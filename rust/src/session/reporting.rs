use std::io::Write;
use std::path::Path;

use serde::Serialize;
use serde_json::Value;

pub const MAX_RECORD_BYTES: usize = 65536;
pub const MAX_PUBLIC_SEQUENCE: u64 = 9_007_199_254_740_991;

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
    pub last_output_sequence: u64,
}

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
    pub ok: bool,
    pub reason: String,
    pub source: String,
    pub channel: u64,
    pub world: u64,
    pub last_output_sequence: u64,
    pub reconnects: u64,
    pub source_ends: u64,
    pub follow_attempts: u64,
    pub last_attempt_end: Option<AttemptEndSummary>,
    pub faults: Vec<AttemptEndSummary>,
    pub health: Option<HealthV2>,
}

pub fn encode_jsonl_line<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    let mut line = serde_json::to_vec(value).map_err(|e| format!("output-serialize: {e}"))?;
    line.push(b'\n');
    if line.len() > MAX_RECORD_BYTES {
        return Err("output-record-budget".into());
    }
    Ok(line)
}

pub fn unix_ms_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

pub struct PublicJsonlSink<W: Write> {
    writer: W,
    pub sequence: u64,
}

impl<W: Write> PublicJsonlSink<W> {
    pub fn new(writer: W) -> Self {
        Self {
            writer,
            sequence: 0,
        }
    }

    pub fn next_sequence(&mut self) -> Result<u64, String> {
        if self.sequence >= MAX_PUBLIC_SEQUENCE {
            return Err("output-sequence-budget".into());
        }
        self.sequence += 1;
        Ok(self.sequence)
    }

    pub fn emit_value(&mut self, mut val: Value) -> Result<u64, String> {
        let seq = self.next_sequence()?;
        if let Some(obj) = val.as_object_mut() {
            obj.insert("sequence".into(), Value::from(seq));
        }
        let line = encode_jsonl_line(&val)?;
        self.writer
            .write_all(&line)
            .map_err(|_| "output-closed".to_string())?;
        self.writer
            .flush()
            .map_err(|_| "output-closed".to_string())?;
        Ok(seq)
    }

    pub fn emit_struct<T: Serialize>(&mut self, val: &T) -> Result<(), String> {
        let line = encode_jsonl_line(val)?;
        self.writer
            .write_all(&line)
            .map_err(|_| "output-closed".to_string())?;
        self.writer
            .flush()
            .map_err(|_| "output-closed".to_string())?;
        Ok(())
    }
}

pub fn write_report_file(dir: &Path, report: &ReportV2) -> Result<(), String> {
    let path = dir.join("report.json");
    let data = serde_json::to_vec_pretty(report).map_err(|e| e.to_string())?;
    std::fs::write(&path, data).map_err(|e| format!("report-write: {e}"))
}
