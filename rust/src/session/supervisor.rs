use std::io::Read;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Deserialize;

use super::driver::{DriverEmit, DriverPhase, ObserverDriver};
use super::reporting::{
    write_report_file, AsyncStderrLogger, AsyncStdoutSink, DiscontinuityRecord, FaultSummary,
    HealthV3, RecordSink, ReportV3, SessionStartRecord,
};
use super::SessionError;
use crate::native::abi::{NativePort, NativeStartError};
use crate::native::password::SecretBytes;
use crate::native::ObserverPort;

const STABLE_MS: u64 = 30_000;
const FAULT_INITIAL_MS: u64 = 500;
const FAULT_MAX_MS: u64 = 30_000;
const HEALTH_INTERVAL_MS: u64 = 1_000;

#[derive(Debug, Clone)]
pub struct ManagedArgs {
    pub native: PathBuf,
    pub steam_api: Option<PathBuf>,
    pub host_version: u32,
    pub output: PathBuf,
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
    TransientFault,
    TerminalFault,
}

#[derive(Debug, Clone)]
pub enum AttemptExit {
    OwnerStopped {
        phase: String,
    },
    DurationLimit {
        phase: String,
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
    Retry,
    Stopped(String),
    Fail(String),
}

pub fn decide_recovery(exit: &AttemptExit) -> RecoveryAction {
    match exit {
        AttemptExit::OwnerStopped { .. } => RecoveryAction::Stopped("owner-stopped".into()),
        AttemptExit::DurationLimit { .. } => RecoveryAction::Stopped("duration-limit".into()),
        AttemptExit::CleanSourceStop { .. } => RecoveryAction::Close,
        AttemptExit::Fault {
            category, reason, ..
        } => match category {
            AttemptCategory::CleanSourceStop => RecoveryAction::Close,
            AttemptCategory::TransientFault => RecoveryAction::Retry,
            AttemptCategory::TerminalFault => RecoveryAction::Fail(reason.clone()),
        },
    }
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
    has_ever_full: bool,
) -> AttemptCategory {
    match err {
        SessionError::NativeSessionClosed
        | SessionError::InitializationTimeout
        | SessionError::SourceDrainTimeout
        | SessionError::SourceDrainNativeFailed => AttemptCategory::TransientFault,
        SessionError::PhaseTimeout => {
            if !has_ever_full && phase == DriverPhase::Connection {
                AttemptCategory::TerminalFault
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
        let mut buf = [0u8; 64];
        loop {
            match reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
        }
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

    let epoch = Instant::now();
    let deadline = args
        .seconds
        .map(|s| epoch + Duration::from_secs_f64(s.max(0.0)));

    let mut sink = AsyncStdoutSink::spawn();
    let mut stderr_log = AsyncStderrLogger::spawn();
    let mut channel: u64 = 0;
    let mut world: u64 = 1;
    let mut reconnects: u64 = 0;
    let mut retry_streak: u32 = 0;
    let mut has_ever_full = false;
    let mut faults: Vec<FaultSummary> = Vec::new();
    let mut last_health: Option<HealthV3> = None;
    let mut last_phase: Option<String> = None;
    let mut native_boot_code: Option<i32> = None;
    let mut steam_init_result: Option<i32> = None;

    let (mut outcome, mut reason) = loop {
        if stop_flag.load(Ordering::SeqCst) {
            break ("stopped", "owner-stopped".to_string());
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                break ("stopped", "duration-limit".to_string());
            }
        }

        channel += 1;
        world = 1;
        let start_seq = sink.next_sequence();
        let start_rec = SessionStartRecord {
            kind: "session-start",
            protocol: 3,
            channel,
            world,
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
                let reason = if let Some(se) = start_err {
                    native_boot_code = Some(se.boot_code);
                    steam_init_result = Some(se.init_result);
                    "native-start-failed".to_string()
                } else {
                    e.to_string()
                };
                last_phase = Some("transport".into());
                let summary = FaultSummary {
                    channel,
                    reason: reason.clone(),
                    phase: "transport".into(),
                    native_failure: None,
                    remote_end_reason: None,
                };
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
            &mut last_health,
            reconnects,
            has_ever_full,
            faults.last(),
        );
        world = driver.core.identity.world;
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

        if reached_full {
            has_ever_full = true;
            if ready_ms >= STABLE_MS {
                retry_streak = 0;
            }
        }

        let decision = decide_recovery(&exit_val);
        match &decision {
            RecoveryAction::Stopped(r) => {
                last_phase = match &exit_val {
                    AttemptExit::OwnerStopped { phase } | AttemptExit::DurationLimit { phase } => {
                        Some(phase.clone())
                    }
                    _ => last_phase,
                };
                break ("stopped", r.clone());
            }
            RecoveryAction::Close | RecoveryAction::Retry | RecoveryAction::Fail(_) => {
                let (reason, phase, nf, rer) = match &exit_val {
                    AttemptExit::CleanSourceStop {
                        phase,
                        native_failure,
                        remote_end_reason,
                        ..
                    } => (
                        "source-hltv-stop".to_string(),
                        phase.clone(),
                        *native_failure,
                        *remote_end_reason,
                    ),
                    AttemptExit::Fault {
                        reason,
                        phase,
                        native_failure,
                        remote_end_reason,
                        ..
                    } => (
                        reason.clone(),
                        phase.clone(),
                        *native_failure,
                        *remote_end_reason,
                    ),
                    _ => unreachable!(),
                };
                last_phase = Some(phase.clone());

                let disc_seq = sink.next_sequence();
                let conn_disc = DiscontinuityRecord {
                    kind: "discontinuity",
                    scope: "connection",
                    reason: reason.clone(),
                    channel,
                    world,
                    sequence: disc_seq,
                };
                if let Err(e) = sink.emit_with_seq(disc_seq, &conn_disc) {
                    break ("failed", e.to_string());
                }

                let summary = FaultSummary {
                    channel,
                    reason: reason.clone(),
                    phase,
                    native_failure: nf,
                    remote_end_reason: rer,
                };

                match decision {
                    RecoveryAction::Close => {
                        break ("closed", reason);
                    }
                    RecoveryAction::Fail(terminal_reason) => {
                        faults.push(summary);
                        if faults.len() > 8 {
                            faults.remove(0);
                        }
                        break ("failed", terminal_reason);
                    }
                    RecoveryAction::Retry => {
                        faults.push(summary);
                        if faults.len() > 8 {
                            faults.remove(0);
                        }
                        let base = FAULT_INITIAL_MS
                            .saturating_mul(1u64 << retry_streak.min(6))
                            .min(FAULT_MAX_MS);
                        retry_streak += 1;
                        let delay = jittered_ms(base, channel ^ epoch.elapsed().as_nanos() as u64)
                            .min(FAULT_MAX_MS);
                        let h = backoff_health(channel, delay, reconnects, faults.last());
                        stderr_log.emit_health(&h);
                        last_health = Some(h);
                        if !wait_backoff(delay, &stop_flag, deadline) {
                            let r = if stop_flag.load(Ordering::SeqCst) {
                                "owner-stopped"
                            } else {
                                "duration-limit"
                            };
                            break ("stopped", r.into());
                        }
                        reconnects += 1;
                    }
                    RecoveryAction::Stopped(_) => unreachable!(),
                }
            }
        }
    };

    cfg.password.zeroize();

    let drain_stdout = outcome == "closed";
    let stdout_clean = sink.close(drain_stdout);
    if outcome == "closed" && !stdout_clean {
        outcome = "failed";
        reason = "output-drain-timeout".to_string();
    }

    if let Some(ref mut h) = last_health {
        h.state = if outcome == "failed" {
            "failed"
        } else {
            "ended"
        };
        h.retry_in_ms = None;
        h.reason = reason.clone();
        stderr_log.emit_health(h);
    }

    let final_seq = sink.delivered_sequence();
    stderr_log.close();

    let last_fault = faults.last().cloned();
    let report = ReportV3 {
        schema: "cs2-observer-report/3",
        outcome,
        reason: reason.clone(),
        channel: channel.max(1),
        world,
        last_output_sequence: final_seq,
        reconnects,
        native_boot_code,
        steam_init_result,
        phase: last_phase,
        last_fault,
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
    last_health: &mut Option<HealthV3>,
    reconnects: u64,
    has_ever_full: bool,
    last_fault: Option<&FaultSummary>,
) -> Result<AttemptExit, SessionError> {
    let mut ready_since: Option<Instant> = None;
    let mut next_health_ms = 0u64;

    loop {
        if stop_flag.load(Ordering::SeqCst) {
            return Ok(AttemptExit::OwnerStopped {
                phase: driver.phase.as_str().into(),
            });
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                return Ok(AttemptExit::DurationLimit {
                    phase: driver.phase.as_str().into(),
                });
            }
        }

        let step_res = driver.step_with_clock(|| epoch.elapsed().as_millis() as u64);

        for ev in driver.emitted.drain(..) {
            match ev {
                DriverEmit::Cursor(mut c) => {
                    let seq = sink.next_sequence();
                    c.sequence = seq;
                    sink.emit_with_seq(seq, &c)?;
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
                    let seq = sink.next_sequence();
                    let rec = DiscontinuityRecord {
                        kind: "discontinuity",
                        scope,
                        reason,
                        channel: driver.core.identity.channel,
                        world,
                        sequence: seq,
                    };
                    sink.emit_with_seq(seq, &rec)?;
                }
                DriverEmit::Diagnostic { reason, event_id } => {
                    if let Some(logger) = stderr_log {
                        logger.emit_diagnostic(driver.core.identity.channel, &reason, event_id);
                    }
                }
            }
        }

        let now_ms = epoch.elapsed().as_millis() as u64;
        if now_ms >= next_health_ms {
            next_health_ms = now_ms + HEALTH_INTERVAL_MS;
            let state = if ready_since.is_some() {
                "receiving"
            } else {
                "connecting"
            };
            let (decode_us, decode_max_us) = driver.take_decode_window();
            let h = HealthV3 {
                r#type: "cs2-observer-health/3",
                channel: driver.core.identity.channel,
                world: driver.core.identity.world,
                state,
                reason: driver.reason.clone().unwrap_or_else(|| state.into()),
                reconnects,
                retry_in_ms: None,
                sdk_queue_age_us: driver.last_sdk_age_us,
                sdk_max_age_us: driver.max_sdk_age_us,
                decode_us,
                decode_max_us,
                committed_tick: driver.core.committed_tick(),
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
                    has_ever_full,
                );
                let ready_ms = ready_since
                    .map(|t| t.elapsed().as_millis() as u64)
                    .unwrap_or(0);
                let reason = if !has_ever_full
                    && driver.phase == DriverPhase::Connection
                    && matches!(err, SessionError::PhaseTimeout)
                {
                    "connection-timeout".to_string()
                } else {
                    err.to_string()
                };
                return Ok(AttemptExit::Fault {
                    category: cat,
                    reason,
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

fn backoff_health(
    channel: u64,
    delay_ms: u64,
    reconnects: u64,
    last_fault: Option<&FaultSummary>,
) -> HealthV3 {
    HealthV3 {
        r#type: "cs2-observer-health/3",
        channel,
        world: 1,
        state: "connecting",
        reason: "fault-retry".into(),
        reconnects,
        retry_in_ms: Some(delay_ms),
        sdk_queue_age_us: None,
        sdk_max_age_us: None,
        decode_us: None,
        decode_max_us: None,
        committed_tick: None,
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
