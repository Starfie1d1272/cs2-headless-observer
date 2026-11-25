use std::io::Read;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Deserialize;

use super::driver::{DriverEmit, DriverPhase, ObserverDriver, RecoveryState};
use super::reporting::{
    write_report_file, AsyncStderrLogger, AsyncStdoutSink, AttemptEndSummary, DiscontinuityRecord,
    HealthV2, LastDeliveredCursor, RecordSink, ReportV2, SessionStartRecord,
};
use super::SessionError;
use crate::native::abi::{NativePort, NativeStartError};
use crate::native::password::SecretBytes;
use crate::native::ObserverPort;

const RETRY_LIMIT: u32 = 5;
const STABLE_MS: u64 = 30_000;
const FOLLOW_INITIAL_MS: u64 = 5_000;
const FOLLOW_MAX_MS: u64 = 45_000;
const FAULT_INITIAL_MS: u64 = 500;
const HEALTH_INTERVAL_MS: u64 = 1_000;

#[derive(Debug, Clone)]
pub struct ManagedArgs {
    pub native: PathBuf,
    pub steam_api: Option<PathBuf>,
    pub source_role: String,
    pub source_id: String,
    pub host_version: u32,
    pub output: PathBuf,
    pub follow_source: bool,
    pub seconds: Option<f64>,
}

#[derive(Deserialize)]
struct StdinConfig {
    endpoint: String,
    password: String,
}

pub struct ParsedConfig {
    pub endpoint: String,
    pub password: SecretBytes,
}

pub fn read_managed_config<R: Read>(reader: &mut R) -> Result<ParsedConfig, String> {
    let mut buf = Vec::with_capacity(256);
    let mut byte = [0u8; 1];
    while buf.len() <= 4096 {
        let n = reader.read(&mut byte).map_err(|_| "stdin-read-failed")?;
        if n == 0 {
            break;
        }
        buf.push(byte[0]);
        if byte[0] == b'\n' {
            break;
        }
    }
    if buf.is_empty() || buf.len() > 4096 || !buf.ends_with(b"\n") {
        return Err("invalid-stdin-configuration-line".into());
    }
    let cfg: StdinConfig =
        serde_json::from_slice(&buf).map_err(|_| "invalid-stdin-configuration-json")?;
    for b in &mut buf {
        unsafe { std::ptr::write_volatile(b, 0) };
    }
    validate_endpoint(&cfg.endpoint)?;
    let pw_bytes = cfg.password.into_bytes();
    if pw_bytes.len() > 95 || pw_bytes.contains(&0) || !pw_bytes.is_ascii() {
        return Err("invalid-password-boundary".into());
    }
    Ok(ParsedConfig {
        endpoint: cfg.endpoint,
        password: SecretBytes::new(pw_bytes),
    })
}

