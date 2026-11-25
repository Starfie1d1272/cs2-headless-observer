use std::collections::HashSet;

use serde_json::Value;

use super::control::{client_info, ControlDecoder, ObserverSettings};
use super::reporting::unix_ms_now;
use crate::native::password::{transform_password, SecretBytes};
use crate::native::ObserverPort;
use crate::parser::core::{CoreOutput, ObserverCore, SourceIdentity};
use crate::wire::bits::{encode_pb_varint, scalar_varint, wire_fields};
use crate::wire::channel::{
    decode_frame, decode_messages, encode_message, join_messages, reliable_frame,
    ReliableMessageFilter, UnreliableFeedback, UnreliableOrder,
};
use crate::wire::handshake::{
    connect_inner_message, connect_payload, initial_challenge_request, parse_challenge_body,
    parse_connection_inner, Challenge, SignonSequence,
};

pub const DRAIN_TIMEOUT_MS: u64 = 5000;
pub const INITIALIZATION_TIMEOUT_MS: u64 = 30000;
pub const CHANNEL_SILENCE_TIMEOUT_MS: u64 = 15000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DriverPhase {
    Transport,
    Challenge,
    Ticket,
    Connection,
    Channel,
    Draining,
    Blocked,
    Closed,
}

impl DriverPhase {
    pub fn as_str(self) -> &'static str {
        match self {
            DriverPhase::Transport => "transport",
            DriverPhase::Challenge => "challenge",
            DriverPhase::Ticket => "ticket",
            DriverPhase::Connection => "connection",
            DriverPhase::Channel => "channel",
            DriverPhase::Draining => "draining",
            DriverPhase::Blocked => "blocked",
            DriverPhase::Closed => "closed",
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct WorldSyncState {
    pub last_receipt_ms: u64,
    pub new_sent: bool,
    pub prespawn_sent: bool,
    pub spawn_sent: bool,
    pub full_snapshot_processed: bool,
    pub full_sent: bool,
    pub recovery_pending: bool,
    pub request_full_update: bool,
    pub full_update_outstanding: bool,
    pub event_subscription_pending: Option<Vec<i32>>,
    pub processed_entity_tick: Option<i32>,
    pub ack_tick: Option<i32>,
}

impl WorldSyncState {
    pub fn reset(&mut self, now_ms: u64) {
        *self = Self::default();
        self.last_receipt_ms = now_ms;
    }

    pub fn apply_receipt(
        &mut self,
        tick: i32,
        full: bool,
        baseline_ack: Option<u8>,
    ) -> Option<(i32, u8)> {
        if full {
            self.full_snapshot_processed = true;
        }
        self.recovery_pending = false;
        self.full_update_outstanding = false;
        self.processed_entity_tick = Some(tick);
        baseline_ack.map(|b| (tick, b))
    }

    pub fn apply_recovery(&mut self) {
        self.recovery_pending = true;
        self.request_full_update = true;
        self.processed_entity_tick = None;
    }
}

#[derive(Debug, Clone)]
pub enum DriverEmit {
    Cursor {
        record: Value,
        committed_tick: i32,
        world: u64,
        paused: bool,
    },
    RawEvent {
        record: Value,
        world: u64,
    },
    Discontinuity {
        scope: &'static str,
        reason: String,
        world: u64,
    },
}

pub type CaptureCallback = Box<dyn FnMut(&[u8], bool, u64)>;

pub struct ObserverDriver<P: ObserverPort> {
    pub port: P,
    pub host_version: u32,
    password: SecretBytes,
    challenge: Option<Challenge>,
    last_challenge_request_ms: Option<u64>,
    challenge_contexts: HashSet<Vec<u8>>,
    account_id: Option<u32>,
    settings: ObserverSettings,
    query_window_ms: u64,
    query_count: u32,
    pub world_sync: WorldSyncState,
    pub core: ObserverCore,
    pub decoder: ControlDecoder,
    pub signon: SignonSequence,
    pub order: UnreliableOrder,
    pub feedback: UnreliableFeedback,
    pub reliable_filter: ReliableMessageFilter,
    last_feedback_ms: u64,
    pub phase: DriverPhase,
    pub reason: Option<String>,
    pub start_ms: u64,
    pub last_ms: u64,
    pub deadline: u64,
    pub initialization_deadline: u64,
    pub drain_deadline: Option<u64>,
    pub drain_completed: bool,
    pub ever_full: bool,
    pub channel_frames: u64,
    pub received_messages: u64,
    pub last_sdk_age_us: Option<i64>,
    pub max_sdk_age_us: Option<i64>,
    pub last_sdk_sample_ms: Option<u64>,
    pub cursor_rate: Option<f64>,
    last_cursor_sample: Option<(u64, i32, u64, bool)>,
    pub gap: bool,
    pub emitted: Vec<DriverEmit>,
    capture_cb: Option<CaptureCallback>,
}

impl<P: ObserverPort> ObserverDriver<P> {
    pub fn new(
        port: P,
        host_version: u32,
        password: SecretBytes,
        source: String,
        channel: u64,
        now_ms: u64,
    ) -> Result<Self, String> {
        if host_version == 0 || password.len() > 95 || password.as_slice().contains(&0) {
            return Err("configuration-boundary".into());
        }
        Ok(Self {
            port,
            host_version,
            password,
            challenge: None,
            last_challenge_request_ms: None,
            challenge_contexts: HashSet::new(),
            account_id: None,
            settings: ObserverSettings::new(),
            query_window_ms: now_ms,
            query_count: 0,
            world_sync: WorldSyncState {
                last_receipt_ms: now_ms,
                ..Default::default()
            },
            core: ObserverCore::new(SourceIdentity {
                source,
                channel,
                world: 1,
            }),
            decoder: ControlDecoder::new(),
            signon: SignonSequence::new(),
            order: UnreliableOrder::new(Some(0)).map_err(|e| e.to_string())?,
            feedback: UnreliableFeedback::new(),
            reliable_filter: ReliableMessageFilter::new(),
            last_feedback_ms: now_ms,
            phase: DriverPhase::Transport,
            reason: None,
            start_ms: now_ms,
            last_ms: now_ms,
            deadline: now_ms + INITIALIZATION_TIMEOUT_MS,
            initialization_deadline: now_ms + INITIALIZATION_TIMEOUT_MS,
            drain_deadline: None,
            drain_completed: false,
            ever_full: false,
            channel_frames: 0,
            received_messages: 0,
            last_sdk_age_us: None,
            max_sdk_age_us: None,
            last_sdk_sample_ms: None,
            cursor_rate: None,
            last_cursor_sample: None,
            gap: false,
            emitted: Vec::new(),
            capture_cb: None,
        })
    }

    pub fn set_capture_callback(&mut self, cb: CaptureCallback) {
        self.capture_cb = Some(cb);
    }

    pub fn done(&self) -> bool {
        matches!(self.phase, DriverPhase::Blocked | DriverPhase::Closed)
    }

    pub fn close(&mut self) {
        self.password.zeroize();
        self.port.close();
    }

    pub fn step(&mut self, now_ms: u64) -> Result<bool, String> {
        if self.done() {
            return Ok(false);
        }
        if now_ms < self.last_ms {
            return Err("monotonic-clock-regressed".into());
        }
        self.last_ms = now_ms;
        if let Some(dd) = self.drain_deadline {
            if now_ms >= dd {
                return Err("source-drain-timeout".into());
            }
        } else if now_ms >= self.deadline {
            return Err("phase-timeout".into());
        }

        self.port.pump(now_ms);
        if self.drain_deadline.is_some() && self.port.failure() != 7 {
            return Err("source-drain-native-failed".into());
        }
        if self.port.state() == 6 && self.drain_deadline.is_none() {
            if self.port.remote_end_reason() == 1038
                && self.world_sync.full_sent
                && self.port.failure() == 7
            {
                self.phase = DriverPhase::Draining;
                self.drain_deadline = Some(now_ms + DRAIN_TIMEOUT_MS);
            } else {
                return Err("native-session-closed".into());
            }
        }
        if self.phase == DriverPhase::Channel
            && !self.world_sync.full_sent
            && now_ms >= self.initialization_deadline
        {
            return Err("initialization-timeout".into());
        }

        if self.phase == DriverPhase::Transport && self.port.state() == 3 {
            if self.port.remote_id() == 0 {
                return Err("trusted-peer-missing".into());
            }
            self.request_challenge(now_ms)?;
            self.phase = DriverPhase::Challenge;
            self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
        }
        if self.phase == DriverPhase::Ticket && self.port.state() == 5 {
            self.send_connect_with_auth()?;
            self.phase = DriverPhase::Connection;
            self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
        }

        let mut received = 0usize;
        let mut pumped_bytes = 0usize;
        let mut got_empty = false;
        while received < 128 && pumped_bytes < 8 * 1024 * 1024 {
            if self.done() {
                return Ok(false);
            }
            if let Some(dd) = self.drain_deadline {
                if now_ms >= dd {
                    return Err("source-drain-timeout".into());
                }
            }
            let Some(pkt) = self.port.receive()? else {
                got_empty = true;
                break;
            };
            received += 1;
            self.received_messages += 1;
            pumped_bytes += pkt.data.len();
            self.last_sdk_sample_ms = Some(now_ms);
            self.last_sdk_age_us = pkt.sdk_queue_age_us;
            if let Some(age) = pkt.sdk_queue_age_us {
                self.max_sdk_age_us = Some(self.max_sdk_age_us.map_or(age, |m| m.max(age)));
            }
            self.receive_packet(&pkt.data, pkt.reliable, now_ms, pkt.sdk_queue_age_us)?;
        }

        if !self.done() {
            if self.drain_deadline.is_none() {
                self.advance_initialization(now_ms)?;
                self.send_processed_tick(now_ms)?;
            } else if got_empty {
                self.drain_completed = true;
                self.world_sync.processed_entity_tick = None;
                self.phase = DriverPhase::Closed;
                self.reason = Some("source-hltv-stop".into());
                self.emitted.push(DriverEmit::Discontinuity {
                    scope: "connection",
                    reason: "source-hltv-stop".into(),
                    world: self.core.identity.world,
                });
            }
        }

        if self.phase == DriverPhase::Channel && now_ms - self.last_feedback_ms >= 100 {
            let mut encoded = Vec::new();
            if self.world_sync.full_sent && !self.world_sync.recovery_pending {
                if let Some(t) = self.world_sync.processed_entity_tick {
                    let mut pb = Vec::new();
                    encode_pb_varint(1, t as u64, &mut pb);
                    encoded = encode_message(4, &pb).map_err(|e| e.to_string())?.0;
                    self.world_sync.ack_tick = Some(t);
                }
            }
            self.send_channel_feedback(&encoded, now_ms)?;
        }

        if matches!(
            self.phase,
            DriverPhase::Challenge | DriverPhase::Ticket | DriverPhase::Connection
        ) {
            if let Some(last_req) = self.last_challenge_request_ms {
                if now_ms - last_req >= 500 {
                    self.request_challenge(now_ms)?;
                }
            }
        }

        Ok(!got_empty)
    }

    fn request_challenge(&mut self, now_ms: u64) -> Result<(), String> {
        let num = self.challenge.as_ref().map(|c| c.number).unwrap_or(0);
        let req = initial_challenge_request(num);
        self.port.send(&req, 5)?;
        self.challenge_contexts
            .insert(req[5..req.len() - 1].to_vec());
        self.last_challenge_request_ms = Some(now_ms);
        Ok(())
    }

    fn send_connect_with_auth(&mut self) -> Result<(), String> {
        let challenge = self.challenge.clone().ok_or("missing-challenge")?;
        let hv = self.host_version;
        let pw_enc = transform_password(self.password.as_slice(), challenge.number)
            .map_err(|e| e.to_string())?;
        let mut acct_id = self.account_id;
        let msg = if challenge.auth_protocol == 3 {
            let mut out_msg = Vec::new();
            self.port.with_auth(|auth| {
                if auth.len() < 8 {
                    return Err("local-account-id-missing".into());
                }
                let id = u64::from_le_bytes(auth[0..8].try_into().unwrap()) as u32;
                if id == 0 {
                    return Err("local-account-id-missing".into());
                }
                acct_id = Some(id);
                let payload = connect_payload(
                    hv,
                    &challenge,
                    auth,
                    "CS2 Headless Observer",
                    pw_enc.as_deref(),
                    0,
                    false,
                )
                .map_err(|e| e.to_string())?;
                out_msg = connect_inner_message(&payload).map_err(|e| e.to_string())?;
                Ok(())
            })?;
            out_msg
        } else {
            if acct_id.unwrap_or(0) == 0 {
                return Err("local-account-id-missing".into());
            }
            let payload = connect_payload(
                hv,
                &challenge,
                &[],
                "CS2 Headless Observer",
                pw_enc.as_deref(),
                0,
                false,
            )
            .map_err(|e| e.to_string())?;
            connect_inner_message(&payload).map_err(|e| e.to_string())?
        };
        self.account_id = acct_id;
        self.port.send(&msg, 5)
    }

    pub fn receive_packet(
        &mut self,
        data: &[u8],
        reliable: bool,
        now_ms: u64,
        sdk_age_us: Option<i64>,
    ) -> Result<(), String> {
        if matches!(
            self.phase,
            DriverPhase::Challenge | DriverPhase::Ticket | DriverPhase::Connection
        ) && (self.phase == DriverPhase::Challenge || data.starts_with(b"\xff\xff\xff\xffA"))
        {
            if reliable || !data.starts_with(b"\xff\xff\xff\xffA") {
                return Err("unexpected-challenge-message".into());
            }
            let challenge = parse_challenge_body(&data[5..]).map_err(|e| e.to_string())?;
            let peer = self.port.remote_id();
            if peer == 0 || (challenge.server_steam_id != 0 && challenge.server_steam_id != peer) {
                return Err("challenge-peer-mismatch".into());
            }
            if !self.challenge_contexts.contains(&challenge.context) {
                return Err("challenge-context-mismatch".into());
            }
            if let Some(ref prev) = self.challenge {
                if challenge.auth_protocol != prev.auth_protocol || challenge.secure != prev.secure
                {
                    return Err("challenge-auth-changed".into());
                }
                self.challenge = Some(challenge);
                if self.phase == DriverPhase::Connection {
                    self.send_connect_with_auth()?;
                }
                return Ok(());
            }
            let auth_proto = challenge.auth_protocol;
            self.challenge = Some(challenge);
            if auth_proto == 2 {
                let own = self.port.local_id();
                if own == 0 {
                    return Err("local-account-id-missing".into());
                }
                self.account_id = Some(own as u32);
                self.port.accept_server_auth2()?;
                self.send_connect_with_auth()?;
                self.phase = DriverPhase::Connection;
                self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
            } else {
                self.port.request_ticket()?;
                self.phase = DriverPhase::Ticket;
                self.deadline = now_ms + INITIALIZATION_TIMEOUT_MS;
            }
            return Ok(());
        }

        if self.phase == DriverPhase::Connection {
            if reliable {
                return Err("unexpected-connection-reliability".into());
            }
            let response = parse_connection_inner(data).map_err(|e| e.to_string())?;
            self.password.zeroize();
            if response.addon_name_bytes.unwrap_or(0) > 0 {
                self.phase = DriverPhase::Blocked;
                self.reason = Some("addon-initialization-required".into());
                return Ok(());
            }
            self.send_connected_ack()?;
            self.phase = DriverPhase::Channel;
            self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
            self.challenge = None;
            return Ok(());
        }

        if !matches!(self.phase, DriverPhase::Channel | DriverPhase::Draining) {
            return Err("unexpected-protocol-phase".into());
        }
        if !reliable
            && (data.starts_with(b"\xff\xff\xff\xffA") || data.starts_with(b"\xff\xff\xff\xffB"))
        {
            return Ok(());
        }

        let frame = decode_frame(data, reliable).map_err(|e| e.to_string())?;
        if let Some(ref mut cb) = self.capture_cb {
            cb(data, reliable, now_ms - self.start_ms);
        }
        self.channel_frames += 1;
        self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
        self.feedback.observe(&frame).map_err(|e| e.to_string())?;
        if !frame.reliable {
            let ord = self.order.accept(&frame).map_err(|e| e.to_string())?;
            if !ord.accepted {
                return Ok(());
            }
            if ord.gap > 0 {
                self.last_cursor_sample = None;
                self.cursor_rate = None;
                self.gap = true;
            }
        }

        let mut discard = HashSet::new();
        discard.insert(76u32);
        let (msgs, _) = decode_messages(&frame.body, None, &discard).map_err(|e| e.to_string())?;
        let mut context_tick: i32 = if frame.reliable {
            frame.reliable_tick_hint.unwrap_or(0) as i32
        } else {
            0
        };

        for msg in msgs {
            if msg.message_id == 4 || msg.message_id == 55 {
                if let Ok(fields) = wire_fields(&msg.body, 4 * 1024 * 1024) {
                    let tag = if msg.message_id == 4 { 1 } else { 12 };
                    if let Ok(Some(v)) = scalar_varint(&fields, tag) {
                        let cand = (v as u32) as i32;
                        if cand > 0 {
                            context_tick = cand;
                        }
                    }
                }
            }
            if !self
                .reliable_filter
                .accept(msg.message_id, &msg.body)
                .map_err(|e| e.to_string())?
            {
                continue;
            }
            if msg.message_id == 58 && self.drain_deadline.is_none() {
                if now_ms - self.query_window_ms >= 1000 {
                    self.query_window_ms = now_ms;
                    self.query_count = 0;
                }
                self.query_count += 1;
                if self.query_count > 32 {
                    return Err("observer-cvar-query-rate-budget".into());
                }
                let resp = self.settings.query(&msg.body).map_err(|e| e.to_string())?;
                let (encoded, _) = encode_message(25, &resp).map_err(|e| e.to_string())?;
                let rf = reliable_frame(&encoded, 0).map_err(|e| e.to_string())?;
                self.port.send(&rf, 8)?;
            }

            if msg.message_id == 7 {
                let fields = wire_fields(&msg.body, 65535).map_err(|e| e.to_string())?;
                let state = scalar_varint(&fields, 1).map_err(|e| e.to_string())?;
                if state == Some(2) {
                    self.reset_world_protocol(now_ms, false);
                }
                self.signon.receive(&msg.body).map_err(|e| e.to_string())?;
                if state == Some(7) {
                    self.reset_world_protocol(now_ms, true);
                }
                if matches!(state, Some(2) | Some(7)) && self.drain_deadline.is_none() {
                    self.send_connected_ack()?;
                }
            } else {
                self.decoder.consume(msg.message_id, &msg.body)?;
                if msg.message_id == 40 {
                    if let Some(ref srv) = self.decoder.server {
                        self.signon
                            .server_info(srv.server_count)
                            .map_err(|e| e.to_string())?;
                    }
                } else if msg.message_id == 8 || msg.message_id == 11 {
                    self.core
                        .admit_creation_sequence(self.decoder.max_creation_sequence)?;
                } else if msg.message_id == 51 {
                    self.reset_world_protocol(now_ms, false);
                }

                if msg.message_id != 76 {
                    let outputs = self
                        .core
                        .consume(msg.message_id, &msg.body, Some(context_tick));
                    self.process_core_outputs(outputs, now_ms, sdk_age_us)?;
                }
            }
        }

        if self.drain_deadline.is_none() {
            self.advance_initialization(now_ms)?;
            self.send_processed_tick(now_ms)?;
        }
        Ok(())
    }

    fn process_core_outputs(
        &mut self,
        outputs: Vec<CoreOutput>,
        now_ms: u64,
        sdk_age_us: Option<i64>,
    ) -> Result<(), String> {
        let obs_ms = unix_ms_now();
        for out in outputs {
            match out {
                CoreOutput::Receipt {
                    tick,
                    full,
                    baseline_ack,
                    ..
                } => {
                    if let Some((t, bank)) = self.world_sync.apply_receipt(tick, full, baseline_ack)
                    {
                        let mut pb = Vec::new();
                        encode_pb_varint(1, t as u64, &mut pb);
                        encode_pb_varint(2, bank as u64, &mut pb);
                        let (encoded, _) = encode_message(23, &pb).map_err(|e| e.to_string())?;
                        let rf = reliable_frame(&encoded, 0).map_err(|e| e.to_string())?;
                        if self.drain_deadline.is_none() {
                            self.port.send(&rf, 8)?;
                        }
                    }
                }
                CoreOutput::Cursor(c) => {
                    let paused = c.round_clock.pause.active.unwrap_or(false);
                    let world = c.world;
                    let committed = c.committed_tick;
                    self.cursor_rate = None;
                    if let Some((lw, lt, lms, lp)) = self.last_cursor_sample {
                        let elapsed = now_ms.saturating_sub(lms);
                        if world == lw
                            && committed > lt
                            && elapsed > 0
                            && elapsed <= 3000
                            && !lp
                            && !paused
                        {
                            self.cursor_rate =
                                Some(((committed - lt) as f64) * 1000.0 / (elapsed as f64));
                        }
                    }
                    self.last_cursor_sample = Some((world, committed, now_ms, paused));
                    self.gap = false;

                    let mut val = serde_json::to_value(&c).map_err(|e| e.to_string())?;
                    if let Some(obj) = val.as_object_mut() {
                        obj.insert("contextTick".into(), Value::from(c.tick));
                        obj.insert(
                            "sdkQueueAgeUs".into(),
                            sdk_age_us.map(Value::from).unwrap_or(Value::Null),
                        );
                        obj.insert("observedAt".into(), Value::from(obs_ms));
                    }
                    self.emitted.push(DriverEmit::Cursor {
                        record: val,
                        committed_tick: committed,
                        world,
                        paused,
                    });
                }
                CoreOutput::RawEvent(e) => {
                    let world = e.world;
                    let ctx = e.tick;
                    let mut val = serde_json::to_value(&e).map_err(|e| e.to_string())?;
                    if let Some(obj) = val.as_object_mut() {
                        obj.insert("contextTick".into(), Value::from(ctx));
                        obj.insert(
                            "sdkQueueAgeUs".into(),
                            sdk_age_us.map(Value::from).unwrap_or(Value::Null),
                        );
                        obj.insert("observedAt".into(), Value::from(obs_ms));
                    }
                    self.emitted
                        .push(DriverEmit::RawEvent { record: val, world });
                }
                CoreOutput::EventSubscriptions { ids, .. } => {
                    self.world_sync.event_subscription_pending = Some(ids);
                }
                CoreOutput::Gap { reason } => {
                    self.last_cursor_sample = None;
                    self.cursor_rate = None;
                    self.gap = true;
                    self.emitted.push(DriverEmit::Discontinuity {
                        scope: "snapshot",
                        reason,
                        world: self.core.identity.world,
                    });
                }
                CoreOutput::Recovery {
                    reason,
                    world_reinitialization,
                    ..
                } => {
                    self.last_cursor_sample = None;
                    self.cursor_rate = None;
                    self.gap = true;
                    self.world_sync.apply_recovery();
                    if world_reinitialization {
                        return Err(format!("world-reinitialization-required: {reason}"));
                    }
                    self.emitted.push(DriverEmit::Discontinuity {
                        scope: "snapshot",
                        reason,
                        world: self.core.identity.world,
                    });
                }
                CoreOutput::WorldReset { reason } => {
                    self.last_cursor_sample = None;
                    self.cursor_rate = None;
                    self.gap = true;
                    self.emitted.push(DriverEmit::Discontinuity {
                        scope: "world",
                        reason,
                        world: self.core.identity.world,
                    });
                }
                CoreOutput::Blocked { reason } => {
                    return Err(reason);
                }
                CoreOutput::Diagnostic { .. } => {}
            }
        }
        Ok(())
    }

    fn reset_world_protocol(&mut self, now_ms: u64, replace_client: bool) {
        self.decoder.reset_world();
        let next_world = self.core.identity.world + 1;
        self.core.reset_world(next_world);
        self.last_cursor_sample = None;
        self.cursor_rate = None;
        self.gap = true;
        self.initialization_deadline = now_ms + INITIALIZATION_TIMEOUT_MS;
        self.signon = SignonSequence::new();
        self.world_sync.reset(now_ms);
        if replace_client {
            self.reliable_filter.replace_client_owner();
        }
    }

    fn send_connected_ack(&mut self) -> Result<(), String> {
        let (msg_id, payload) = self.signon.acknowledgement().map_err(|e| e.to_string())?;
        let m1 = encode_message(6, &self.settings.userinfo()).map_err(|e| e.to_string())?;
        let m2 = encode_message(msg_id, &payload).map_err(|e| e.to_string())?;
        let (joined, _) = join_messages(&[m1, m2]).map_err(|e| e.to_string())?;
        let rf = reliable_frame(&joined, 0).map_err(|e| e.to_string())?;
        self.port.send(&rf, 8)
    }

    pub fn advance_initialization(&mut self, _now_ms: u64) -> Result<(), String> {
        if self.signon.state > 3 {
            if let Some(ids) = self.world_sync.event_subscription_pending.take() {
                if let Some(ref srv) = self.decoder.server {
                    let mut words = [0u32; 16];
                    for eid in ids {
                        if !(0..512).contains(&eid) {
                            return Err("event-subscription-id".into());
                        }
                        let uid = eid as usize;
                        words[uid / 32] |= 1u32 << (uid % 32);
                    }
                    let mut payload = Vec::new();
                    encode_pb_varint(1, (srv.player_slot as u32) as u64, &mut payload);
                    for w in words {
                        encode_pb_varint(2, w as u64, &mut payload);
                    }
                    let (encoded, _) = encode_message(206, &payload).map_err(|e| e.to_string())?;
                    let rf = reliable_frame(&encoded, 0).map_err(|e| e.to_string())?;
                    self.port.send(&rf, 8)?;
                }
            }
        }

        if self.signon.state == 3 && !self.world_sync.new_sent {
            if self.decoder.server.is_none() {
                return Err("new-before-serverinfo".into());
            }
            let sc = self.signon.spawn_count.ok_or("serverinfo-missing")?;
            let acct = self.account_id.unwrap_or(1);
            let info = client_info(sc, acct, 0);
            let (enc_info, _) = encode_message(20, &info).map_err(|e| e.to_string())?;
            let rf1 = reliable_frame(&enc_info, 0).map_err(|e| e.to_string())?;
            self.port.send(&rf1, 8)?;
            self.signon.finish_new().map_err(|e| e.to_string())?;
            let (mid, payload) = self.signon.acknowledgement().map_err(|e| e.to_string())?;
            let (enc_ack, _) = encode_message(mid, &payload).map_err(|e| e.to_string())?;
            let rf2 = reliable_frame(&enc_ack, 0).map_err(|e| e.to_string())?;
            self.port.send(&rf2, 8)?;
            self.world_sync.new_sent = true;
        } else if self.signon.state == 4 && !self.world_sync.prespawn_sent {
            if !self.core.ready() || self.core.class_count() == 0 {
                self.phase = DriverPhase::Blocked;
                self.reason = Some("prespawn-initialization-required".into());
                return Ok(());
            }
            let (mid, payload) = self.signon.acknowledgement().map_err(|e| e.to_string())?;
            let (enc_ack, _) = encode_message(mid, &payload).map_err(|e| e.to_string())?;
            let rf = reliable_frame(&enc_ack, 0).map_err(|e| e.to_string())?;
            self.port.send(&rf, 8)?;
            self.world_sync.prespawn_sent = true;
        }

        if matches!(self.signon.state, 4..=6) && self.core.ready() {
            for handle in self.decoder.ready_world_groups()? {
                let mut pb = Vec::new();
                encode_pb_varint(1, handle as u64, &mut pb);
                let (encoded, _) = encode_message(13, &pb).map_err(|e| e.to_string())?;
                let rf = reliable_frame(&encoded, 0).map_err(|e| e.to_string())?;
                self.port.send(&rf, 8)?;
            }
        }

        if self.signon.state == 5 && !self.world_sync.spawn_sent {
            if !self.core.ready() || !self.world_sync.prespawn_sent {
                return Err("spawn-before-parser-initialization".into());
            }
            if self.decoder.spawn_groups.len() != self.decoder.ready_spawn_groups.len() {
                return Ok(());
            }
            self.signon.finish_spawn().map_err(|e| e.to_string())?;
            let (mid, payload) = self.signon.acknowledgement().map_err(|e| e.to_string())?;
            let (enc_ack, _) = encode_message(mid, &payload).map_err(|e| e.to_string())?;
            let rf = reliable_frame(&enc_ack, 0).map_err(|e| e.to_string())?;
            self.port.send(&rf, 8)?;
            self.world_sync.spawn_sent = true;
        }

        self.acknowledge_full()
    }

    fn acknowledge_full(&mut self) -> Result<(), String> {
        if self.signon.state == 6
            && !self.world_sync.full_sent
            && self.world_sync.full_snapshot_processed
        {
            if !self.world_sync.spawn_sent {
                return Err("full-before-spawn-acknowledgement".into());
            }
            let (mid, payload) = self.signon.acknowledgement().map_err(|e| e.to_string())?;
            let (enc_ack, _) = encode_message(mid, &payload).map_err(|e| e.to_string())?;
            let rf = reliable_frame(&enc_ack, 0).map_err(|e| e.to_string())?;
            self.port.send(&rf, 8)?;
            self.world_sync.full_sent = true;
            self.ever_full = true;
        }
        Ok(())
    }

    pub fn send_processed_tick(&mut self, now_ms: u64) -> Result<(), String> {
        if !self.world_sync.full_sent && !self.world_sync.spawn_sent {
            return Ok(());
        }
        if self.world_sync.full_snapshot_processed && !self.world_sync.full_sent {
            if self.signon.state == 5 {
                self.signon
                    .finish_full_snapshot()
                    .map_err(|e| e.to_string())?;
            }
            self.acknowledge_full()?;
        }
        if self.world_sync.recovery_pending {
            if self.world_sync.request_full_update && !self.world_sync.full_update_outstanding {
                let mut pb = Vec::new();
                encode_pb_varint(1, 0xFFFF_FFFF, &mut pb);
                let (encoded, _) = encode_message(4, &pb).map_err(|e| e.to_string())?;
                let rf = reliable_frame(&encoded, 0).map_err(|e| e.to_string())?;
                self.port.send(&rf, 8)?;
                self.world_sync.ack_tick = Some(-1);
                self.world_sync.full_update_outstanding = true;
            }
            return Ok(());
        }
        if !self.world_sync.full_sent {
            return Ok(());
        }
        let Some(tick) = self.world_sync.processed_entity_tick else {
            return Ok(());
        };
        if self.world_sync.ack_tick == Some(tick)
            || now_ms.saturating_sub(self.world_sync.last_receipt_ms) < 100
        {
            return Ok(());
        }
        let mut pb = Vec::new();
        encode_pb_varint(1, tick as u64, &mut pb);
        let (encoded, _) = encode_message(4, &pb).map_err(|e| e.to_string())?;
        self.send_channel_feedback(&encoded, now_ms)?;
        self.world_sync.ack_tick = Some(tick);
        self.world_sync.last_receipt_ms = now_ms;
        Ok(())
    }

    fn send_channel_feedback(&mut self, encoded: &[u8], now_ms: u64) -> Result<(), String> {
        let pkt = self.feedback.frame(encoded).map_err(|e| e.to_string())?;
        self.port.send(&pkt, 1)?;
        self.last_feedback_ms = now_ms;
        self.world_sync.last_receipt_ms = now_ms;
        Ok(())
    }
}
