use std::collections::VecDeque;
use std::io::Cursor;
use std::sync::atomic::AtomicBool;
use std::time::Instant;

use cs2_headless_observer::native::password::SecretBytes;
use cs2_headless_observer::native::{ObserverPort, ReceivedPacket};
use cs2_headless_observer::session::driver::{DriverEmit, DriverPhase, ObserverDriver};
use cs2_headless_observer::session::reporting::{HealthV2, ReportV2, SyncJsonlSink};
use cs2_headless_observer::session::supervisor::{
    decide_recovery, read_managed_config, run_single_attempt, AttemptCategory, AttemptExit,
    RecoveryAction,
};
use cs2_headless_observer::wire::bits::{encode_pb_bytes, encode_pb_varint, encode_varint};
use cs2_headless_observer::wire::channel::{
    decode_frame, decode_messages, encode_message, join_messages, reliable_frame,
};

struct MockPort {
    pub state: i32,
    pub failure: i32,
    pub remote_end_reason: i32,
    pub remote_id: u64,
    pub local_id: u64,
    pub auth2_accepted: bool,
    pub ticket_requested: bool,
    pub auth_bytes: Vec<u8>,
    pub sent: Vec<(Vec<u8>, i32)>,
    pub inbound: VecDeque<ReceivedPacket>,
}

impl MockPort {
    fn new() -> Self {
        let mut auth = Vec::new();
        auth.extend_from_slice(&76561198000000123u64.to_le_bytes());
        auth.extend_from_slice(b"MOCK_TICKET_BYTES");
        Self {
            state: 3,
            failure: 7,
            remote_end_reason: 0,
            remote_id: 90071996842377217,
            local_id: 76561198000000123,
            auth2_accepted: false,
            ticket_requested: false,
            auth_bytes: auth,
            sent: Vec::new(),
            inbound: VecDeque::new(),
        }
    }

    fn push_packet(&mut self, data: Vec<u8>, reliable: bool) {
        self.inbound.push_back(ReceivedPacket {
            data,
            reliable,
            dequeue_ns: 1000,
            sdk_queue_age_us: Some(500),
        });
    }
}

impl ObserverPort for MockPort {
    fn state(&self) -> i32 {
        self.state
    }
    fn failure(&self) -> i32 {
        self.failure
    }
    fn remote_end_reason(&self) -> i32 {
        self.remote_end_reason
    }
    fn pump(&mut self, _now_ms: u64) {}
    fn remote_id(&self) -> u64 {
        self.remote_id
    }
    fn local_id(&self) -> u64 {
        self.local_id
    }
    fn accept_server_auth2(&mut self) -> Result<(), String> {
        self.auth2_accepted = true;
        self.state = 7;
        Ok(())
    }
    fn request_ticket(&mut self) -> Result<(), String> {
        self.ticket_requested = true;
        self.state = 4;
        Ok(())
    }
    fn with_auth<F, R>(&self, f: F) -> Result<R, String>
    where
        F: FnOnce(&[u8]) -> Result<R, String>,
    {
        f(&self.auth_bytes)
    }
    fn send(&mut self, data: &[u8], flags: i32) -> Result<(), String> {
        self.sent.push((data.to_vec(), flags));
        Ok(())
    }
    fn receive(&mut self) -> Result<Option<ReceivedPacket>, String> {
        Ok(self.inbound.pop_front())
    }
    fn close(&mut self) {
        self.state = 6;
    }
}

fn make_challenge(auth_proto: u32, challenge_num: u32, peer: u64, context: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(b"\xff\xff\xff\xffA");
    out.extend_from_slice(&challenge_num.to_le_bytes());
    out.extend_from_slice(&auth_proto.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&peer.to_le_bytes());
    out.push(1);
    out.extend_from_slice(context);
    out.push(0);
    out
}

fn make_connection_inner() -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(b"\xff\xff\xff\xffB");
    encode_varint(0, &mut out);
    while out.len() < 16 {
        out.push(b'0');
    }
    out
}

fn pack_bits(bits: &[u8]) -> Vec<u8> {
    let mut out = vec![0u8; bits.len().div_ceil(8)];
    for (i, &b) in bits.iter().enumerate() {
        if b != 0 {
            out[i / 8] |= 1 << (i & 7);
        }
    }
    out
}

fn push_bits(vec: &mut Vec<u8>, val: u64, count: u8) {
    for i in 0..count {
        vec.push(((val >> i) & 1) as u8);
    }
}

