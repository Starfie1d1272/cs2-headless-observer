use std::collections::{BTreeMap, HashSet};

use crate::wire::bits::{
    encode_pb_bytes, encode_pb_varint, scalar_bytes, scalar_fixed32, scalar_varint, wire_fields,
    BitReader, WireError, MAX_BYTES,
};
use crate::wire::compression::expand_lzss;

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

#[derive(Debug, Clone)]
pub struct ResourceItem {
    pub directory: String,
    pub name: String,
    pub extension: String,
}

fn read_manifest_string(r: &mut BitReader<'_>) -> Result<String, String> {
    let bytes = r.read_string_nul(4096).map_err(|e| e.to_string())?;
    String::from_utf8(bytes).map_err(|_| "manifest-string-encoding".to_string())
}

pub fn decode_resource_manifest(data: &[u8]) -> Result<Vec<ResourceItem>, String> {
    if data.len() > 128 * 1024 {
        return Err("manifest-wire-budget".into());
    }
    if data.is_empty() {
        return Ok(Vec::new());
    }
    let mut env = BitReader::new(data).map_err(|e| e.to_string())?;
    let compressed = env.read_bits(1).map_err(|e| e.to_string())?;
    let size = env.read_bits(24).map_err(|e| e.to_string())? as usize;
    let raw_payload = env.read_bytes(size).map_err(|e| e.to_string())?;
    if env.remaining_bits() >= 8 {
        return Err("manifest-trailing-bytes".into());
    }
    let owned_payload;
    let payload = if compressed != 0 {
        owned_payload = expand_lzss(&raw_payload).map_err(|e| e.to_string())?;
        owned_payload.as_slice()
    } else {
        &raw_payload
    };

    let mut r = BitReader::new(payload).map_err(|e| e.to_string())?;
    let ext_count = r.read_bits(16).map_err(|e| e.to_string())? as usize;
    let dir_count = r.read_bits(16).map_err(|e| e.to_string())? as usize;
    let res_count = r.read_bits(16).map_err(|e| e.to_string())? as usize;
    if res_count > 16384 {
        return Err("manifest-resource-count-budget".into());
    }
    let mut exts = Vec::with_capacity(ext_count);
    for _ in 0..ext_count {
        exts.push(read_manifest_string(&mut r)?);
    }
    let mut dirs = Vec::with_capacity(dir_count);
    for _ in 0..dir_count {
        dirs.push(read_manifest_string(&mut r)?);
    }
    let dir_bits = if dir_count <= 1 {
        1
    } else {
        (32 - ((dir_count - 1) as u32).leading_zeros()) as u8
    };
    let ext_bits = if ext_count <= 1 {
        1
    } else {
        (32 - ((ext_count - 1) as u32).leading_zeros()) as u8
    };
    let mut items = Vec::with_capacity(res_count);
    for _ in 0..res_count {
        let d = r.read_bits(dir_bits).map_err(|e| e.to_string())? as usize;
        let name = read_manifest_string(&mut r)?;
        let e = r.read_bits(ext_bits).map_err(|e| e.to_string())? as usize;
        if d >= dir_count || e >= ext_count {
            return Err("manifest-symbol-index".into());
        }
        items.push(ResourceItem {
            directory: dirs[d].clone(),
            name,
            extension: exts[e].clone(),
        });
    }
    if r.remaining_bits() >= 8 {
        return Err("manifest-payload-trailing-bytes".into());
    }
    Ok(items)
}

#[derive(Debug, Clone, PartialEq)]
pub struct ControlServerInfo {
    pub server_count: u32,
    pub protocol: u32,
    pub map: String,
    pub tick_interval: f32,
    pub player_slot: i32,
}

#[derive(Debug, Clone)]
pub struct SpawnGroup {
    pub flags: u32,
    pub owner: u32,
    pub parent: u32,
    pub savegame: bool,
    pub manifest_incomplete: bool,
    pub fragment_count: usize,
}

#[derive(Debug, Default)]
pub struct ControlDecoder {
    pub tick: Option<u32>,
    pub server: Option<ControlServerInfo>,
    pub counts: BTreeMap<String, u64>,
    pub spawn_groups: BTreeMap<u32, SpawnGroup>,
    pub ready_spawn_groups: HashSet<u32>,
    pub session_manifest_loaded: bool,
    pub max_creation_sequence: u32,
    manifest_name_bytes: usize,
    manifest_resources: usize,
}

