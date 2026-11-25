use std::collections::HashSet;

use crate::wire::bits::BitReader;
use crate::wire::compression::snappy_decompress;
use crate::wire::proto::{CSvcMsgCreateStringTable, CSvcMsgUpdateStringTable};

const MAXIMUM_ENTRY_BYTES: usize = 0x138800;

#[derive(Debug, Clone)]
pub struct StringTableEntry {
    pub key: Vec<u8>,
    pub value: Vec<u8>,
    pub revision: u64,
}

#[derive(Debug, Clone)]
pub struct StringTable {
    pub name: String,
    pub fixed: bool,
    pub size: usize,
    pub bits: usize,
    pub flags: i32,
    pub varint: bool,
    pub entries: Vec<StringTableEntry>,
    pub revision: u64,
}

impl StringTable {
    fn total_bytes(&self) -> usize {
        self.entries
            .iter()
            .map(|e| e.key.len() + e.value.len())
            .sum()
    }
}

#[derive(Debug, Default)]
pub struct StringTables {
    tables: Vec<StringTable>,
    pub revision: u64,
    retained_bytes: usize,
    instance_baseline_id: Option<usize>,
    userinfo_id: Option<usize>,
}

impl StringTables {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn count(&self) -> usize {
        self.tables.len()
    }

    pub fn clear(&mut self) {
        self.tables.clear();
        self.retained_bytes = 0;
        self.instance_baseline_id = None;
        self.userinfo_id = None;
        self.revision += 1;
    }

    pub fn instance_baseline_revision(&self) -> u64 {
        self.instance_baseline_id
            .and_then(|id| self.tables.get(id))
            .map(|t| t.revision)
            .unwrap_or(0)
    }

    pub fn class_baseline(&self, class_id: usize) -> Option<&[u8]> {
        let id = self.instance_baseline_id?;
        let table = self.tables.get(id)?;
        let key_str = class_id.to_string();
        let key_bytes = key_str.as_bytes();
        table
            .entries
            .iter()
            .find(|e| e.key.as_slice() == key_bytes)
            .map(|e| e.value.as_slice())
    }

    pub fn indexed_baseline(&self, index: usize) -> Option<&[u8]> {
        let id = self.instance_baseline_id?;
        self.tables
            .get(id)?
            .entries
            .get(index)
            .map(|e| e.value.as_slice())
    }

    pub fn userinfo_entry(&self, slot: usize) -> Option<&[u8]> {
        let id = self.userinfo_id?;
        self.tables
            .get(id)?
            .entries
            .get(slot)
            .map(|e| e.value.as_slice())
    }

    pub fn create(&mut self, msg: &CSvcMsgCreateStringTable) -> Result<usize, String> {
        let name = msg.name.as_deref().unwrap_or("");
        if self.tables.len() >= 1024
            || name.is_empty()
            || name.len() > 1024
            || self.tables.iter().any(|t| t.name == name)
        {
            return Err("Invalid string table name/count".into());
        }
        let fixed = msg.user_data_fixed_size == Some(true);
        let size = msg.user_data_size.unwrap_or(0);
        let bits = msg.user_data_size_bits.unwrap_or(0);
        if size < 0
            || (size as usize) > MAXIMUM_ENTRY_BYTES
            || bits < 0
            || (fixed && (bits as usize) > (size as usize) * 8)
        {
            return Err("Invalid fixed string table size".into());
        }
        let raw_data = msg.string_data.as_deref().unwrap_or(&[]);
        if raw_data.len() > 32 * 1024 * 1024 {
            return Err("String table input budget".into());
        }
        let owned_data;
        let data = if msg.data_compressed == Some(true) {
            let cap = msg.uncompressed_size.map(|v| v.max(0) as usize);
            owned_data = snappy_decompress(raw_data, cap).map_err(|e| e.to_string())?;
            owned_data.as_slice()
        } else {
            raw_data
        };

        let mut table = StringTable {
            name: name.to_string(),
            fixed,
            size: size as usize,
            bits: bits as usize,
            flags: msg.flags.unwrap_or(0),
            varint: msg.using_varint_bitcounts == Some(true),
            entries: Vec::new(),
            revision: self.revision + 1,
        };
        let num_entries = msg.num_entries.unwrap_or(0);
        if num_entries < 0 {
            return Err("String table entry count budget".into());
        }
        Self::parse_into(&mut table, data, num_entries as usize, self.revision + 1)?;
        let table_bytes = table.total_bytes();
        let retained = self.retained_bytes + table_bytes;
        if retained > 128 * 1024 * 1024 {
            return Err("Global string table budget".into());
        }
        self.retained_bytes = retained;
        let id = self.tables.len();
        if table.name == "instancebaseline" {
            self.instance_baseline_id = Some(id);
        } else if table.name == "userinfo" {
            self.userinfo_id = Some(id);
        }
        self.tables.push(table);
        self.revision += 1;
        Ok(id)
    }