fn build_world_init_messages(steam: u64) -> (Vec<(u32, Vec<u8>)>, Vec<u8>) {
    // 40: ServerInfo
    let mut srv = Vec::new();
    encode_pb_varint(1, 14191, &mut srv);
    encode_pb_varint(2, 7, &mut srv);
    encode_pb_varint(11, 1, &mut srv);
    srv.push(0x6d);
    srv.extend_from_slice(&(1.0f32 / 64.0f32).to_le_bytes());
    encode_pb_bytes(15, b"de_test", &mut srv);

    // 41: FlattenedSerializer
    let mut ser_msg = Vec::new();
    let mut s = Vec::new();
    encode_pb_varint(1, 0, &mut s);
    encode_pb_varint(2, 0, &mut s);
    encode_pb_varint(3, 0, &mut s);
    encode_pb_bytes(1, &s, &mut ser_msg);
    for sym in ["CCSPlayerController", "m_steamID", "uint64", "fixed64"] {
        encode_pb_bytes(2, sym.as_bytes(), &mut ser_msg);
    }
    let mut fld = Vec::new();
    encode_pb_varint(1, 2, &mut fld);
    encode_pb_varint(2, 1, &mut fld);
    encode_pb_varint(10, 3, &mut fld);
    encode_pb_bytes(3, &fld, &mut ser_msg);

    // 42: ClassInfo
    let mut cls = Vec::new();
    let mut c0 = Vec::new();
    encode_pb_varint(1, 0, &mut c0);
    encode_pb_bytes(3, b"CCSPlayerController", &mut c0);
    encode_pb_bytes(2, &c0, &mut cls);

    // field_wire for m_steamID
    let mut fw = vec![0u8, 1, 0];
    push_bits(&mut fw, steam, 64);
    let fw_bytes = pack_bits(&fw);

    // 44: instancebaseline
    let mut st_bits = vec![1u8, 1, 0];
    push_bits(&mut st_bits, 48, 8);
    push_bits(&mut st_bits, 0, 8);
    st_bits.push(1);
    push_bits(&mut st_bits, fw_bytes.len() as u64, 17);
    for &b in &fw_bytes {
        push_bits(&mut st_bits, b as u64, 8);
    }
    let mut st_ib = Vec::new();
    encode_pb_bytes(1, b"instancebaseline", &mut st_ib);
    encode_pb_varint(2, 1, &mut st_ib);
    encode_pb_bytes(7, &pack_bits(&st_bits), &mut st_ib);

    // 44: userinfo
    let mut uinfo_val = vec![0x11u8];
    uinfo_val.extend_from_slice(&steam.to_le_bytes());
    encode_pb_varint(3, 42, &mut uinfo_val);
    let mut ui_bits = vec![1u8, 1, 0];
    push_bits(&mut ui_bits, 48, 8);
    push_bits(&mut ui_bits, 0, 8);
    ui_bits.push(1);
    push_bits(&mut ui_bits, uinfo_val.len() as u64, 17);
    for &b in &uinfo_val {
        push_bits(&mut ui_bits, b as u64, 8);
    }
    let mut st_ui = Vec::new();
    encode_pb_bytes(1, b"userinfo", &mut st_ui);
    encode_pb_varint(2, 1, &mut st_ui);
    encode_pb_bytes(7, &pack_bits(&ui_bits), &mut st_ui);

    (
        vec![
            (40, srv),
            (41, ser_msg),
            (42, cls),
            (44, st_ib),
            (44, st_ui),
        ],
        fw,
    )
}

fn make_full_snapshot(tick: u32, fw: &[u8]) -> Vec<u8> {
    let mut pe_bits = Vec::new();
    push_bits(&mut pe_bits, 1, 6);
    push_bits(&mut pe_bits, 2, 2);
    pe_bits.push(0);
    push_bits(&mut pe_bits, 1, 17);
    push_bits(&mut pe_bits, 0, 8);
    pe_bits.extend_from_slice(fw);
    let mut pe = Vec::new();
    encode_pb_varint(2, 1, &mut pe);
    encode_pb_varint(10, 0, &mut pe);
    encode_pb_varint(12, tick as u64, &mut pe);
    encode_pb_bytes(7, &pack_bits(&pe_bits), &mut pe);
    encode_pb_bytes(19, &[], &mut pe);
    pe
}