pub fn validate_endpoint(endpoint: &str) -> Result<(), String> {
    let addr: SocketAddr = endpoint
        .parse()
        .map_err(|_| "invalid-endpoint-address".to_string())?;
    if addr.port() == 0 {
        return Err("invalid-endpoint-port".into());
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttemptCategory {
    CleanSourceStop,
    SourceUnavailable,
    TransientFault,
    TerminalFault,
}

impl AttemptCategory {
    pub fn as_str(self) -> &'static str {
        match self {
            AttemptCategory::CleanSourceStop => "clean-source-stop",
            AttemptCategory::SourceUnavailable => "source-unavailable",
            AttemptCategory::TransientFault => "transient-fault",
            AttemptCategory::TerminalFault => "terminal-fault",
        }
    }
}

#[derive(Debug, Clone)]
pub enum AttemptExit {
    OwnerStopped {
        phase: String,
        native_failure: Option<i32>,
        remote_end_reason: Option<i32>,
    },
    DurationLimit {
        phase: String,
        native_failure: Option<i32>,
        remote_end_reason: Option<i32>,
    },
    CleanSourceStop {
        phase: String,
        native_failure: Option<i32>,
        remote_end_reason: Option<i32>,
        reached_full: bool,
        ready_duration_ms: u64,
    },
    Fault {
        category: AttemptCategory,
        reason: String,
        phase: String,
        native_failure: Option<i32>,
        remote_end_reason: Option<i32>,
        reached_full: bool,
        ready_duration_ms: u64,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RecoveryAction {
    Close,
    Follow,
    Retry,
    Incomplete(String),
    Fail(String),
}

pub fn decide_recovery(
    exit: &AttemptExit,
    following: bool,
    follow_source: bool,
    retry_streak: u32,
) -> RecoveryAction {
    match exit {
        AttemptExit::OwnerStopped { .. } => RecoveryAction::Incomplete("owner-stopped".into()),
        AttemptExit::DurationLimit { .. } => {
            RecoveryAction::Incomplete("duration-limit-incomplete".into())
        }
        AttemptExit::CleanSourceStop { .. } => {
            if follow_source {
                RecoveryAction::Follow
            } else {
                RecoveryAction::Close
            }
        }
        AttemptExit::Fault {
            category,
            reason,
            native_failure,
            remote_end_reason,
            ..
        } => {
            if following && *category == AttemptCategory::SourceUnavailable {
                return RecoveryAction::Follow;
            }
            if following
                && *native_failure == Some(7)
                && *category == AttemptCategory::TransientFault
                && !is_timeout_end_reason(*remote_end_reason)
            {
                return RecoveryAction::Fail(reason.clone());
            }
            if matches!(
                category,
                AttemptCategory::SourceUnavailable | AttemptCategory::TransientFault
            ) {
                if retry_streak >= RETRY_LIMIT {
                    return RecoveryAction::Fail("reconnect-budget-exhausted".into());
                }
                return RecoveryAction::Retry;
            }
            RecoveryAction::Fail(reason.clone())
        }
    }
}

fn is_timeout_end_reason(code: Option<i32>) -> bool {
    matches!(code, Some(3001..=3005 | 4001..=4005 | 5001..=5005))
}

fn jittered_ms(base_ms: u64, seed: u64) -> u64 {
    let mixed = seed
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    let frac = ((mixed >> 32) % 401) as i64 - 200;
    let adjusted = (base_ms as i64) + ((base_ms as i64) * frac) / 1000;
    adjusted.max(50) as u64
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManagedError {
    pub reason: String,
    pub report_written: bool,
}

impl std::fmt::Display for ManagedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.reason)
    }
}

impl std::error::Error for ManagedError {}

pub fn classify_session_error(
    err: &SessionError,
    phase: DriverPhase,
    native_failure: i32,
    remote_end_reason: i32,
) -> AttemptCategory {
    match err {
        SessionError::NativeSessionClosed => {
            if matches!(phase, DriverPhase::Transport | DriverPhase::Challenge)
                && is_timeout_end_reason(Some(remote_end_reason))
            {
                AttemptCategory::SourceUnavailable
            } else {
                AttemptCategory::TransientFault
            }
        }
        SessionError::InitializationTimeout
        | SessionError::SourceDrainTimeout
        | SessionError::SourceDrainNativeFailed => AttemptCategory::TransientFault,
        SessionError::PhaseTimeout => {
            if matches!(phase, DriverPhase::Transport | DriverPhase::Challenge) {
                AttemptCategory::SourceUnavailable
            } else {
                AttemptCategory::TransientFault
            }
        }
        SessionError::Native(msg)
            if native_failure == 7
                || msg == "native-receive-failed"
                || msg == "native-send-failed" =>
        {
            AttemptCategory::TransientFault
        }
        _ => AttemptCategory::TerminalFault,
    }
}

pub fn spawn_stop_watcher<R: Read + Send + 'static>(
    mut reader: R,
    stop_flag: Arc<AtomicBool>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut buf = [0u8; 1];
        let _ = reader.read(&mut buf);
        stop_flag.store(true, Ordering::SeqCst);
    })
}

