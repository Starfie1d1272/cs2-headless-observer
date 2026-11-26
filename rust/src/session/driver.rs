use std::collections::HashSet;

use super::SessionError;
use crate::native::password::{transform_password, SecretBytes};
use crate::native::ObserverPort;
use crate::parser::core::{CoreOutput, CursorRecord, ObserverCore, RawEventRecord, SourceIdentity};
use crate::wire::bits::{
    encode_pb_bytes, encode_pb_varint, scalar_bytes, scalar_varint, wire_fields, WireError,
};
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

pub struct ObserverSettings {
    pub values: Vec<(&'static [u8], &'static [u8])>,
}

impl Default for ObserverSettings {
    fn default() -> Self {
        Self::new()
    }
}

impl ObserverSettings {
    pub fn new() -> Self {
        Self {
            values: vec![
                (b"name", b"CS2 Headless Observer"),
                (b"tv_relay", b"0"),
                (b"rate", b"786432"),
            ],
        }
    }

    pub fn userinfo(&self) -> Vec<u8> {
        let mut entries = Vec::new();
        for &(name, value) in &self.values {
            let mut kv = Vec::new();
            encode_pb_bytes(1, name, &mut kv);
            encode_pb_bytes(2, value, &mut kv);
            encode_pb_bytes(1, &kv, &mut entries);
        }
        let mut out = Vec::new();
        encode_pb_bytes(1, &entries, &mut out);
        out
    }

    pub fn query(&self, payload: &[u8]) -> Result<Vec<u8>, WireError> {
        let values = wire_fields(payload, 4096)?;
        let cookie = scalar_varint(&values, 1)?.unwrap_or(0) as u32;
        let name = scalar_bytes(&values, 2)?.unwrap_or(&[]);
        if name.len() > 256 || name.contains(&0) {
            return Err(WireError::StringBudget);
        }
        let found = self
            .values
            .iter()
            .find(|&&(k, _)| k == name)
            .map(|&(_, v)| v);
        let mut out = Vec::new();
        encode_pb_varint(1, cookie as u64, &mut out);
        encode_pb_varint(2, if found.is_none() { 1 } else { 0 }, &mut out);
        encode_pb_bytes(3, name, &mut out);
        encode_pb_bytes(4, found.unwrap_or(&[]), &mut out);
        Ok(out)
    }
}

pub fn client_info(server_count: u32, account_id: u32, send_table_crc: u32) -> Vec<u8> {
    let mut out = Vec::with_capacity(32);
    out.push(0x0d);
    out.extend_from_slice(&send_table_crc.to_le_bytes());
    encode_pb_varint(2, server_count as u64, &mut out);
    encode_pb_varint(3, 0, &mut out);
    encode_pb_varint(5, account_id as u64, &mut out);
    out
}

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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RecoveryState {
    #[default]
    Normal,
    NeedFullUpdate,
    WaitingFull,
}

#[derive(Debug, Clone, Default)]
pub struct WorldSyncState {
    pub last_receipt_ms: u64,
    pub new_sent: bool,
    pub prespawn_sent: bool,
    pub spawn_sent: bool,
    pub full_snapshot_processed: bool,
    pub full_sent: bool,
    pub recovery: RecoveryState,
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
        self.recovery = RecoveryState::Normal;
        self.processed_entity_tick = Some(tick);
        baseline_ack.map(|b| (tick, b))
    }

    pub fn apply_recovery(&mut self) {
        self.recovery = RecoveryState::NeedFullUpdate;
        self.full_snapshot_processed = false;
        self.processed_entity_tick = None;
    }
}

#[derive(Debug, Clone)]
pub enum DriverEmit {
    Cursor(Box<CursorRecord>),
    RawEvent(Box<RawEventRecord>),
    Discontinuity {
        scope: &'static str,
        reason: String,
        world: u64,
    },
    Diagnostic {
        reason: String,
        event_id: Option<i32>,
    },
}

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
    pub context_tick: Option<i32>,
    pub last_sdk_age_us: Option<i64>,
    pub max_sdk_age_us: Option<i64>,
    pub window_decode_us: u64,
    pub window_max_decode_us: Option<u64>,
    pub emitted: Vec<DriverEmit>,
}