fn make_signon(state: u64, spawn_count: u64) -> Vec<u8> {
    let mut sig = Vec::new();
    encode_pb_varint(1, state, &mut sig);
    encode_pb_varint(2, spawn_count, &mut sig);
    sig
}

fn pack_reliable_msgs(msgs: &[(u32, Vec<u8>)], tick_hint: u32) -> Vec<u8> {
    let encoded: Vec<(Vec<u8>, usize)> = msgs
        .iter()
        .map(|(id, body)| encode_message(*id, body).unwrap())
        .collect();
    let (joined, _) = join_messages(&encoded).unwrap();
    reliable_frame(&joined, tick_hint).unwrap()
}

#[test]
fn test_full_end_to_end_lifecycle_world_reset_recovery_and_1038_drain() {
    let steam: u64 = 76561198000000123;
    let port = MockPort::new();
    let mut driver = ObserverDriver::new(
        port,
        14191,
        SecretBytes::new(b"pw123".to_vec()),
        "ahead:e2e".into(),
        1,
        0,
    )
    .unwrap();

    // 1. Auth3 handshake -> ticket -> connect -> channel
    driver.step(10).unwrap();
    let ch = make_challenge(3, 0xAABBCCDD, 90071996842377217, b"connect0x00000000");
    driver.port.push_packet(ch, false);
    driver.step(20).unwrap();
    assert!(driver.port.ticket_requested);
    driver.port.state = 5;
    driver.step(30).unwrap();
    driver.port.push_packet(make_connection_inner(), false);
    driver.step(40).unwrap();
    assert_eq!(driver.phase, DriverPhase::Channel);

    // 2. Signon 3 (NEW) -> 4 (PRESPAWN) -> 5 (SPAWN) -> FULL Snapshot (natural full_sent!)
    let (init_msgs, fw) = build_world_init_messages(steam);
    let mut batch1 = init_msgs.clone();
    batch1.push((7, make_signon(3, 7)));
    driver
        .port
        .push_packet(pack_reliable_msgs(&batch1, 10), true);
    driver.step(50).unwrap();
    assert!(driver.world_sync.new_sent);

    driver
        .port
        .push_packet(pack_reliable_msgs(&[(7, make_signon(4, 7))], 20), true);
    driver.step(60).unwrap();
    assert!(driver.world_sync.prespawn_sent);

    driver
        .port
        .push_packet(pack_reliable_msgs(&[(7, make_signon(5, 7))], 30), true);
    driver.step(70).unwrap();
    assert!(driver.world_sync.spawn_sent);
    assert!(!driver.world_sync.full_sent);

    // Send Tick(100) + FULL PacketEntities(100)
    let mut tick_pb = Vec::new();
    encode_pb_varint(1, 100, &mut tick_pb);
    driver.port.push_packet(
        pack_reliable_msgs(&[(4, tick_pb), (55, make_full_snapshot(100, &fw))], 100),
        true,
    );
    driver.step(200).unwrap();
    // full_sent becomes true naturally without manual mutation!
    assert!(driver.world_sync.full_sent);
    assert!(driver.ever_full);
    assert_eq!(driver.core.entities.get(1).unwrap().id, 1);

    // Verify Tick ACK was sent in unreliable feedback frame
    let has_ack_100 = driver.port.sent.iter().any(|(pkt, flags)| {
        if *flags != 1 {
            return false;
        }
        if let Ok(frame) = decode_frame(pkt, false) {
            if let Ok((msgs, _)) = decode_messages(&frame.body, None, None) {
                return msgs.iter().any(|m| m.message_id == 4);
            }
        }
        false
    });
    assert!(has_ack_100, "expected tick ACK in feedback frame");

    // 3. Emit weapon_fire event
    let mut desc = Vec::new();
    encode_pb_varint(1, 17, &mut desc);
    encode_pb_bytes(2, b"weapon_fire", &mut desc);
    for (t, n) in [(9u64, "userid"), (1, "weapon"), (6, "silenced")] {
        let mut k = Vec::new();
        encode_pb_varint(1, t, &mut k);
        encode_pb_bytes(2, n.as_bytes(), &mut k);
        encode_pb_bytes(3, &k, &mut desc);
    }
    let mut ev_list = Vec::new();
    encode_pb_bytes(1, &desc, &mut ev_list);
    let mut ev = Vec::new();
    encode_pb_varint(2, 17, &mut ev);
    let mut k0 = Vec::new();
    encode_pb_varint(1, 9, &mut k0);
    encode_pb_varint(5, 0, &mut k0);
    encode_pb_bytes(3, &k0, &mut ev);
    let mut k1 = Vec::new();
    encode_pb_varint(1, 1, &mut k1);
    encode_pb_bytes(2, b"ak47", &mut k1);
    encode_pb_bytes(3, &k1, &mut ev);
    let mut k2 = Vec::new();
    encode_pb_varint(1, 6, &mut k2);
    encode_pb_varint(7, 0, &mut k2);
    encode_pb_bytes(3, &k2, &mut ev);

    driver
        .port
        .push_packet(pack_reliable_msgs(&[(205, ev_list), (207, ev)], 101), true);
    driver.step(250).unwrap();
    assert!(driver.emitted.iter().any(
        |e| matches!(e, DriverEmit::RawEvent(r) if r.name == "weapon_fire" && r.identity_resolved)
    ));

    // 4. ID 51 World Reset: verify world increments STRICTLY ONCE (1 -> 2)
    driver
        .port
        .push_packet(pack_reliable_msgs(&[(51, Vec::new())], 102), true);
    driver.step(260).unwrap();
    assert_eq!(driver.core.identity.world, 2);
    assert_eq!(driver.core.known_creation_sequence, 0);
    assert!(matches!(
        driver.emitted.last(),
        Some(DriverEmit::Discontinuity {
            scope: "world",
            world: 2,
            ..
        })
    ));

    // Re-init world 2 -> Signon 3,4,5 -> FULL(200)
    let mut w2_init = init_msgs;
    w2_init.push((7, make_signon(3, 7)));
    driver
        .port
        .push_packet(pack_reliable_msgs(&w2_init, 200), true);
    driver.step(270).unwrap();
    driver
        .port
        .push_packet(pack_reliable_msgs(&[(7, make_signon(4, 7))], 200), true);
    driver.step(280).unwrap();
    driver
        .port
        .push_packet(pack_reliable_msgs(&[(7, make_signon(5, 7))], 200), true);
    driver.step(290).unwrap();
    let mut tick200 = Vec::new();
    encode_pb_varint(1, 200, &mut tick200);
    driver.port.push_packet(
        pack_reliable_msgs(&[(4, tick200), (55, make_full_snapshot(200, &fw))], 200),
        true,
    );
    driver.step(300).unwrap();
    assert!(driver.world_sync.full_sent);
    assert!(driver.core.entities.get(1).is_some());

    // 5. Malformed PacketEntities triggers recover(): entities cleared & recovery requested
    let mut bad_pe = Vec::new();
    encode_pb_varint(2, 5, &mut bad_pe); // updated_entries=5, missing server_tick!
    driver
        .port
        .push_packet(pack_reliable_msgs(&[(55, bad_pe)], 201), true);
    driver.step(310).unwrap();
    assert!(driver.world_sync.recovery_pending);
    assert!(driver.world_sync.full_update_outstanding);
    assert!(driver.core.entities.get(1).is_none());

    // Recover from a new FULL snapshot at tick 205
    let mut tick205 = Vec::new();
    encode_pb_varint(1, 205, &mut tick205);
    driver.port.push_packet(
        pack_reliable_msgs(&[(4, tick205), (55, make_full_snapshot(205, &fw))], 205),
        true,
    );
    driver.step(320).unwrap();
    assert!(!driver.world_sync.recovery_pending);
    assert!(driver.core.entities.get(1).is_some());

    // 6. 1038 clean drain without manual full_sent hack!
    driver.port.state = 6;
    driver.port.remote_end_reason = 1038;
    driver.port.failure = 7;
    driver.step(330).unwrap();
    assert!(driver.done());
    assert!(driver.drain_completed);
    assert_eq!(driver.reason.as_deref(), Some("source-hltv-stop"));
}