pub fn run_managed(args: ManagedArgs) -> Result<(), ManagedError> {
    if args.output.exists() {
        return Err(ManagedError {
            reason: "output-directory-unavailable".into(),
            report_written: false,
        });
    }
    std::fs::create_dir_all(&args.output).map_err(|_| ManagedError {
        reason: "output-directory-unavailable".into(),
        report_written: false,
    })?;

    let mut stdin_lock = std::io::stdin().lock();
    let mut cfg = read_managed_config(&mut stdin_lock).map_err(|_| ManagedError {
        reason: "configuration-boundary".into(),
        report_written: false,
    })?;
    drop(stdin_lock);

    let stop_flag = Arc::new(AtomicBool::new(false));
    let _stop_watcher = spawn_stop_watcher(std::io::stdin(), stop_flag.clone());

    let source = format!("{}:{}", args.source_role, args.source_id);
    let epoch = Instant::now();
    let deadline = args
        .seconds
        .map(|s| epoch + Duration::from_secs_f64(s.max(0.0)));

    let mut sink = AsyncStdoutSink::spawn();
    let mut stderr_log = AsyncStderrLogger::spawn();
    let mut channel: u64 = 0;
    let mut reconnects: u64 = 0;
    let mut source_ends: u64 = 0;
    let mut follow_attempts: u64 = 0;
    let mut retry_streak: u32 = 0;
    let mut following = false;
    let mut follow_delay_ms = FOLLOW_INITIAL_MS;
    let mut last_attempt_end: Option<AttemptEndSummary> = None;
    let mut faults: Vec<AttemptEndSummary> = Vec::new();
    let mut last_health: Option<HealthV2> = None;
    let mut last_cursor: Option<LastDeliveredCursor> = None;
    let mut native_boot_code: Option<i32> = None;
    let mut steam_init_result: Option<i32> = None;

    let (outcome, reason) = loop {
        if stop_flag.load(Ordering::SeqCst) {
            break ("incomplete", "owner-stopped".to_string());
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                break ("incomplete", "duration-limit-incomplete".to_string());
            }
        }

        channel += 1;
        let start_seq = sink.next_sequence();
        let start_rec = SessionStartRecord {
            kind: "session-start",
            protocol: 2,
            source: source.clone(),
            channel,
            world: 1,
            sequence: start_seq,
        };
        if let Err(e) = sink.emit_with_seq(start_seq, &start_rec) {
            break ("failed", e.to_string());
        }

        let now_ms = epoch.elapsed().as_millis() as u64;
        let port = match NativePort::open(
            &args.native,
            args.steam_api.as_deref(),
            &cfg.endpoint,
            now_ms,
            epoch,
        ) {
            Ok(p) => p,
            Err(e) => {
                let start_err = e.downcast_ref::<NativeStartError>();
                let is_start_err = start_err.is_some();
                let reason = if let Some(se) = start_err {
                    native_boot_code = Some(se.boot_code);
                    steam_init_result = Some(se.init_result);
                    "native-start-failed".to_string()
                } else {
                    e.to_string()
                };
                let cat = if is_start_err {
                    AttemptCategory::TerminalFault
                } else {
                    AttemptCategory::TransientFault
                };
                let summary = AttemptEndSummary {
                    channel,
                    category: cat.as_str().into(),
                    reason: reason.clone(),
                    phase: "transport".into(),
                    native_failure: None,
                    remote_end_reason: None,
                    last_delivered_sequence: sink.current_sequence(),
                };
                last_attempt_end = Some(summary.clone());
                faults.push(summary);
                if faults.len() > 8 {
                    faults.remove(0);
                }
                break ("failed", reason);
            }
        };

        let mut driver = match ObserverDriver::new(
            port,
            args.host_version,
            cfg.password.clone(),
            source.clone(),
            channel,
            now_ms,
        ) {
            Ok(d) => d,
            Err(e) => break ("failed", e.to_string()),
        };

        let exit = run_single_attempt(
            &mut driver,
            &mut sink,
            Some(&stderr_log),
            &stop_flag,
            deadline,
            &epoch,
            &mut last_cursor,
            &mut last_health,
            reconnects,
            source_ends,
            follow_attempts,
            &last_attempt_end,
            faults.last(),
        );
        driver.close();

        let (exit_val, reached_full, ready_ms) = match exit {
            Ok(e) => {
                let rf = matches!(
                    e,
                    AttemptExit::CleanSourceStop {
                        reached_full: true,
                        ..
                    } | AttemptExit::Fault {
                        reached_full: true,
                        ..
                    }
                );
                let rm = match &e {
                    AttemptExit::CleanSourceStop {
                        ready_duration_ms, ..
                    }
                    | AttemptExit::Fault {
                        ready_duration_ms, ..
                    } => *ready_duration_ms,
                    _ => 0,
                };
                (e, rf, rm)
            }
            Err(e) => break ("failed", e.to_string()),
        };

        if reached_full && ready_ms >= STABLE_MS {
            retry_streak = 0;
            follow_delay_ms = FOLLOW_INITIAL_MS;
            following = false;
        }

        let decision = decide_recovery(&exit_val, following, args.follow_source, retry_streak);
        match &decision {
            RecoveryAction::Incomplete(r) => {
                break ("incomplete", r.clone());
            }
            RecoveryAction::Close
            | RecoveryAction::Follow
            | RecoveryAction::Retry
            | RecoveryAction::Fail(_) => {
                let (cat, reason, phase, nf, rer) = match &exit_val {
                    AttemptExit::CleanSourceStop {
                        phase,
                        native_failure,
                        remote_end_reason,
                        ..
                    } => (
                        AttemptCategory::CleanSourceStop,
                        "source-hltv-stop".to_string(),
                        phase.clone(),
                        *native_failure,
                        *remote_end_reason,
                    ),
                    AttemptExit::Fault {
                        category,
                        reason,
                        phase,
                        native_failure,
                        remote_end_reason,
                        ..
                    } => (
                        *category,
                        reason.clone(),
                        phase.clone(),
                        *native_failure,
                        *remote_end_reason,
                    ),
                    _ => unreachable!(),
                };

                // Supervisor owns connection-level discontinuity & clears last_cursor.
                last_cursor = None;
                let disc_seq = sink.next_sequence();
                let conn_disc = DiscontinuityRecord {
                    kind: "discontinuity",
                    scope: "connection",
                    reason: reason.clone(),
                    source: source.clone(),
                    channel,
                    world: driver.core.identity.world,
                    sequence: disc_seq,
                };
                if let Err(e) = sink.emit_with_seq(disc_seq, &conn_disc) {
                    break ("failed", e.to_string());
                }

                let summary = AttemptEndSummary {
                    channel,
                    category: cat.as_str().into(),
                    reason: reason.clone(),
                    phase,
                    native_failure: nf,
                    remote_end_reason: rer,
                    last_delivered_sequence: sink.delivered_sequence(),
                };
                last_attempt_end = Some(summary.clone());

                match decision {
                    RecoveryAction::Close => {
                        source_ends += 1;
                        break ("closed", reason);
                    }
                    RecoveryAction::Fail(terminal_reason) => {
                        faults.push(summary);
                        if faults.len() > 8 {
                            faults.remove(0);
                        }
                        break ("failed", terminal_reason);
                    }
                    RecoveryAction::Follow => {
                        if cat == AttemptCategory::CleanSourceStop {
                            source_ends += 1;
                            following = true;
                        }
                        follow_attempts += 1;
                        let delay = jittered_ms(
                            follow_delay_ms,
                            channel ^ epoch.elapsed().as_nanos() as u64,
                        );
                        follow_delay_ms = (follow_delay_ms * 2).min(FOLLOW_MAX_MS);
                        let h = backoff_health(
                            &source,
                            channel,
                            "follow-source",
                            delay,
                            reconnects,
                            source_ends,
                            follow_attempts,
                            &last_attempt_end,
                            faults.last(),
                        );
                        stderr_log.emit_health(&h);
                        last_health = Some(h);
                        if !wait_backoff(delay, &stop_flag, deadline) {
                            let r = if stop_flag.load(Ordering::SeqCst) {
                                "owner-stopped"
                            } else {
                                "duration-limit-incomplete"
                            };
                            break ("incomplete", r.into());
                        }
                    }
                    RecoveryAction::Retry => {
                        faults.push(summary);
                        if faults.len() > 8 {
                            faults.remove(0);
                        }
                        let base = FAULT_INITIAL_MS * (1u64 << retry_streak.min(10));
                        retry_streak += 1;
                        let delay = jittered_ms(base, channel ^ epoch.elapsed().as_nanos() as u64);
                        let h = backoff_health(
                            &source,
                            channel,
                            "fault-retry",
                            delay,
                            reconnects,
                            source_ends,
                            follow_attempts,
                            &last_attempt_end,
                            faults.last(),
                        );
                        stderr_log.emit_health(&h);
                        last_health = Some(h);
                        if !wait_backoff(delay, &stop_flag, deadline) {
                            let r = if stop_flag.load(Ordering::SeqCst) {
                                "owner-stopped"
                            } else {
                                "duration-limit-incomplete"
                            };
                            break ("incomplete", r.into());
                        }
                        reconnects += 1;
                    }
                    RecoveryAction::Incomplete(_) => unreachable!(),
                }
            }
        }
    };

    cfg.password.zeroize();

    if let Some(ref mut h) = last_health {
        h.state = "stopped";
        h.ready = false;
        h.reason = reason.clone();
        stderr_log.emit_health(h);
    }

    let drain_stdout = outcome == "closed";
    let stdout_clean = sink.close(drain_stdout);
    let outcome = if outcome == "closed" && !stdout_clean {
        "failed"
    } else {
        outcome
    };
    let final_seq = sink.delivered_sequence();
    stderr_log.close();

    let report = ReportV2 {
        schema: "cs2-observer-report/2",
        outcome,
        reason: reason.clone(),
        cleanup_completed: stdout_clean,
        report_written: true,
        source,
        channel: channel.max(1),
        world: last_health.as_ref().map(|h| h.world).unwrap_or(1),
        last_output_sequence: final_seq,
        reconnects,
        source_ends,
        follow_attempts,
        native_boot_code,
        steam_init_result,
        last_attempt_end,
        faults,
        health: last_health,
    };
    write_report_file(Path::new(&args.output), &report).map_err(|e| ManagedError {
        reason: e,
        report_written: false,
    })?;
    if outcome == "failed" {
        Err(ManagedError {
            reason,
            report_written: true,
        })
    } else {
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
pub fn run_single_attempt<P: ObserverPort, S: RecordSink>(
    driver: &mut ObserverDriver<P>,
    sink: &mut S,
    stderr_log: Option<&AsyncStderrLogger>,
    stop_flag: &AtomicBool,
    deadline: Option<Instant>,
    epoch: &Instant,
    last_cursor: &mut Option<LastDeliveredCursor>,
    last_health: &mut Option<HealthV2>,
    reconnects: u64,
    source_ends: u64,
    follow_attempts: u64,
    last_attempt_end: &Option<AttemptEndSummary>,
    last_fault: Option<&AttemptEndSummary>,
) -> Result<AttemptExit, SessionError> {
    let mut ready_since: Option<Instant> = None;
    let mut next_health_ms = 0u64;

    loop {
        if stop_flag.load(Ordering::SeqCst) {
            return Ok(AttemptExit::OwnerStopped {
                phase: driver.phase.as_str().into(),
                native_failure: Some(driver.port.failure()),
                remote_end_reason: Some(driver.port.remote_end_reason()),
            });
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                return Ok(AttemptExit::DurationLimit {
                    phase: driver.phase.as_str().into(),
                    native_failure: Some(driver.port.failure()),
                    remote_end_reason: Some(driver.port.remote_end_reason()),
                });
            }
        }

        let step_res = driver.step_with_clock(|| epoch.elapsed().as_millis() as u64);

        for ev in driver.emitted.drain(..) {
            match ev {
                DriverEmit::Cursor(mut c) => {
                    let seq = sink.next_sequence();
                    c.sequence = seq;
                    let committed = c.committed_tick;
                    let world = c.world;
                    sink.emit_with_seq(seq, &c)?;
                    *last_cursor = Some(LastDeliveredCursor {
                        channel: driver.core.identity.channel,
                        world,
                        committed_tick: committed,
                        sequence: seq,
                    });
                    if ready_since.is_none() {
                        ready_since = Some(Instant::now());
                    }
                }
                DriverEmit::RawEvent(mut e) => {
                    let seq = sink.next_sequence();
                    e.sequence = seq;
                    sink.emit_with_seq(seq, &e)?;
                }
                DriverEmit::Discontinuity {
                    scope,
                    reason,
                    world,
                } => {
                    ready_since = None;
                    *last_cursor = None;
                    let seq = sink.next_sequence();
                    let rec = DiscontinuityRecord {
                        kind: "discontinuity",
                        scope,
                        reason,
                        source: driver.core.identity.source.clone(),
                        channel: driver.core.identity.channel,
                        world,
                        sequence: seq,
                    };
                    sink.emit_with_seq(seq, &rec)?;
                }
            }
        }

        let now_ms = epoch.elapsed().as_millis() as u64;
        if now_ms >= next_health_ms {
            next_health_ms = now_ms + HEALTH_INTERVAL_MS;
            let state = if driver.drain_deadline.is_some() {
                "retiring"
            } else if ready_since.is_some() {
                if driver.gap || driver.world_sync.recovery != RecoveryState::Normal {
                    "catching-up"
                } else {
                    "connected"
                }
            } else {
                "initializing"
            };
            let (decode_us, decode_max_us) = driver.take_decode_window();
            let h = HealthV2 {
                r#type: "cs2-observer-health/2",
                source: driver.core.identity.source.clone(),
                channel: driver.core.identity.channel,
                world: driver.core.identity.world,
                state,
                reason: driver.reason.clone().unwrap_or_else(|| state.into()),
                upstream_freshness: "unknown",
                ready: ready_since.is_some(),
                reconnects,
                source_ends,
                follow_attempts,
                retry_in_ms: None,
                wait_reason: None,
                sdk_queue_age_us: driver.last_sdk_age_us,
                sdk_max_age_us: driver.max_sdk_age_us,
                decode_us,
                decode_max_us,
                context_tick: driver.context_tick,
                network_tick: Some(driver.core.network_tick).filter(|&t| t >= 0),
                committed_tick: driver.core.committed_tick(),
                committed_ticks_per_second: if state == "connected" {
                    driver.cursor_rate
                } else {
                    None
                },
                last_delivered_cursor: last_cursor.clone(),
                last_attempt_end: last_attempt_end.clone(),
                last_fault: last_fault.cloned(),
            };
            if let Some(logger) = stderr_log {
                logger.emit_health(&h);
            }
            *last_health = Some(h);
        }

        match step_res {
            Ok(had_work) => {
                if driver.done() {
                    let reason = driver.reason.clone().unwrap_or_else(|| "closed".into());
                    let ready_ms = ready_since
                        .map(|t| t.elapsed().as_millis() as u64)
                        .unwrap_or(0);
                    if driver.drain_completed && reason == "source-hltv-stop" {
                        return Ok(AttemptExit::CleanSourceStop {
                            phase: driver.phase.as_str().into(),
                            native_failure: Some(driver.port.failure()),
                            remote_end_reason: Some(driver.port.remote_end_reason()),
                            reached_full: driver.ever_full,
                            ready_duration_ms: ready_ms,
                        });
                    }
                    return Ok(AttemptExit::Fault {
                        category: AttemptCategory::TerminalFault,
                        reason,
                        phase: driver.phase.as_str().into(),
                        native_failure: Some(driver.port.failure()),
                        remote_end_reason: Some(driver.port.remote_end_reason()),
                        reached_full: driver.ever_full,
                        ready_duration_ms: ready_ms,
                    });
                }
                if !had_work {
                    std::thread::sleep(Duration::from_millis(5));
                }
            }
            Err(err) => {
                let cat = classify_session_error(
                    &err,
                    driver.phase,
                    driver.port.failure(),
                    driver.port.remote_end_reason(),
                );
                let ready_ms = ready_since
                    .map(|t| t.elapsed().as_millis() as u64)
                    .unwrap_or(0);
                return Ok(AttemptExit::Fault {
                    category: cat,
                    reason: err.to_string(),
                    phase: driver.phase.as_str().into(),
                    native_failure: Some(driver.port.failure()),
                    remote_end_reason: Some(driver.port.remote_end_reason()),
                    reached_full: driver.ever_full,
                    ready_duration_ms: ready_ms,
                });
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn backoff_health(
    source: &str,
    channel: u64,
    wait_reason: &'static str,
    delay_ms: u64,
    reconnects: u64,
    source_ends: u64,
    follow_attempts: u64,
    last_attempt_end: &Option<AttemptEndSummary>,
    last_fault: Option<&AttemptEndSummary>,
) -> HealthV2 {
    HealthV2 {
        r#type: "cs2-observer-health/2",
        source: source.to_string(),
        channel,
        world: 1,
        state: "backoff",
        reason: wait_reason.into(),
        upstream_freshness: "unknown",
        ready: false,
        reconnects,
        source_ends,
        follow_attempts,
        retry_in_ms: Some(delay_ms),
        wait_reason: Some(wait_reason),
        sdk_queue_age_us: None,
        sdk_max_age_us: None,
        decode_us: None,
        decode_max_us: None,
        context_tick: None,
        network_tick: None,
        committed_tick: None,
        committed_ticks_per_second: None,
        last_delivered_cursor: None,
        last_attempt_end: last_attempt_end.clone(),
        last_fault: last_fault.cloned(),
    }
}

fn wait_backoff(delay_ms: u64, stop_flag: &AtomicBool, deadline: Option<Instant>) -> bool {
    let until = Instant::now() + Duration::from_millis(delay_ms);
    while Instant::now() < until {
        if stop_flag.load(Ordering::SeqCst) {
            return false;
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                return false;
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    true
}