    pub fn update(&mut self, msg: &CSvcMsgUpdateStringTable) -> Result<(), String> {
        let id = msg
            .table_id
            .filter(|&v| v >= 0)
            .map(|v| v as usize)
            .filter(|&v| v < self.tables.len())
            .ok_or_else(|| "Unknown string table ID".to_string())?;
        let data = msg.string_data.as_deref().unwrap_or(&[]);
        if data.len() > 32 * 1024 * 1024 {
            return Err("String table input budget".into());
        }
        let count = msg.num_changed_entries.unwrap_or(0);
        if count < 0 {
            return Err("String table entry count budget".into());
        }
        let mut next = self.tables[id].clone();
        let old_bytes = self.tables[id].total_bytes();
        let next_rev = self.revision + 1;
        Self::parse_into(&mut next, data, count as usize, next_rev)?;
        next.revision = next_rev;
        let new_bytes = next.total_bytes();
        let retained = self.retained_bytes - old_bytes + new_bytes;
        if retained > 128 * 1024 * 1024 {
            return Err("Global string table budget".into());
        }
        self.tables[id] = next;
        self.retained_bytes = retained;
        self.revision = next_rev;
        Ok(())
    }

    fn parse_into(
        table: &mut StringTable,
        data: &[u8],
        count: usize,
        entry_rev: u64,
    ) -> Result<(), String> {
        if count > 65536 {
            return Err("String table entry count budget".into());
        }
        let mut reader = BitReader::new(data).map_err(|e| e.to_string())?;
        let mut history: Vec<Vec<u8>> = Vec::with_capacity(32);
        let mut names: HashSet<Vec<u8>> = table.entries.iter().map(|e| e.key.clone()).collect();
        let mut index: i64 = -1;
        let mut total = table.total_bytes();

        for _ in 0..count {
            let incr = if reader.read_bool().map_err(|e| e.to_string())? {
                1i64
            } else {
                reader.read_varuint32().map_err(|e| e.to_string())? as i64 + 2
            };
            index += incr;
            if !(0..65536).contains(&index) {
                return Err("String table entry index budget".into());
            }
            let idx = index as usize;

            let supplied = if reader.read_bool().map_err(|e| e.to_string())? {
                if reader.read_bool().map_err(|e| e.to_string())? {
                    let position = reader.read_bits(5).map_err(|e| e.to_string())? as usize;
                    let length = reader.read_bits(5).map_err(|e| e.to_string())? as usize;
                    let prefix = history
                        .get(position)
                        .ok_or_else(|| "Invalid table key history".to_string())?;
                    if length > prefix.len() {
                        return Err("Invalid table key history".into());
                    }
                    let suffix = reader.read_string_nul(4096).map_err(|e| e.to_string())?;
                    let mut buf = Vec::with_capacity(length + suffix.len());
                    buf.extend_from_slice(&prefix[..length]);
                    buf.extend_from_slice(&suffix);
                    Some(buf)
                } else {
                    Some(reader.read_string_nul(4096).map_err(|e| e.to_string())?)
                }
            } else {
                None
            };

            let is_new = idx >= table.entries.len();
            let key = if !is_new {
                table.entries[idx].key.clone()
            } else {
                let k = supplied.ok_or_else(|| "New string table entry lacks key".to_string())?;
                if idx != table.entries.len() {
                    return Err("Noncontiguous new string table entry".into());
                }
                if !names.insert(k.clone()) {
                    return Err("Duplicate new string table key".into());
                }
                k
            };

            let mut value = Vec::new();
            if reader.read_bool().map_err(|e| e.to_string())? {
                let mut bit_count = table.bits;
                let mut compressed = false;
                if !table.fixed {
                    if (table.flags & 1) != 0 {
                        compressed = reader.read_bool().map_err(|e| e.to_string())?;
                    }
                    let bytes = if table.varint {
                        reader.read_ubitvar().map_err(|e| e.to_string())? as usize
                    } else {
                        reader.read_bits(17).map_err(|e| e.to_string())? as usize
                    };
                    if bytes > MAXIMUM_ENTRY_BYTES {
                        return Err("String table value budget".into());
                    }
                    bit_count = bytes * 8;
                }
                if bit_count > reader.remaining_bits() {
                    return Err("Truncated string table value".into());
                }
                let alloc_bytes = if table.fixed {
                    table.size
                } else {
                    bit_count / 8
                };
                value = vec![0u8; alloc_bytes];
                let whole = bit_count >> 3;
                for slot in value.iter_mut().take(whole) {
                    *slot = reader.read_bits(8).map_err(|e| e.to_string())? as u8;
                }
                if (bit_count & 7) != 0 {
                    value[whole] = reader
                        .read_bits((bit_count & 7) as u8)
                        .map_err(|e| e.to_string())? as u8;
                }
                if compressed {
                    value = snappy_decompress(&value, Some(MAXIMUM_ENTRY_BYTES))
                        .map_err(|e| e.to_string())?;
                }
            }

            let old_len = if is_new {
                0
            } else {
                table.entries[idx].key.len() + table.entries[idx].value.len()
            };
            total = total + key.len() + value.len() - old_len;
            if total > 64 * 1024 * 1024 {
                return Err("Retained string table byte budget".into());
            }

            let hist_key = key[..key.len().min(31)].to_vec();
            let entry = StringTableEntry {
                key,
                value,
                revision: entry_rev,
            };
            if is_new {
                table.entries.push(entry);
            } else {
                table.entries[idx] = entry;
            }
            history.push(hist_key);
            if history.len() > 32 {
                history.remove(0);
            }
        }
        Ok(())
    }
}