#[test]
fn test_auth2_handshake() {
    let port = MockPort::new();
    let mut driver = ObserverDriver::new(
        port,
        14191,
        SecretBytes::new(b"pw123".to_vec()),
        "ahead:test".into(),
        1,
        0,
    )
    .unwrap();

    driver.step(10).unwrap();
    let ch = make_challenge(2, 0x11223344, 90071996842377217, b"connect0x00000000");
    driver.port.push_packet(ch, false);
    driver.step(20).unwrap();
    assert!(driver.port.auth2_accepted);
    assert_eq!(driver.phase, DriverPhase::Connection);

    driver.port.push_packet(make_connection_inner(), false);
    driver.step(30).unwrap();
    assert_eq!(driver.phase, DriverPhase::Channel);
}

#[test]
fn test_stdin_eof_stop_under_follow_source_exits_incomplete_without_source_ends() {
    let input = b"{\"endpoint\":\"127.0.0.1:27020\",\"password\":\"secret\"}\n";
    let mut cur = Cursor::new(&input[..]);
    let mut cfg = read_managed_config(&mut cur).unwrap();
    assert_eq!(cfg.endpoint, "127.0.0.1:27020");
    cfg.password.zeroize();

    let port = MockPort::new();
    let mut driver = ObserverDriver::new(
        port,
        14191,
        SecretBytes::default(),
        "ahead:eof".into(),
        1,
        0,
    )
    .unwrap();
    let stop_flag = AtomicBool::new(true);
    let mut sink = SyncJsonlSink::new(Vec::<u8>::new());
    let mut last_cursor = None;
    let mut last_health = None;
    let exit = run_single_attempt(
        &mut driver,
        &mut sink,
        None,
        &stop_flag,
        None,
        &Instant::now(),
        &mut last_cursor,
        &mut last_health,
        0,
        0,
        0,
        &None,
        None,
    )
    .unwrap();
    assert!(matches!(exit, AttemptExit::OwnerStopped { .. }));
    assert_eq!(
        decide_recovery(&exit, false, true, 0),
        RecoveryAction::Incomplete("owner-stopped".into())
    );
}