impl<P: ObserverPort> ObserverDriver<P> {
    pub fn new(
        port: P,
        host_version: u32,
        password: SecretBytes,
        channel: u64,
        now_ms: u64,
    ) -> Result<Self, SessionError> {
        if host_version == 0 || password.len() > 95 || password.as_slice().contains(&0) {
            return Err(SessionError::ConfigurationBoundary);
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
            core: ObserverCore::new(SourceIdentity { channel, world: 1 }),
            signon: SignonSequence::new(),
            order: UnreliableOrder::new(Some(0))?,
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
            context_tick: None,
            last_sdk_age_us: None,
            max_sdk_age_us: None,
            window_decode_us: 0,
            window_max_decode_us: None,
            emitted: Vec::new(),
        })
    }

    pub fn set_offline_account_id(&mut self, id: u32) {
        self.account_id = Some(id);
    }

    pub fn take_decode_window(&mut self) -> (Option<u64>, Option<u64>) {
        let max = self.window_max_decode_us.take();
        let sum = if max.is_some() {
            Some(self.window_decode_us)
        } else {
            None
        };
        self.window_decode_us = 0;
        (sum, max)
    }

    pub fn done(&self) -> bool {
        matches!(self.phase, DriverPhase::Blocked | DriverPhase::Closed)
    }

    pub fn close(&mut self) {
        self.password.zeroize();
        self.port.close();
    }

    pub fn step(&mut self, now_ms: u64) -> Result<bool, SessionError> {
        self.step_with_clock(|| now_ms)
    }

    pub fn step_with_clock<F>(&mut self, mut clock_ms: F) -> Result<bool, SessionError>
    where
        F: FnMut() -> u64,
    {
        if self.done() {
            return Ok(false);
        }
        let mut now_ms = clock_ms();
        if now_ms < self.last_ms {
            return Err(SessionError::ClockRegressed);
        }
        self.last_ms = now_ms;
        if let Some(dd) = self.drain_deadline {
            if now_ms >= dd {
                return Err(SessionError::SourceDrainTimeout);
            }
        } else if now_ms >= self.deadline {
            return Err(SessionError::PhaseTimeout);
        }

        self.port.pump(now_ms);
        if self.drain_deadline.is_some() && self.port.failure() != 7 {
            return Err(SessionError::SourceDrainNativeFailed);
        }
        if self.port.state() == 6 && self.drain_deadline.is_none() {
            if self.port.remote_end_reason() == 1038
                && self.world_sync.full_sent
                && self.port.failure() == 7
            {
                self.phase = DriverPhase::Draining;
                self.drain_deadline = Some(now_ms + DRAIN_TIMEOUT_MS);
            } else {
                return Err(SessionError::NativeSessionClosed);
            }
        }
        if self.phase == DriverPhase::Channel
            && !self.world_sync.full_sent
            && now_ms >= self.initialization_deadline
        {
            return Err(SessionError::InitializationTimeout);
        }

        if self.phase == DriverPhase::Transport && self.port.state() == 3 {
            if self.port.remote_id() == 0 {
                return Err(SessionError::TrustedPeerMissing);
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
            now_ms = clock_ms();
            if let Some(dd) = self.drain_deadline {
                if now_ms >= dd {
                    return Err(SessionError::SourceDrainTimeout);
                }
            }
            let Some(pkt) = self.port.receive().map_err(SessionError::Native)? else {
                got_empty = true;
                break;
            };
            received += 1;
            self.received_messages += 1;
            pumped_bytes += pkt.data.len();
            self.last_sdk_age_us = pkt.sdk_queue_age_us;
            if let Some(age) = pkt.sdk_queue_age_us {
                self.max_sdk_age_us = Some(self.max_sdk_age_us.map_or(age, |m| m.max(age)));
            }
            now_ms = clock_ms();
            self.receive_packet(
                &pkt.data,
                pkt.reliable,
                now_ms,
                pkt.sdk_queue_age_us,
                Some(pkt.dequeue_ns),
            )?;
        }

        now_ms = clock_ms();
        if !self.done() {
            if self.drain_deadline.is_none() {
                self.advance_initialization()?;
                self.send_processed_tick(now_ms)?;
            } else if got_empty {
                self.drain_completed = true;
                self.world_sync.processed_entity_tick = None;
                self.phase = DriverPhase::Closed;
                self.reason = Some("source-hltv-stop".into());
            }
        }

        if self.phase == DriverPhase::Channel && now_ms.saturating_sub(self.last_feedback_ms) >= 100
        {
            let mut encoded = Vec::new();
            if self.world_sync.full_sent && self.world_sync.recovery == RecoveryState::Normal {
                if let Some(t) = self.world_sync.processed_entity_tick {
                    let mut pb = Vec::new();
                    encode_pb_varint(1, t as u64, &mut pb);
                    encoded = encode_message(4, &pb)?.0;
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
                if now_ms.saturating_sub(last_req) >= 500 {
                    self.request_challenge(now_ms)?;
                }
            }
        }

        Ok(!got_empty)
    }

    fn request_challenge(&mut self, now_ms: u64) -> Result<(), SessionError> {
        let num = self.challenge.as_ref().map(|c| c.number).unwrap_or(0);
        let req = initial_challenge_request(num);
        self.port.send(&req, 5).map_err(SessionError::Native)?;
        self.challenge_contexts
            .insert(req[5..req.len() - 1].to_vec());
        self.last_challenge_request_ms = Some(now_ms);
        Ok(())
    }

    fn send_connect_with_auth(&mut self) -> Result<(), SessionError> {
        let challenge = self
            .challenge
            .clone()
            .ok_or(SessionError::UnexpectedChallengeMessage)?;
        let hv = self.host_version;
        let pw_enc = transform_password(self.password.as_slice(), challenge.number)?;
        let mut acct_id = self.account_id;
        let msg = if challenge.auth_protocol == 3 {
            let mut out_msg = Vec::new();
            self.port
                .with_auth(|auth| {
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
                })
                .map_err(SessionError::Native)?;
            out_msg
        } else {
            if acct_id.unwrap_or(0) == 0 {
                return Err(SessionError::LocalAccountIdMissing);
            }
            let payload = connect_payload(
                hv,
                &challenge,
                &[],
                "CS2 Headless Observer",
                pw_enc.as_deref(),
                0,
                false,
            )?;
            connect_inner_message(&payload)?
        };
        self.account_id = acct_id;
        self.port.send(&msg, 5).map_err(SessionError::Native)
    }

    pub fn receive_packet(
        &mut self,
        data: &[u8],
        reliable: bool,
        now_ms: u64,
        sdk_age_us: Option<i64>,
        dequeue_ns: Option<u64>,
    ) -> Result<(), SessionError> {
        if matches!(
            self.phase,
            DriverPhase::Challenge | DriverPhase::Ticket | DriverPhase::Connection
        ) && (self.phase == DriverPhase::Challenge || data.starts_with(b"\xff\xff\xff\xffA"))
        {
            if reliable || !data.starts_with(b"\xff\xff\xff\xffA") {
                return Err(SessionError::UnexpectedChallengeMessage);
            }
            let challenge = parse_challenge_body(&data[5..])?;
            let peer = self.port.remote_id();
            if peer == 0 || (challenge.server_steam_id != 0 && challenge.server_steam_id != peer) {
                return Err(SessionError::ChallengePeerMismatch);
            }
            if !self.challenge_contexts.contains(&challenge.context) {
                return Err(SessionError::ChallengeContextMismatch);
            }
            if let Some(ref prev) = self.challenge {
                if challenge.auth_protocol != prev.auth_protocol || challenge.secure != prev.secure
                {
                    return Err(SessionError::ChallengeAuthChanged);
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
                    return Err(SessionError::LocalAccountIdMissing);
                }
                self.account_id = Some(own as u32);
                self.port
                    .accept_server_auth2()
                    .map_err(SessionError::Native)?;
                self.send_connect_with_auth()?;
                self.phase = DriverPhase::Connection;
                self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
            } else {
                self.port.request_ticket().map_err(SessionError::Native)?;
                self.phase = DriverPhase::Ticket;
                self.deadline = now_ms + INITIALIZATION_TIMEOUT_MS;
            }
            return Ok(());
        }

        if self.phase == DriverPhase::Connection {
            if reliable {
                return Err(SessionError::UnexpectedConnectionReliability);
            }
            let response = parse_connection_inner(data)?;
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
            return Err(SessionError::UnexpectedProtocolPhase);
        }
        if !reliable
            && (data.starts_with(b"\xff\xff\xff\xffA") || data.starts_with(b"\xff\xff\xff\xffB"))
        {
            return Ok(());
        }

        let frame = decode_frame(data, reliable)?;
        self.channel_frames += 1;
        self.deadline = now_ms + CHANNEL_SILENCE_TIMEOUT_MS;
        self.feedback.observe(&frame)?;
        if !frame.reliable {
            let ord = self.order.accept(&frame)?;
            if !ord.accepted {
                return Ok(());
            }
            let _ = ord.gap;
        }

        let (msgs, _) = decode_messages(&frame.body, None, Some(76))?;
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
            self.context_tick = Some(context_tick);
            if !self.reliable_filter.accept(msg.message_id, &msg.body)? {
                continue;
            }
            if msg.message_id == 58 && self.drain_deadline.is_none() {
                if now_ms.saturating_sub(self.query_window_ms) >= 1000 {
                    self.query_window_ms = now_ms;
                    self.query_count = 0;
                }
                self.query_count += 1;
                if self.query_count > 32 {
                    return Err(SessionError::CvarQueryRateBudget);
                }
                let resp = self.settings.query(&msg.body)?;
                let (encoded, _) = encode_message(25, &resp)?;
                let rf = reliable_frame(&encoded, 0)?;
                self.port.send(&rf, 8).map_err(SessionError::Native)?;
            }

            if msg.message_id == 7 {
                let fields = wire_fields(&msg.body, 65535)?;
                let state = scalar_varint(&fields, 1)?;
                if state == Some(2) {
                    self.enter_new_world(now_ms, "signon-connected", false, true);
                }
                self.signon.receive(&msg.body)?;
                if state == Some(7) {
                    self.enter_new_world(now_ms, "signon-changelevel", true, true);
                }
                if matches!(state, Some(2) | Some(7)) && self.drain_deadline.is_none() {
                    self.send_connected_ack()?;
                }
            } else if msg.message_id != 76 {
                let t0 = std::time::Instant::now();
                let outputs =
                    self.core
                        .consume(msg.message_id, &msg.body, Some(context_tick), sdk_age_us);
                let elapsed_us = t0.elapsed().as_micros() as u64;
                self.window_decode_us = self.window_decode_us.saturating_add(elapsed_us);
                self.window_max_decode_us = Some(
                    self.window_max_decode_us
                        .map_or(elapsed_us, |m| m.max(elapsed_us)),
                );
                if msg.message_id == 40 {
                    if let Some(ref srv) = self.core.server {
                        self.signon.server_info(srv.server_count)?;
                    }
                }
                self.process_core_outputs(outputs, now_ms, dequeue_ns)?;
            }
        }

        if self.drain_deadline.is_none() {
            self.advance_initialization()?;
            self.send_processed_tick(now_ms)?;
        }
        Ok(())
    }

    fn process_core_outputs(
        &mut self,
        outputs: Vec<CoreOutput>,
        now_ms: u64,
        dequeue_ns: Option<u64>,
    ) -> Result<(), SessionError> {
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
                        let (encoded, _) = encode_message(23, &pb)?;
                        let rf = reliable_frame(&encoded, 0)?;
                        if self.drain_deadline.is_none() {
                            self.port.send(&rf, 8).map_err(SessionError::Native)?;
                        }
                    }
                }
                CoreOutput::Cursor(c) => {
                    self.emitted.push(DriverEmit::Cursor(Box::new(c)));
                }
                CoreOutput::RawEvent(mut e) => {
                    e.dequeue_ns = dequeue_ns;
                    self.emitted.push(DriverEmit::RawEvent(Box::new(e)));
                }
                CoreOutput::EventSubscriptions { ids, .. } => {
                    self.world_sync.event_subscription_pending = Some(ids);
                }
                CoreOutput::Gap { reason } => {
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
                    self.world_sync.apply_recovery();
                    if world_reinitialization {
                        return Err(SessionError::WorldReinitializationRequired(reason));
                    }
                    self.emitted.push(DriverEmit::Discontinuity {
                        scope: "snapshot",
                        reason,
                        world: self.core.identity.world,
                    });
                }
                CoreOutput::WorldReset { reason } => {
                    self.enter_new_world(now_ms, &reason, false, false);
                }
                CoreOutput::Blocked { reason } => {
                    return Err(SessionError::Protocol(reason));
                }
                CoreOutput::Diagnostic { reason, event_id } => {
                    self.emitted
                        .push(DriverEmit::Diagnostic { reason, event_id });
                }
            }
        }
        Ok(())
    }

    fn enter_new_world(
        &mut self,
        now_ms: u64,
        reason: &str,
        replace_client: bool,
        reset_core: bool,
    ) {
        if reset_core {
            self.core.reset_world(self.core.identity.world + 1);
        }

        self.initialization_deadline = now_ms + INITIALIZATION_TIMEOUT_MS;
        self.signon = SignonSequence::new();
        self.world_sync.reset(now_ms);
        if replace_client {
            self.reliable_filter.replace_client_owner();
        }
        self.emitted.push(DriverEmit::Discontinuity {
            scope: "world",
            reason: reason.to_string(),
            world: self.core.identity.world,
        });
    }

    fn send_connected_ack(&mut self) -> Result<(), SessionError> {
        let (msg_id, payload) = self.signon.acknowledgement()?;
        let m1 = encode_message(6, &self.settings.userinfo())?;
        let m2 = encode_message(msg_id, &payload)?;
        let (joined, _) = join_messages(&[m1, m2])?;
        let rf = reliable_frame(&joined, 0)?;
        self.port.send(&rf, 8).map_err(SessionError::Native)
    }

    pub fn advance_initialization(&mut self) -> Result<(), SessionError> {
        if self.signon.state > 3 {
            if let Some(ids) = self.world_sync.event_subscription_pending.take() {
                if let Some(ref srv) = self.core.server {
                    let mut words = [0u32; 16];
                    for eid in ids {
                        if !(0..512).contains(&eid) {
                            return Err(SessionError::EventSubscriptionId);
                        }
                        let uid = eid as usize;
                        words[uid / 32] |= 1u32 << (uid % 32);
                    }
                    let mut payload = Vec::new();
                    encode_pb_varint(1, (srv.player_slot as u32) as u64, &mut payload);
                    for w in words {
                        encode_pb_varint(2, w as u64, &mut payload);
                    }
                    let (encoded, _) = encode_message(206, &payload)?;
                    let rf = reliable_frame(&encoded, 0)?;
                    self.port.send(&rf, 8).map_err(SessionError::Native)?;
                }
            }
        }

        if self.signon.state == 3 && !self.world_sync.new_sent {
            if self.core.server.is_none() {
                return Err(SessionError::NewBeforeServerInfo);
            }
            let sc = self
                .signon
                .spawn_count
                .ok_or(SessionError::ServerInfoMissing)?;
            let acct = self.account_id.ok_or(SessionError::LocalAccountIdMissing)?;
            let info = client_info(sc, acct, 0);
            let (enc_info, _) = encode_message(20, &info)?;
            let rf1 = reliable_frame(&enc_info, 0)?;
            self.port.send(&rf1, 8).map_err(SessionError::Native)?;
            self.signon.finish_new()?;
            let (mid, payload) = self.signon.acknowledgement()?;
            let (enc_ack, _) = encode_message(mid, &payload)?;
            let rf2 = reliable_frame(&enc_ack, 0)?;
            self.port.send(&rf2, 8).map_err(SessionError::Native)?;
            self.world_sync.new_sent = true;
        } else if self.signon.state == 4 && !self.world_sync.prespawn_sent {
            if !self.core.ready() || self.core.class_count() == 0 {
                self.phase = DriverPhase::Blocked;
                self.reason = Some("prespawn-initialization-required".into());
                return Ok(());
            }
            let (mid, payload) = self.signon.acknowledgement()?;
            let (enc_ack, _) = encode_message(mid, &payload)?;
            let rf = reliable_frame(&enc_ack, 0)?;
            self.port.send(&rf, 8).map_err(SessionError::Native)?;
            self.world_sync.prespawn_sent = true;
        }

        if matches!(self.signon.state, 4..=6) && self.core.ready() {
            let ready = self
                .core
                .ready_world_groups()
                .map_err(SessionError::Protocol)?;
            for handle in ready {
                let mut pb = Vec::new();
                encode_pb_varint(1, handle as u64, &mut pb);
                let (encoded, _) = encode_message(13, &pb)?;
                let rf = reliable_frame(&encoded, 0)?;
                self.port.send(&rf, 8).map_err(SessionError::Native)?;
            }
        }

        if self.signon.state == 5 && !self.world_sync.spawn_sent {
            if !self.core.ready() || !self.world_sync.prespawn_sent {
                return Err(SessionError::SpawnBeforeParserInit);
            }
            if self.core.spawn_groups.len() != self.core.ready_spawn_groups.len() {
                return Ok(());
            }
            self.signon.finish_spawn()?;
            let (mid, payload) = self.signon.acknowledgement()?;
            let (enc_ack, _) = encode_message(mid, &payload)?;
            let rf = reliable_frame(&enc_ack, 0)?;
            self.port.send(&rf, 8).map_err(SessionError::Native)?;
            self.world_sync.spawn_sent = true;
        }

        self.acknowledge_full()
    }

    fn acknowledge_full(&mut self) -> Result<(), SessionError> {
        if self.signon.state == 6
            && !self.world_sync.full_sent
            && self.world_sync.full_snapshot_processed
        {
            if !self.world_sync.spawn_sent {
                return Err(SessionError::FullBeforeSpawnAck);
            }
            let (mid, payload) = self.signon.acknowledgement()?;
            let (enc_ack, _) = encode_message(mid, &payload)?;
            let rf = reliable_frame(&enc_ack, 0)?;
            self.port.send(&rf, 8).map_err(SessionError::Native)?;
            self.world_sync.full_sent = true;
            self.ever_full = true;
        }
        Ok(())
    }

    pub fn send_processed_tick(&mut self, now_ms: u64) -> Result<(), SessionError> {
        if !self.world_sync.full_sent && !self.world_sync.spawn_sent {
            return Ok(());
        }
        if self.world_sync.full_snapshot_processed && !self.world_sync.full_sent {
            if self.signon.state == 5 {
                self.signon.finish_full_snapshot()?;
            }
            self.acknowledge_full()?;
        }
        match self.world_sync.recovery {
            RecoveryState::NeedFullUpdate => {
                let mut pb = Vec::new();
                encode_pb_varint(1, 0xFFFF_FFFF, &mut pb);
                let (encoded, _) = encode_message(4, &pb)?;
                let rf = reliable_frame(&encoded, 0)?;
                self.port.send(&rf, 8).map_err(SessionError::Native)?;
                self.world_sync.ack_tick = Some(-1);
                self.world_sync.recovery = RecoveryState::WaitingFull;
                return Ok(());
            }
            RecoveryState::WaitingFull => return Ok(()),
            RecoveryState::Normal => {}
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
        let (encoded, _) = encode_message(4, &pb)?;
        self.send_channel_feedback(&encoded, now_ms)?;
        self.world_sync.ack_tick = Some(tick);
        self.world_sync.last_receipt_ms = now_ms;
        Ok(())
    }

    fn send_channel_feedback(&mut self, encoded: &[u8], now_ms: u64) -> Result<(), SessionError> {
        let pkt = self.feedback.frame(encoded)?;
        self.port.send(&pkt, 1).map_err(SessionError::Native)?;
        self.last_feedback_ms = now_ms;
        self.world_sync.last_receipt_ms = now_ms;
        Ok(())
    }
}
