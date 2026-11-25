use std::io::Write;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{sync_channel, SyncSender, TrySendError};
use std::sync::Arc;
use std::thread::JoinHandle;

use serde::Serialize;

use super::SessionError;

pub const MAX_RECORD_BYTES: usize = 65536;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionStartRecord {
    pub kind: &'static str,
    pub protocol: u32,
    pub source: String,
    pub channel: u64,
    pub world: u64,
    pub sequence: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscontinuityRecord {
    pub kind: &'static str,
    pub scope: &'static str,
    pub reason: String,
    pub source: String,
    pub channel: u64,
    pub world: u64,
    pub sequence: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LastDeliveredCursor {
    pub channel: u64,
    pub world: u64,
    pub committed_tick: i32,
    pub sequence: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AttemptEndSummary {
    pub channel: u64,
    pub category: String,
    pub reason: String,
    pub phase: String,
    pub native_failure: Option<i32>,
    pub remote_end_reason: Option<i32>,
    pub last_delivered_sequence: u64,
}

/// Mizar v2 health states: initializing | connected | catching-up | retiring | backoff | stopped
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HealthV2 {
    pub r#type: &'static str,
    pub source: String,
    pub channel: u64,
    pub world: u64,
    pub state: &'static str,
    pub reason: String,
    pub upstream_freshness: &'static str,
    pub ready: bool,
    pub reconnects: u64,
    pub source_ends: u64,
    pub follow_attempts: u64,
    pub retry_in_ms: Option<u64>,
    pub wait_reason: Option<&'static str>,
    pub sdk_queue_age_us: Option<i64>,
    pub sdk_max_age_us: Option<i64>,
    pub decode_us: Option<u64>,
    pub decode_max_us: Option<u64>,
    pub context_tick: Option<i32>,
    pub network_tick: Option<i32>,
    pub committed_tick: Option<i32>,
    pub committed_ticks_per_second: Option<f64>,
    pub last_delivered_cursor: Option<LastDeliveredCursor>,
    pub last_attempt_end: Option<AttemptEndSummary>,
    pub last_fault: Option<AttemptEndSummary>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReportV2 {
    pub schema: &'static str,
    pub outcome: &'static str,
    pub reason: String,
    pub cleanup_completed: bool,
    pub report_written: bool,
    pub source: String,
    pub channel: u64,
    pub world: u64,
    pub last_output_sequence: u64,
    pub reconnects: u64,
    pub source_ends: u64,
    pub follow_attempts: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub native_boot_code: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub steam_init_result: Option<i32>,
    pub last_attempt_end: Option<AttemptEndSummary>,
    pub faults: Vec<AttemptEndSummary>,
    pub health: Option<HealthV2>,
}

pub fn encode_jsonl_line<T: Serialize>(value: &T) -> Result<Vec<u8>, SessionError> {
    let mut line = serde_json::to_vec(value).map_err(|e| SessionError::Protocol(e.to_string()))?;
    line.push(b'\n');
    if line.len() > MAX_RECORD_BYTES {
        return Err(SessionError::OutputRecordBudget);
    }
    Ok(line)
}

pub fn unix_ms_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

pub trait RecordSink {
    fn next_sequence(&mut self) -> u64;
    fn current_sequence(&self) -> u64;
    fn delivered_sequence(&self) -> u64;
    fn emit_with_seq<T: Serialize>(&mut self, seq: u64, val: &T) -> Result<(), SessionError>;
}

pub struct SyncJsonlSink<W: Write> {
    writer: W,
    pub sequence: u64,
}

impl<W: Write> SyncJsonlSink<W> {
    pub fn new(writer: W) -> Self {
        Self {
            writer,
            sequence: 0,
        }
    }
}

impl<W: Write> RecordSink for SyncJsonlSink<W> {
    fn next_sequence(&mut self) -> u64 {
        self.sequence += 1;
        self.sequence
    }

    fn current_sequence(&self) -> u64 {
        self.sequence
    }

    fn delivered_sequence(&self) -> u64 {
        self.sequence
    }

    fn emit_with_seq<T: Serialize>(&mut self, _seq: u64, val: &T) -> Result<(), SessionError> {
        let line = encode_jsonl_line(val)?;
        self.writer
            .write_all(&line)
            .map_err(|_| SessionError::OutputClosed)?;
        self.writer
            .flush()
            .map_err(|_| SessionError::OutputClosed)?;
        Ok(())
    }
}

/// Non-blocking stdout JSONL writer backed by a bounded sync_channel + worker thread.
pub struct AsyncStdoutSink {
    tx: Option<SyncSender<(u64, Vec<u8>)>>,
    handle: Option<JoinHandle<()>>,
    pub sequence: u64,
    delivered: Arc<AtomicU64>,
    write_failed: Arc<AtomicBool>,
}

impl AsyncStdoutSink {
    pub fn spawn() -> Self {
        let (tx, rx) = sync_channel::<(u64, Vec<u8>)>(512);
        let delivered = Arc::new(AtomicU64::new(0));
        let write_failed = Arc::new(AtomicBool::new(false));
        let del_clone = delivered.clone();
        let fail_clone = write_failed.clone();
        let handle = std::thread::spawn(move || {
            let mut out = std::io::BufWriter::new(std::io::stdout().lock());
            while let Ok((seq, line)) = rx.recv() {
                if out.write_all(&line).is_err() || out.flush().is_err() {
                    fail_clone.store(true, Ordering::Release);
                    break;
                }
                del_clone.store(seq, Ordering::Release);
            }
        });
        Self {
            tx: Some(tx),
            handle: Some(handle),
            sequence: 0,
            delivered,
            write_failed,
        }
    }

    pub fn close(&mut self, drain: bool) -> bool {
        self.tx.take();
        let Some(h) = self.handle.take() else {
            return !self.write_failed.load(Ordering::Acquire);
        };
        if drain && !self.write_failed.load(Ordering::Acquire) {
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
            while !h.is_finished() && std::time::Instant::now() < deadline {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            if h.is_finished() {
                let _ = h.join();
                return !self.write_failed.load(Ordering::Acquire);
            }
            return false;
        }
        !self.write_failed.load(Ordering::Acquire)
    }
}

impl Drop for AsyncStdoutSink {
    fn drop(&mut self) {
        self.tx.take();
        self.handle.take();
    }
}

impl RecordSink for AsyncStdoutSink {
    fn next_sequence(&mut self) -> u64 {
        self.sequence += 1;
        self.sequence
    }

    fn current_sequence(&self) -> u64 {
        self.sequence
    }

    fn delivered_sequence(&self) -> u64 {
        self.delivered.load(Ordering::Acquire)
    }

    fn emit_with_seq<T: Serialize>(&mut self, seq: u64, val: &T) -> Result<(), SessionError> {
        if self.write_failed.load(Ordering::Acquire) {
            return Err(SessionError::OutputClosed);
        }
        let line = encode_jsonl_line(val)?;
        let Some(tx) = &self.tx else {
            return Err(SessionError::OutputClosed);
        };
        match tx.try_send((seq, line)) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => Err(SessionError::OutputBackpressure),
            Err(TrySendError::Disconnected(_)) => Err(SessionError::OutputClosed),
        }
    }
}

/// Non-blocking stderr health logger; drops diagnostic lines if pipe is full.
pub struct AsyncStderrLogger {
    tx: Option<SyncSender<Vec<u8>>>,
    handle: Option<JoinHandle<()>>,
}

impl Default for AsyncStderrLogger {
    fn default() -> Self {
        Self::spawn()
    }
}

impl AsyncStderrLogger {
    pub fn spawn() -> Self {
        let (tx, rx) = sync_channel::<Vec<u8>>(64);
        let handle = std::thread::spawn(move || {
            let mut err = std::io::stderr().lock();
            while let Ok(line) = rx.recv() {
                if err.write_all(&line).is_err() {
                    break;
                }
            }
        });
        Self {
            tx: Some(tx),
            handle: Some(handle),
        }
    }

    pub fn emit_health(&self, h: &HealthV2) {
        if let Some(tx) = &self.tx {
            if let Ok(line) = encode_jsonl_line(h) {
                let _ = tx.try_send(line);
            }
        }
    }

    pub fn close(&mut self) {
        self.tx.take();
        if let Some(h) = self.handle.take() {
            let deadline = std::time::Instant::now() + std::time::Duration::from_millis(200);
            while !h.is_finished() && std::time::Instant::now() < deadline {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            if h.is_finished() {
                let _ = h.join();
            }
        }
    }
}

impl Drop for AsyncStderrLogger {
    fn drop(&mut self) {
        self.close();
    }
}

pub fn write_report_file(dir: &Path, report: &ReportV2) -> Result<(), String> {
    let path = dir.join("report.json");
    let data = serde_json::to_vec_pretty(report).map_err(|e| e.to_string())?;
    std::fs::write(&path, data).map_err(|e| format!("report-write: {e}"))
}
