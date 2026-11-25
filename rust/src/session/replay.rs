use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

use serde_json::Value;

use super::driver::{DriverEmit, DriverPhase, ObserverDriver};
use super::reporting::{DiscontinuityRecord, RecordSink, SyncJsonlSink};
use crate::native::password::SecretBytes;
use crate::native::{ObserverPort, ReceivedPacket};

pub const CAPTURE_MAGIC: &[u8; 8] = b"MZRCS2\x01\0";

struct OfflinePort;

impl ObserverPort for OfflinePort {
    fn state(&self) -> i32 {
        4
    }
    fn failure(&self) -> i32 {
        7
    }
    fn remote_end_reason(&self) -> i32 {
        0
    }
    fn pump(&mut self, _now_ms: u64) {}
    fn remote_id(&self) -> u64 {
        0
    }
    fn local_id(&self) -> u64 {
        0
    }
    fn accept_server_auth2(&mut self) -> Result<(), String> {
        Ok(())
    }
    fn request_ticket(&mut self) -> Result<(), String> {
        Ok(())
    }
    fn with_auth<F, R>(&self, _f: F) -> Result<R, String>
    where
        F: FnOnce(&[u8]) -> Result<R, String>,
    {
        Err("offline".into())
    }
    fn send(&mut self, _data: &[u8], _flags: i32) -> Result<(), String> {
        Ok(())
    }
    fn receive(&mut self) -> Result<Option<ReceivedPacket>, String> {
        Ok(None)
    }
    fn close(&mut self) {}
}

pub fn run_replay(input: &Path, host_version: u32, output_dir: &Path) -> Result<(), String> {
    if output_dir.exists() {
        return Err(format!(
            "output directory already exists: {}",
            output_dir.display()
        ));
    }
    std::fs::create_dir_all(output_dir).map_err(|e| e.to_string())?;

    let events_file = File::create(output_dir.join("events.jsonl")).map_err(|e| e.to_string())?;
    let mut sink = SyncJsonlSink::new(BufWriter::new(events_file));
    let mut driver = ObserverDriver::new(
        OfflinePort,
        host_version,
        SecretBytes::default(),
        "offline:channel-replay".into(),
        1,
        0,
    )
    .map_err(|e| e.to_string())?;
    driver.phase = DriverPhase::Channel;

    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut frames = 0u64;
    let mut last_ms = 0u64;

    let raw_bytes = std::fs::read(input).map_err(|e| e.to_string())?;
    if raw_bytes.starts_with(CAPTURE_MAGIC) {
        let mut pos = CAPTURE_MAGIC.len();
        while pos < raw_bytes.len() {
            if pos + 13 > raw_bytes.len() {
                return Err("sample-truncated-header".into());
            }
            let size = u32::from_le_bytes(raw_bytes[pos..pos + 4].try_into().unwrap()) as usize;
            let elapsed = u64::from_le_bytes(raw_bytes[pos + 4..pos + 12].try_into().unwrap());
            let reliable_byte = raw_bytes[pos + 12];
            pos += 13;
            if size == 0 || size > 4 * 1024 * 1024 || reliable_byte > 1 || elapsed < last_ms {
                return Err("sample-record-boundary".into());
            }
            if pos + size > raw_bytes.len() {
                return Err("sample-truncated-body".into());
            }
            let body = &raw_bytes[pos..pos + size];
            pos += size;
            driver
                .receive_packet(body, reliable_byte != 0, elapsed, None)
                .map_err(|e| e.to_string())?;
            flush_emitted(&mut driver, &mut sink, &mut counts)?;
            frames += 1;
            last_ms = elapsed;
        }
    } else {
        let json: Value = serde_json::from_slice(&raw_bytes).map_err(|e| e.to_string())?;
        let arr = json["frames"]
            .as_array()
            .ok_or_else(|| "invalid-replay-input".to_string())?;
        for f in arr {
            let elapsed = f["elapsedMs"].as_u64().ok_or("invalid-elapsed-ms")?;
            let reliable = f["reliable"].as_bool().ok_or("invalid-reliable")?;
            let b64 = f["bodyBase64"].as_str().ok_or("invalid-body-base64")?;
            let body = decode_base64(b64)?;
            if elapsed < last_ms {
                return Err("sample-record-boundary".into());
            }
            driver
                .receive_packet(&body, reliable, elapsed, None)
                .map_err(|e| e.to_string())?;
            flush_emitted(&mut driver, &mut sink, &mut counts)?;
            frames += 1;
            last_ms = elapsed;
        }
    }

    let report = serde_json::json!({
        "evidence": "CAPTURED_CHANNEL_OFFLINE_REPLAY",
        "online": false,
        "complete": true,
        "frames": frames,
        "sampleDurationMs": last_ms,
        "counts": counts,
        "committedTick": driver.core.committed_tick(),
    });
    let report_bytes = serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?;
    std::fs::write(output_dir.join("report.json"), report_bytes).map_err(|e| e.to_string())?;
    let mut stdout = std::io::stdout().lock();
    let _ = writeln!(stdout, "{report}");
    Ok(())
}

fn flush_emitted<P: ObserverPort, W: Write>(
    driver: &mut ObserverDriver<P>,
    sink: &mut SyncJsonlSink<W>,
    counts: &mut BTreeMap<String, u64>,
) -> Result<(), String> {
    for ev in driver.emitted.drain(..) {
        match ev {
            DriverEmit::Cursor(mut c) => {
                c.sequence = sink.next_sequence();
                *counts.entry("cursor".into()).or_insert(0) += 1;
                sink.emit(&c).map_err(|e| e.to_string())?;
            }
            DriverEmit::RawEvent(mut e) => {
                e.sequence = sink.next_sequence();
                *counts.entry(e.kind.clone()).or_insert(0) += 1;
                sink.emit(&e).map_err(|e| e.to_string())?;
            }
            DriverEmit::Discontinuity {
                scope,
                reason,
                world,
            } => {
                let rec = DiscontinuityRecord {
                    kind: "discontinuity",
                    scope,
                    reason,
                    source: driver.core.identity.source.clone(),
                    channel: driver.core.identity.channel,
                    world,
                    sequence: sink.next_sequence(),
                };
                *counts.entry("discontinuity".into()).or_insert(0) += 1;
                sink.emit(&rec).map_err(|e| e.to_string())?;
            }
        }
    }
    Ok(())
}

fn decode_base64(input: &str) -> Result<Vec<u8>, String> {
    let val = |c: u8| -> Option<u8> {
        match c {
            b'A'..=b'Z' => Some(c - b'A'),
            b'a'..=b'z' => Some(c - b'a' + 26),
            b'0'..=b'9' => Some(c - b'0' + 52),
            b'+' => Some(62),
            b'/' => Some(63),
            _ => None,
        }
    };
    let bytes: Vec<u8> = input.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    let mut out = Vec::with_capacity(bytes.len() * 3 / 4);
    for chunk in bytes.chunks(4) {
        if chunk.len() < 2 {
            return Err("invalid-base64".into());
        }
        let a = val(chunk[0]).ok_or("invalid-base64")?;
        let b = val(chunk[1]).ok_or("invalid-base64")?;
        out.push((a << 2) | (b >> 4));
        if chunk.len() > 2 && chunk[2] != b'=' {
            let c = val(chunk[2]).ok_or("invalid-base64")?;
            out.push((b << 4) | (c >> 2));
            if chunk.len() > 3 && chunk[3] != b'=' {
                let d = val(chunk[3]).ok_or("invalid-base64")?;
                out.push((c << 6) | d);
            }
        }
    }
    Ok(out)
}
