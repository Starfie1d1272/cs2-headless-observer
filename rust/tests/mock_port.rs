use std::collections::VecDeque;
use std::io::Cursor;
use std::sync::atomic::AtomicBool;
use std::time::Instant;

use cs2_headless_observer::native::password::SecretBytes;
use cs2_headless_observer::native::{ObserverPort, ReceivedPacket};
use cs2_headless_observer::session::driver::{DriverEmit, DriverPhase, ObserverDriver};
use cs2_headless_observer::session::reporting::{unix_ms_now, PublicJsonlSink};
use cs2_headless_observer::session::supervisor::{
    decide_recovery, read_managed_config, run_single_attempt, AttemptCategory, AttemptOutcome,
    RecoveryAction,
};
use cs2_headless_observer::wire::bits::{encode_pb_bytes, encode_pb_varint, encode_varint};
use cs2_headless_observer::wire::channel::{encode_message, join_messages, reliable_frame};

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

#[test]
fn test_auth2_handshake_and_1038_drain() {
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

    // Step 1: transport -> challenge request
    driver.step(10).unwrap();
    assert_eq!(driver.phase, DriverPhase::Challenge);
    assert_eq!(driver.port.sent.len(), 1);
    assert!(driver.port.sent[0].0.starts_with(b"\xff\xff\xff\xffq"));

    // Step 2: server sends Auth2 challenge
    let ch = make_challenge(2, 0x11223344, 90071996842377217, b"connect0x00000000");
    driver.port.push_packet(ch, false);
    driver.step(20).unwrap();
    assert!(driver.port.auth2_accepted);
    assert_eq!(driver.phase, DriverPhase::Connection);

    // Step 3: server sends S2C_CONNECTION -> enters channel
    driver.port.push_packet(make_connection_inner(), false);
    driver.step(30).unwrap();
    assert_eq!(driver.phase, DriverPhase::Channel);

    // Step 4: simulate full_sent and 1038 clean drain
    driver.world_sync.full_sent = true;
    driver.ever_full = true;
    driver.port.state = 6;
    driver.port.remote_end_reason = 1038;
    driver.port.failure = 7;
    driver.step(40).unwrap();
    assert!(driver.done());
    assert!(driver.drain_completed);
    assert_eq!(driver.reason.as_deref(), Some("source-hltv-stop"));
    assert!(matches!(
        driver.emitted.last(),
        Some(DriverEmit::Discontinuity { scope: "connection", reason, .. }) if reason == "source-hltv-stop"
    ));
}

#[test]
fn test_auth3_handshake_ticket_flow() {
    let port = MockPort::new();
    let mut driver = ObserverDriver::new(
        port,
        14191,
        SecretBytes::new(Vec::new()),
        "ahead:test".into(),
        1,
        0,
    )
    .unwrap();

    driver.step(10).unwrap();
    let ch = make_challenge(3, 0xAABBCCDD, 90071996842377217, b"connect0x00000000");
    driver.port.push_packet(ch, false);
    driver.step(20).unwrap();
    assert!(driver.port.ticket_requested);
    assert_eq!(driver.phase, DriverPhase::Ticket);

    // Native ticket callback completes -> state = 5
    driver.port.state = 5;
    driver.step(30).unwrap();
    assert_eq!(driver.phase, DriverPhase::Connection);

    driver.port.push_packet(make_connection_inner(), false);
    driver.step(40).unwrap();
    assert_eq!(driver.phase, DriverPhase::Channel);

    // Verify ServerInfo + SignonState(3) advances to NEW
    let mut srv = Vec::new();
    encode_pb_varint(1, 14191, &mut srv);
    encode_pb_varint(2, 7, &mut srv);
    encode_pb_varint(11, 1, &mut srv);
    srv.push(0x6d);
    srv.extend_from_slice(&(1.0f32 / 64.0f32).to_le_bytes());
    encode_pb_bytes(15, b"de_test", &mut srv);
    let mut sig3 = Vec::new();
    encode_pb_varint(1, 3, &mut sig3);
    encode_pb_varint(2, 7, &mut sig3);
    let m1 = encode_message(40, &srv).unwrap();
    let m2 = encode_message(7, &sig3).unwrap();
    let (joined, _) = join_messages(&[m1, m2]).unwrap();
    driver
        .port
        .push_packet(reliable_frame(&joined, 100).unwrap(), true);
    driver.step(50).unwrap();
    assert!(driver.world_sync.new_sent);
}

#[test]
fn test_stdin_config_and_eof_stop() {
    let input = b"{\"endpoint\":\"127.0.0.1:27020\",\"password\":\"secret\"}\n";
    let mut cur = Cursor::new(&input[..]);
    let mut cfg = read_managed_config(&mut cur).unwrap();
    assert_eq!(cfg.endpoint, "127.0.0.1:27020");
    assert_eq!(cfg.password.as_slice(), b"secret");
    cfg.password.zeroize();
    assert!(cfg.password.is_empty());

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
    let mut sink = PublicJsonlSink::new(Vec::<u8>::new());
    let mut last_cursor = None;
    let mut last_health = None;
    let outcome = run_single_attempt(
        &mut driver,
        &mut sink,
        &stop_flag,
        None,
        Instant::now(),
        &mut last_cursor,
        &mut last_health,
        0,
        0,
        0,
        &None,
        None,
    )
    .unwrap();
    assert_eq!(outcome.reason, "owner-stopped");
    assert_eq!(outcome.category, AttemptCategory::CleanSourceStop);
    let _ = unix_ms_now();
}

#[test]
fn test_follow_source_and_retry_decisions() {
    let clean = AttemptOutcome {
        category: AttemptCategory::CleanSourceStop,
        reason: "source-hltv-stop".into(),
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

    let unavail = AttemptOutcome {
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
