use std::io::{BufRead, BufReader, Read, Write};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Deserialize;

use super::driver::{DriverEmit, DriverPhase, ObserverDriver};
use super::reporting::{
    encode_jsonl_line, write_report_file, AttemptEndSummary, DiscontinuityRecord, HealthV2,
    LastDeliveredCursor, PublicJsonlSink, ReportV2, SessionStartRecord,
};
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
pub struct AttemptOutcome {
    pub category: AttemptCategory,
    pub reason: String,
    pub phase: String,
    pub native_failure: Option<i32>,
    pub remote_end_reason: Option<i32>,
    pub reached_full: bool,
    pub ready_duration_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RecoveryAction {
    Close,
    Follow,
    Retry,
    Fail(String),
}

pub fn decide_recovery(
    outcome: &AttemptOutcome,
    following: bool,
    follow_source: bool,
    retry_streak: u32,
) -> RecoveryAction {
    if outcome.category == AttemptCategory::CleanSourceStop {
        if follow_source {
            return RecoveryAction::Follow;
        }
        return RecoveryAction::Close;
    }
    if following && outcome.category == AttemptCategory::SourceUnavailable {
        return RecoveryAction::Follow;
    }
    if following
        && outcome.native_failure == Some(7)
        && outcome.category == AttemptCategory::TransientFault
        && !is_timeout_end_reason(outcome.remote_end_reason)
    {
        return RecoveryAction::Fail(outcome.reason.clone());
    }
    if matches!(
        outcome.category,
        AttemptCategory::SourceUnavailable | AttemptCategory::TransientFault
    ) {
        if retry_streak >= RETRY_LIMIT {
            return RecoveryAction::Fail("reconnect-budget-exhausted".into());
        }
        return RecoveryAction::Retry;
    }
    RecoveryAction::Fail(outcome.reason.clone())
}

fn is_timeout_end_reason(code: Option<i32>) -> bool {
    matches!(code, Some(3001..=3005 | 4001..=4005 | 5001..=5005))
}

fn jittered_ms(base_ms: u64, seed: u64) -> u64 {
    // Deterministic-friendly ±20% jitter using simple LCG mix on seed
    let mixed = seed
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    let frac = ((mixed >> 32) % 401) as i64 - 200; // -200..=+200 permille
    let adjusted = (base_ms as i64) + ((base_ms as i64) * frac) / 1000;
    adjusted.max(50) as u64
}

pub fn run_managed(args: ManagedArgs) -> Result<(), String> {
    if args.output.exists() {
        return Err(format!(
            "output directory already exists: {}",
            args.output.display()
        ));
    }
    std::fs::create_dir_all(&args.output).map_err(|e| e.to_string())?;

    let mut stdin_lock = std::io::stdin().lock();
    let mut cfg = read_managed_config(&mut stdin_lock)?;
    drop(stdin_lock);

    let stop_flag = Arc::new(AtomicBool::new(false));
    let stop_clone = stop_flag.clone();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(std::io::stdin());
        let mut line = String::new();
        // Any EOF or extra input requests stop
        let _ = reader.read_line(&mut line);
        stop_clone.store(true, Ordering::SeqCst);
    });

    let source = format!("{}:{}", args.source_role, args.source_id);
    let epoch = Instant::now();
    let deadline = args
        .seconds
        .map(|s| epoch + Duration::from_secs_f64(s.max(0.0)));

    let mut sink = PublicJsonlSink::new(std::io::stdout().lock());
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

    let res = (|| -> Result<String, String> {
        loop {
            if stop_flag.load(Ordering::SeqCst) {
                return Ok("owner-stopped".into());
            }
            if let Some(dl) = deadline {
                if Instant::now() >= dl {
                    return Err("duration-limit-incomplete".into());
                }
            }

            channel += 1;
            let start_rec = SessionStartRecord {
                kind: "session-start",
                protocol: 2,
                source: source.clone(),
                channel,
                world: 1,
                sequence: sink.next_sequence()?,
            };
            sink.emit_struct(&start_rec)?;

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
                    let is_start_err = e.downcast_ref::<NativeStartError>().is_some();
                    let outcome = AttemptOutcome {
                        category: if is_start_err {
                            AttemptCategory::TerminalFault
                        } else {
                            AttemptCategory::TransientFault
                        },
                        reason: e.to_string(),
                        phase: "transport".into(),
                        native_failure: None,
                        remote_end_reason: None,
                        reached_full: false,
                        ready_duration_ms: 0,
                    };
                    let summary = AttemptEndSummary {
                        channel,
                        category: outcome.category.as_str().into(),
                        reason: outcome.reason.clone(),
                        phase: outcome.phase.clone(),
                        native_failure: None,
                        remote_end_reason: None,
                        last_output_sequence: sink.sequence,
                    };
                    last_attempt_end = Some(summary.clone());
                    faults.push(summary);
                    if faults.len() > 8 {
                        faults.remove(0);
                    }
                    return Err(outcome.reason);
                }
            };

            let mut driver = ObserverDriver::new(
                port,
                args.host_version,
                cfg.password.clone(),
                source.clone(),
                channel,
                now_ms,
            )?;

            let outcome = run_single_attempt(
                &mut driver,
                &mut sink,
                &stop_flag,
                deadline,
                epoch,
                &mut last_cursor,
                &mut last_health,
                reconnects,
                source_ends,
                follow_attempts,
                &last_attempt_end,
                faults.last(),
            )?;
            driver.close();

            if outcome.reached_full && outcome.ready_duration_ms >= STABLE_MS {
                retry_streak = 0;
                follow_delay_ms = FOLLOW_INITIAL_MS;
            }

            let summary = AttemptEndSummary {
                channel,
                category: outcome.category.as_str().into(),
                reason: outcome.reason.clone(),
                phase: outcome.phase.clone(),
                native_failure: outcome.native_failure,
                remote_end_reason: outcome.remote_end_reason,
                last_output_sequence: sink.sequence,
            };
            last_attempt_end = Some(summary.clone());

            match decide_recovery(&outcome, following, args.follow_source, retry_streak) {
                RecoveryAction::Close => return Ok(outcome.reason),
                RecoveryAction::Fail(r) => {
                    faults.push(summary);
                    if faults.len() > 8 {
                        faults.remove(0);
                    }
                    return Err(r);
                }
                RecoveryAction::Follow => {
                    if outcome.category == AttemptCategory::CleanSourceStop {
                        source_ends += 1;
                    }
                    following = true;
                    follow_attempts += 1;
                    let delay =
                        jittered_ms(follow_delay_ms, channel ^ epoch.elapsed().as_nanos() as u64);
                    follow_delay_ms = (follow_delay_ms * 2).min(FOLLOW_MAX_MS);
                    if !wait_backoff(delay, &stop_flag, deadline) {
                        return Ok("owner-stopped".into());
                    }
                }
                RecoveryAction::Retry => {
                    faults.push(summary);
                    if faults.len() > 8 {
                        faults.remove(0);
                    }
                    let base = FAULT_INITIAL_MS * (1u64 << retry_streak.min(10));
                    retry_streak += 1;
                    reconnects += 1;
                    let delay = jittered_ms(base, channel ^ epoch.elapsed().as_nanos() as u64);
                    if !wait_backoff(delay, &stop_flag, deadline) {
                        return Ok("owner-stopped".into());
                    }
                }
            }
        }
    })();

    cfg.password.zeroize();

    let (ok, reason) = match res {
        Ok(r) => (true, r),
        Err(r) => (false, r),
    };
    let report = ReportV2 {
        schema: "cs2-observer-report/2",
        ok,
        reason: reason.clone(),
        source,
        channel: channel.max(1),
        world: last_health.as_ref().map(|h| h.world).unwrap_or(1),
        last_output_sequence: sink.sequence,
        reconnects,
        source_ends,
        follow_attempts,
        last_attempt_end,
        faults,
        health: last_health,
    };
    let _ = write_report_file(Path::new(&args.output), &report);
    if ok {
        Ok(())
    } else {
        Err(reason)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn run_single_attempt<P: ObserverPort, W: Write>(
    driver: &mut ObserverDriver<P>,
    sink: &mut PublicJsonlSink<W>,
    stop_flag: &AtomicBool,
    deadline: Option<Instant>,
    epoch: Instant,
    last_cursor: &mut Option<LastDeliveredCursor>,
    last_health: &mut Option<HealthV2>,
    reconnects: u64,
    source_ends: u64,
    follow_attempts: u64,
    last_attempt_end: &Option<AttemptEndSummary>,
    last_fault: Option<&AttemptEndSummary>,
) -> Result<AttemptOutcome, String> {
    let mut ready_since: Option<Instant> = None;
    let mut next_health_ms = 0u64;

    loop {
        if stop_flag.load(Ordering::SeqCst) {
            return Ok(AttemptOutcome {
                category: AttemptCategory::CleanSourceStop,
                reason: "owner-stopped".into(),
                phase: driver.phase.as_str().into(),
                native_failure: Some(driver.port.failure()),
                remote_end_reason: Some(driver.port.remote_end_reason()),
                reached_full: driver.ever_full,
                ready_duration_ms: ready_since
                    .map(|t| t.elapsed().as_millis() as u64)
                    .unwrap_or(0),
            });
        }
        if let Some(dl) = deadline {
            if Instant::now() >= dl {
                return Ok(AttemptOutcome {
                    category: AttemptCategory::TerminalFault,
                    reason: "duration-limit-incomplete".into(),
                    phase: driver.phase.as_str().into(),
                    native_failure: Some(driver.port.failure()),
                    remote_end_reason: Some(driver.port.remote_end_reason()),
                    reached_full: driver.ever_full,
                    ready_duration_ms: ready_since
                        .map(|t| t.elapsed().as_millis() as u64)
                        .unwrap_or(0),
                });
            }
        }

        let now_ms = epoch.elapsed().as_millis() as u64;
        let step_res = driver.step(now_ms);

        for ev in driver.emitted.drain(..) {
            match ev {
                DriverEmit::Cursor {
                    record,
                    committed_tick,
                    world,
                    ..
                } => {
                    let seq = sink.emit_value(record)?;
                    *last_cursor = Some(LastDeliveredCursor {
                        channel: driver.core.identity.channel,
                        world,
                        committed_tick,
                        sequence: seq,
                    });
                    if ready_since.is_none() {
                        ready_since = Some(Instant::now());
                    }
                }
                DriverEmit::RawEvent { record, .. } => {
                    sink.emit_value(record)?;
                }
                DriverEmit::Discontinuity {
                    scope,
                    reason,
                    world,
                } => {
                    ready_since = None;
                    *last_cursor = None;
                    let rec = DiscontinuityRecord {
                        kind: "discontinuity",
                        scope,
                        reason,
                        source: driver.core.identity.source.clone(),
                        channel: driver.core.identity.channel,
                        world,
                        sequence: sink.next_sequence()?,
                    };
                    sink.emit_struct(&rec)?;
                }
            }
        }

        if now_ms >= next_health_ms {
            next_health_ms = now_ms + HEALTH_INTERVAL_MS;
            let state = if driver.gap || driver.world_sync.recovery_pending {
                "discontinuity"
            } else if !driver.world_sync.full_sent {
                "unknown"
            } else if ready_since.is_some() && driver.cursor_rate.is_some() {
                "live"
            } else {
                "unknown"
            };
            let h = HealthV2 {
                r#type: "cs2-observer-health/2",
                source: driver.core.identity.source.clone(),
                channel: driver.core.identity.channel,
                world: driver.core.identity.world,
                state,
                reason: driver.reason.clone().unwrap_or_else(|| "observing".into()),
                upstream_freshness: "unknown",
                ready: ready_since.is_some(),
                reconnects,
                source_ends,
                follow_attempts,
                retry_in_ms: None,
                wait_reason: None,
                sdk_queue_age_us: driver.last_sdk_age_us,
                sdk_max_age_us: driver.max_sdk_age_us,
                context_tick: driver.decoder.tick.map(|t| t as i32),
                network_tick: Some(driver.core.network_tick).filter(|&t| t >= 0),
                committed_tick: driver.core.committed_tick(),
                committed_ticks_per_second: if state == "live" {
                    driver.cursor_rate
                } else {
                    None
                },
                last_delivered_cursor: last_cursor.clone(),
                last_attempt_end: last_attempt_end.clone(),
                last_fault: last_fault.cloned(),
            };
            if let Ok(line) = encode_jsonl_line(&h) {
                let _ = std::io::stderr().write_all(&line);
            }
            *last_health = Some(h);
        }

        match step_res {
            Ok(had_work) => {
                if driver.done() {
                    let reason = driver.reason.clone().unwrap_or_else(|| "closed".into());
                    let cat = if driver.drain_completed && reason == "source-hltv-stop" {
                        AttemptCategory::CleanSourceStop
                    } else {
                        AttemptCategory::TerminalFault
                    };
                    return Ok(AttemptOutcome {
                        category: cat,
                        reason,
                        phase: driver.phase.as_str().into(),
                        native_failure: Some(driver.port.failure()),
                        remote_end_reason: Some(driver.port.remote_end_reason()),
                        reached_full: driver.ever_full,
                        ready_duration_ms: ready_since
                            .map(|t| t.elapsed().as_millis() as u64)
                            .unwrap_or(0),
                    });
                }
                if !had_work {
                    std::thread::sleep(Duration::from_millis(5));
                }
            }
            Err(err) => {
                let cat = classify_error(&err, driver.phase, driver.port.failure());
                return Ok(AttemptOutcome {
                    category: cat,
                    reason: err,
                    phase: driver.phase.as_str().into(),
                    native_failure: Some(driver.port.failure()),
                    remote_end_reason: Some(driver.port.remote_end_reason()),
                    reached_full: driver.ever_full,
                    ready_duration_ms: ready_since
                        .map(|t| t.elapsed().as_millis() as u64)
                        .unwrap_or(0),
                });
            }
        }
    }
}

fn classify_error(err: &str, phase: DriverPhase, native_failure: i32) -> AttemptCategory {
    if matches!(
        err,
        "initialization-timeout" | "native-session-closed" | "source-drain-timeout"
    ) {
        return AttemptCategory::TransientFault;
    }
    if err == "phase-timeout" {
        return if matches!(phase, DriverPhase::Transport | DriverPhase::Challenge) {
            AttemptCategory::SourceUnavailable
        } else {
            AttemptCategory::TransientFault
        };
    }
    if native_failure == 7 && err.starts_with("native-") {
        return AttemptCategory::TransientFault;
    }
    AttemptCategory::TerminalFault
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