impl ControlDecoder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn reset_world(&mut self) {
        let counts = std::mem::take(&mut self.counts);
        *self = Self::default();
        self.counts = counts;
    }

    fn admit_manifest(&mut self, payload: &[u8]) -> Result<(), String> {
        let items = decode_resource_manifest(payload)?;
        let names: usize = items
            .iter()
            .map(|i| i.directory.len() + i.name.len() + i.extension.len())
            .sum();
        if self.manifest_name_bytes + names > MAX_BYTES
            || self.manifest_resources + items.len() > 16384
        {
            return Err("spawn-group-session-manifest-budget".into());
        }
        self.manifest_name_bytes += names;
        self.manifest_resources += items.len();
        Ok(())
    }

    pub fn ready_world_groups(&mut self) -> Result<Vec<u32>, String> {
        if !self.session_manifest_loaded {
            return Ok(Vec::new());
        }
        let mut ready = Vec::new();
        let mut pending: Vec<u32> = self
            .spawn_groups
            .keys()
            .copied()
            .filter(|h| !self.ready_spawn_groups.contains(h))
            .collect();
        while !pending.is_empty() {
            let mut advanced = false;
            let mut next_pending = Vec::new();
            for handle in pending {
                let group = &self.spawn_groups[&handle];
                if group.manifest_incomplete {
                    next_pending.push(handle);
                    continue;
                }
                if (group.flags & 1) != 0 || group.savegame {
                    return Err("savegame-world-not-supported".into());
                }
                let owner_ok = group.owner == 0 || self.ready_spawn_groups.contains(&group.owner);
                let parent_ok =
                    group.parent == 0 || self.ready_spawn_groups.contains(&group.parent);
                if !owner_ok || !parent_ok {
                    next_pending.push(handle);
                    continue;
                }
                self.ready_spawn_groups.insert(handle);
                ready.push(handle);
                advanced = true;
            }
            pending = next_pending;
            if !advanced {
                break;
            }
        }
        Ok(ready)
    }

    pub fn consume(&mut self, message_id: u32, body: &[u8]) -> Result<(), String> {
        let key = message_id.to_string();
        if self.counts.contains_key(&key) || self.counts.len() < 1024 {
            *self.counts.entry(key).or_insert(0) += 1;
        } else {
            *self.counts.entry("other".into()).or_insert(0) += 1;
        }

        if !matches!(message_id, 4 | 8 | 9 | 11 | 12 | 40 | 51) {
            return Ok(());
        }
        let f = wire_fields(body, MAX_BYTES).map_err(|e| e.to_string())?;
        match message_id {
            4 => {
                let tick = scalar_varint(&f, 1)
                    .map_err(|e| e.to_string())?
                    .filter(|&t| t <= i32::MAX as u64)
                    .ok_or_else(|| "live-tick-invalid-or-missing".to_string())?;
                self.tick = Some(tick as u32);
            }
            8 => {
                let handle = scalar_varint(&f, 4)
                    .map_err(|e| e.to_string())?
                    .filter(|&h| h > 0 && h <= u32::MAX as u64)
                    .ok_or_else(|| "spawn-group-handle".to_string())?
                    as u32;
                if self.spawn_groups.contains_key(&handle) {
                    return Ok(());
                }
                if self.spawn_groups.len() >= 1024 {
                    return Err("spawn-group-count-budget".into());
                }
                let manifest_bytes = scalar_bytes(&f, 8)
                    .map_err(|e| e.to_string())?
                    .unwrap_or(&[]);
                self.admit_manifest(manifest_bytes)?;
                let seq = scalar_varint(&f, 16)
                    .map_err(|e| e.to_string())?
                    .unwrap_or(0) as u32;
                self.max_creation_sequence = self.max_creation_sequence.max(seq);
                let savegame = scalar_bytes(&f, 17)
                    .map_err(|e| e.to_string())?
                    .map(|b| !b.is_empty())
                    .unwrap_or(false);
                self.spawn_groups.insert(
                    handle,
                    SpawnGroup {
                        flags: scalar_varint(&f, 9)
                            .map_err(|e| e.to_string())?
                            .unwrap_or(0) as u32,
                        owner: scalar_varint(&f, 5)
                            .map_err(|e| e.to_string())?
                            .unwrap_or(0) as u32,
                        parent: scalar_varint(&f, 18)
                            .map_err(|e| e.to_string())?
                            .unwrap_or(0) as u32,
                        savegame,
                        manifest_incomplete: scalar_varint(&f, 11)
                            .map_err(|e| e.to_string())?
                            .unwrap_or(0)
                            != 0,
                        fragment_count: 1,
                    },
                );
            }
            9 => {
                let Some(handle) = scalar_varint(&f, 1).map_err(|e| e.to_string())? else {
                    return Ok(());
                };
                let handle = handle as u32;
                let Some(incomplete) = self
                    .spawn_groups
                    .get(&handle)
                    .map(|g| g.manifest_incomplete)
                else {
                    return Ok(());
                };
                if !incomplete {
                    return Ok(());
                }
                if self.spawn_groups[&handle].fragment_count >= 1024 {
                    return Err("spawn-group-fragment-budget".into());
                }
                let frag = scalar_bytes(&f, 2)
                    .map_err(|e| e.to_string())?
                    .unwrap_or(&[]);
                self.admit_manifest(frag)?;
                let next_incomplete = scalar_varint(&f, 3)
                    .map_err(|e| e.to_string())?
                    .unwrap_or(0)
                    != 0;
                if let Some(g) = self.spawn_groups.get_mut(&handle) {
                    g.fragment_count += 1;
                    g.manifest_incomplete = next_incomplete;
                }
            }
            11 => {
                let seq = scalar_varint(&f, 3)
                    .map_err(|e| e.to_string())?
                    .unwrap_or(0) as u32;
                self.max_creation_sequence = self.max_creation_sequence.max(seq);
            }
            12 => {
                if let Some(handle) = scalar_varint(&f, 1).map_err(|e| e.to_string())? {
                    let h = handle as u32;
                    self.spawn_groups.remove(&h);
                    self.ready_spawn_groups.remove(&h);
                }
            }
            40 => {
                let count = scalar_varint(&f, 2)
                    .map_err(|e| e.to_string())?
                    .ok_or_else(|| "live-serverinfo-required-field".to_string())?
                    as u32;
                let protocol = scalar_varint(&f, 1)
                    .map_err(|e| e.to_string())?
                    .ok_or_else(|| "live-serverinfo-required-field".to_string())?
                    as u32;
                let interval_bytes = scalar_fixed32(&f, 13)
                    .map_err(|e| e.to_string())?
                    .ok_or_else(|| "live-serverinfo-required-field".to_string())?;
                let interval = f32::from_le_bytes(interval_bytes);
                if !interval.is_finite() || interval <= 0.0 || interval > 1.0 {
                    return Err("live-tick-interval".into());
                }
                let map_bytes = scalar_bytes(&f, 15)
                    .map_err(|e| e.to_string())?
                    .ok_or_else(|| "live-text-boundary".to_string())?;
                if map_bytes.is_empty() || map_bytes.len() > 256 || map_bytes.contains(&0) {
                    return Err("live-text-boundary".into());
                }
                let map = std::str::from_utf8(map_bytes)
                    .map_err(|_| "live-text-encoding".to_string())?
                    .to_string();
                let player_slot = scalar_varint(&f, 12)
                    .map_err(|e| e.to_string())?
                    .map(|v| (v as u32) as i32)
                    .unwrap_or(-1);
                let info = ControlServerInfo {
                    server_count: count,
                    protocol,
                    map,
                    tick_interval: interval,
                    player_slot,
                };
                if let Some(ref prev) = self.server {
                    if *prev != info {
                        return Err("live-serverinfo-changed-new-instance-required".into());
                    }
                } else {
                    let manifest = scalar_bytes(&f, 20)
                        .map_err(|e| e.to_string())?
                        .unwrap_or(&[]);
                    self.admit_manifest(manifest)?;
                    self.session_manifest_loaded = true;
                }
                self.server = Some(info);
            }
            51 => {
                self.reset_world();
            }
            _ => {}
        }
        Ok(())
    }
}