#[test]
fn test_mizar_health_and_report_v2_contract() {
    let h = HealthV2 {
        r#type: "cs2-observer-health/2",
        source: "ahead:test".into(),
        channel: 1,
        world: 1,
        state: "connected",
        reason: "connected".into(),
        upstream_freshness: "unknown",
        ready: true,
        reconnects: 0,
        source_ends: 0,
        follow_attempts: 0,
        retry_in_ms: None,
        wait_reason: None,
        sdk_queue_age_us: Some(500),
        sdk_max_age_us: Some(500),
        context_tick: Some(100),
        network_tick: Some(100),
        committed_tick: Some(100),
        committed_ticks_per_second: Some(64.0),
        last_delivered_cursor: None,
        last_attempt_end: None,
        last_fault: None,
    };
    let h_json = serde_json::to_value(&h).unwrap();
    assert_eq!(h_json["state"], "connected");

    let r = ReportV2 {
        schema: "cs2-observer-report/2",
        outcome: "closed",
        reason: "source-hltv-stop".into(),
        cleanup_completed: true,
        report_written: true,
        source: "ahead:test".into(),
        channel: 1,
        world: 1,
        last_output_sequence: 10,
        reconnects: 0,
        source_ends: 1,
        follow_attempts: 0,
        last_attempt_end: None,
        faults: Vec::new(),
        health: Some(h),
    };
    let r_json = serde_json::to_value(&r).unwrap();
    assert_eq!(r_json["schema"], "cs2-observer-report/2");
    assert_eq!(r_json["outcome"], "closed");
    assert_eq!(r_json["cleanupCompleted"], true);
    assert_eq!(r_json["reportWritten"], true);
    assert!(r_json.get("ok").is_none());
}

#[test]
fn test_follow_source_and_retry_decisions() {
    let clean = AttemptExit::CleanSourceStop {
        phase: "draining".into(),
        native_failure: Some(7),
        remote_end_reason: Some(1038),
        reached_full: true,
        ready_duration_ms: 5000,
    };
    assert_eq!(
        decide_recovery(&clean, false, false, 0),
        RecoveryAction::Close
    );
    assert_eq!(
        decide_recovery(&clean, false, true, 0),
        RecoveryAction::Follow
    );

    let unavail = AttemptExit::Fault {
        category: AttemptCategory::SourceUnavailable,
        reason: "phase-timeout".into(),
        phase: "challenge".into(),
        native_failure: Some(7),
        remote_end_reason: Some(0),
        reached_full: false,
        ready_duration_ms: 0,
    };
    assert_eq!(
        decide_recovery(&unavail, true, true, 0),
        RecoveryAction::Follow
    );
    assert_eq!(
        decide_recovery(&unavail, false, false, 0),
        RecoveryAction::Retry
    );
    assert_eq!(
        decide_recovery(&unavail, false, false, 5),
        RecoveryAction::Fail("reconnect-budget-exhausted".into())
    );
}
