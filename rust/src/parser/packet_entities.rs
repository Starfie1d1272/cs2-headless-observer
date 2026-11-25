use std::collections::HashMap;
use std::sync::Arc;

use super::entity_fields::EntityFields;
use super::schema::Schema;
use super::string_tables::StringTables;
use crate::wire::bits::BitReader;
use crate::wire::proto::CSvcMsgPacketEntities;

const MAX_ENTITIES: usize = 16384;
const MAX_FRAMES: usize = 512;

#[derive(Debug, Clone)]
pub struct Entity {
    pub id: usize,
    pub class_id: usize,
    pub serial: u32,
    pub fields: EntityFields,
}

#[derive(Clone)]
struct EntityBitSet([u64; MAX_ENTITIES / 64]);

impl EntityBitSet {
    #[inline]
    fn empty() -> Self {
        Self([0u64; MAX_ENTITIES / 64])
    }
    #[inline]
    fn insert(&mut self, id: usize) {
        self.0[id >> 6] |= 1u64 << (id & 63);
    }
    #[inline]
    fn remove(&mut self, id: usize) {
        self.0[id >> 6] &= !(1u64 << (id & 63));
    }
    #[inline]
    fn contains(&self, id: usize) -> bool {
        (self.0[id >> 6] & (1u64 << (id & 63))) != 0
    }
}

#[derive(Clone)]
struct FrameMembership {
    members: EntityBitSet,
    dormant: EntityBitSet,
    outside: EntityBitSet,
}

#[derive(Debug, Clone)]
struct BaselineEntry {
    class_id: usize,
    fields: Arc<EntityFields>,
}

#[derive(Debug, Clone, Copy)]
pub struct SnapshotReceipt {
    pub epoch: u64,
    pub tick: i32,
    pub full: bool,
    pub baseline_ack: Option<u8>,
}

#[derive(Debug, Default)]
pub struct ClassBaselineCache {
    cached_revision: u64,
    by_class: Vec<Option<Arc<EntityFields>>>,
}

impl ClassBaselineCache {
    pub fn get_or_decode(
        &mut self,
        schema: &Schema,
        tables: &StringTables,
        class_id: usize,
    ) -> Result<Arc<EntityFields>, String> {
        let rev = tables.instance_baseline_revision();
        if self.cached_revision != rev {
            self.by_class.clear();
            self.cached_revision = rev;
        }
        if self.by_class.len() <= class_id {
            self.by_class
                .resize(schema.max_classes.max(class_id + 1), None);
        }
        if let Some(cached) = &self.by_class[class_id] {
            return Ok(cached.clone());
        }
        let bytes = tables
            .class_baseline(class_id)
            .filter(|b| !b.is_empty())
            .ok_or_else(|| "Missing class baseline".to_string())?;
        let mut reader = BitReader::new(bytes).map_err(|e| e.to_string())?;
        let mut fields = EntityFields::empty(class_id);
        fields.decode_in_place(schema, &mut reader, None)?;
        let arc = Arc::new(fields);
        self.by_class[class_id] = Some(arc.clone());
        Ok(arc)
    }

    pub fn clear(&mut self) {
        self.by_class.clear();
        self.cached_revision = 0;
    }
}

pub struct EntityTable {
    entities: Vec<Option<Entity>>,
    frames: HashMap<i32, FrameMembership>,
    frame_order: Vec<i32>,
    banks: [HashMap<usize, BaselineEntry>; 2],
    class_baselines: ClassBaselineCache,
    game_rules_id: Option<usize>,
    pub latest_tick: Option<i32>,
    pub epoch: u64,
    pub waiting_full: bool,
}

impl Default for EntityTable {
    fn default() -> Self {
        Self::new()
    }
}

impl EntityTable {
    pub fn new() -> Self {
        Self {
            entities: vec![None; MAX_ENTITIES],
            frames: HashMap::new(),
            frame_order: Vec::new(),
            banks: [HashMap::new(), HashMap::new()],
            class_baselines: ClassBaselineCache::default(),
            game_rules_id: None,
            latest_tick: None,
            epoch: 0,
            waiting_full: true,
        }
    }

    pub fn get(&self, id: usize) -> Option<&Entity> {
        self.entities.get(id).and_then(|o| o.as_ref())
    }

    pub fn game_rules(&mut self, schema: &Schema) -> Option<&Entity> {
        if self.waiting_full {
            return None;
        }
        if let Some(id) = self.game_rules_id {
            if let Some(ent) = self.entities.get(id).and_then(|o| o.as_ref()) {
                if schema
                    .get_class(ent.class_id)
                    .map(|c| c.name == "CCSGameRulesProxy")
                    .unwrap_or(false)
                {
                    return self.entities[id].as_ref();
                }
            }
            self.game_rules_id = None;
        }
        let found = self
            .entities
            .iter()
            .filter_map(|o| o.as_ref())
            .find(|e| {
                schema
                    .get_class(e.class_id)
                    .map(|c| c.name == "CCSGameRulesProxy")
                    .unwrap_or(false)
            })
            .map(|e| e.id);
        self.game_rules_id = found;
        found.and_then(|id| self.entities[id].as_ref())
    }

    /// Clear entities on decode failure so a partially mutated packet cannot
    /// pollute future FULL snapshots.
    pub fn recover(&mut self) {
        self.epoch += 1;
        self.latest_tick = None;
        self.waiting_full = true;
        self.game_rules_id = None;
        self.entities.fill(None);
        self.frames.clear();
        self.frame_order.clear();
        self.banks[0].clear();
        self.banks[1].clear();
    }

    pub fn reset(&mut self) {
        self.recover();
        self.class_baselines.clear();
    }

    pub fn decode_packet(
        &mut self,
        schema: &Schema,
        tables: &StringTables,
        msg: &CSvcMsgPacketEntities,
        receive_tick: i32,
    ) -> Result<Option<SnapshotReceipt>, String> {
        let count = msg.updated_entries.unwrap_or(0);
        if count < 0 || (count as usize) > MAX_ENTITIES {
            return Err("Invalid entity update count".into());
        }
        let server_tick = msg
            .server_tick
            .ok_or_else(|| "Missing explicit server tick".to_string())?;
        if receive_tick < 1 || (server_tick as i64) != (receive_tick as i64) {
            return Err("Invalid snapshot receive tick".into());
        }
        let bank_idx = msg.baseline.unwrap_or(0);
        if bank_idx != 0 && bank_idx != 1 {
            return Err("Invalid baseline bank".into());
        }
        let bank = bank_idx as usize;
        let update_baseline = msg.update_baseline == Some(true);
        let delta_from = msg.delta_from;
        let is_delta = delta_from.is_some();

        if let Some(df) = delta_from {
            if df >= receive_tick {
                return Err("Invalid delta reference".into());
            }
        }
        if is_delta && self.waiting_full {
            return Ok(None);
        }
        if is_delta {
            if let Some(latest) = self.latest_tick {
                if receive_tick <= latest {
                    return Err("Nonadvancing forward delta snapshot".into());
                }
            }
        }

        let mut frame_state = if let Some(df) = delta_from {
            let src = self
                .frames
                .get(&df)
                .ok_or_else(|| format!("Missing snapshot {df} for {receive_tick}"))?;
            FrameMembership {
                members: src.members.clone(),
                dormant: src.dormant.clone(),
                outside: EntityBitSet::empty(),
            }
        } else {
            FrameMembership {
                members: EntityBitSet::empty(),
                dormant: EntityBitSet::empty(),
                outside: EntityBitSet::empty(),
            }
        };

        let restart = !is_delta && self.latest_tick.map(|l| l > receive_tick).unwrap_or(false);
        if !is_delta {
            self.banks[0].clear();
            self.banks[1].clear();
        }
        let mut next_bank = if update_baseline {
            Some(self.banks[bank].clone())
        } else {
            None
        };

        let mut lengths = Vec::new();
        if let Some(se) = &msg.serialized_entities {
            if !se.is_empty() {
                let mut idx_reader = BitReader::new(se).map_err(|e| e.to_string())?;
                while idx_reader.remaining_bits() > 0 {
                    if lengths.len() >= 32768 {
                        return Err("Entity field length count budget".into());
                    }
                    lengths.push(idx_reader.read_varuint32().map_err(|e| e.to_string())? as usize);
                }
            }
        }

        let mut overrides: HashMap<usize, usize> = HashMap::new();
        for entry in &msg.alternate_baselines {
            let id = entry
                .entity_index
                .filter(|&v| v >= 0 && (v as usize) < MAX_ENTITIES)
                .ok_or_else(|| "Invalid alternate baseline".to_string())?
                as usize;
            let bidx = entry
                .baseline_index
                .filter(|&v| (0..65536).contains(&v))
                .ok_or_else(|| "Invalid alternate baseline".to_string())?
                as usize;
            if overrides.insert(id, bidx).is_some() {
                return Err("Invalid alternate baseline".into());
            }
        }

        let mut length_idx = 0usize;
        let entity_data = msg.entity_data.as_deref().unwrap_or(&[]);
        let mut reader = BitReader::new(entity_data).map_err(|e| e.to_string())?;

        let advance_id = |r: &mut BitReader<'_>, cur: i32| -> Result<usize, String> {
            let step = r.read_ubitvar().map_err(|e| e.to_string())? as i32;
            let next = cur + 1 + step;
            if next < 0 || (next as usize) >= MAX_ENTITIES {
                return Err("Invalid entity index".into());
            }
            Ok(next as usize)
        };

        let mut id: i32 = -1;
        for _ in 0..count {
            let next_id = advance_id(&mut reader, id)?;
            id = next_id as i32;
            let op_type = reader.read_bits(2).map_err(|e| e.to_string())?;
            if (op_type & 1) != 0 {
                frame_state.members.remove(next_id);
                frame_state.dormant.remove(next_id);
                if op_type == 3 {
                    self.entities[next_id] = None;
                    if self.game_rules_id == Some(next_id) {
                        self.game_rules_id = None;
                    }
                }
            } else if op_type == 2 {
                let blen = take_bit_length(&lengths, &mut length_idx)?;
                self.create_entity_at(
                    schema,
                    tables,
                    bank,
                    next_bank.as_mut(),
                    &mut reader,
                    next_id,
                    blen,
                    &mut frame_state,
                )?;
            } else {
                let blen = take_bit_length(&lengths, &mut length_idx)?;
                self.update_entity_at(
                    schema,
                    tables,
                    &overrides,
                    &mut reader,
                    next_id,
                    blen,
                    &mut frame_state,
                )?;
            }
        }

        if let Some(ref outside) = msg.outofpvs_entity_updates {
            let n = outside.count.unwrap_or(0);
            if n < 0 || (n as usize) > MAX_ENTITIES {
                return Err("Invalid out-of-PVS count".into());
            }
            let mut out_reader = BitReader::new(outside.data.as_deref().unwrap_or(&[]))
                .map_err(|e| e.to_string())?;
            let mut oid: i32 = -1;
            for _ in 0..n {
                let next_id = advance_id(&mut out_reader, oid)?;
                oid = next_id as i32;
                let is_create = out_reader.read_bool().map_err(|e| e.to_string())?;
                let blen = take_bit_length(&lengths, &mut length_idx)?;
                if is_create {
                    self.create_entity_at(
                        schema,
                        tables,
                        bank,
                        next_bank.as_mut(),
                        &mut out_reader,
                        next_id,
                        blen,
                        &mut frame_state,
                    )?;
                } else {
                    self.update_entity_at(
                        schema,
                        tables,
                        &overrides,
                        &mut out_reader,
                        next_id,
                        blen,
                        &mut frame_state,
                    )?;
                }
                frame_state.outside.insert(next_id);
            }
        }

        if let Some(ref dormant) = msg.non_transmitted_entities {
            let n = dormant.header_count.unwrap_or(0);
            if n < 0 || (n as usize) > MAX_ENTITIES {
                return Err("Invalid non-transmitted count".into());
            }
            let mut d_reader = BitReader::new(dormant.data.as_deref().unwrap_or(&[]))
                .map_err(|e| e.to_string())?;
            let mut did: i32 = -1;
            for _ in 0..n {
                let next_id = advance_id(&mut d_reader, did)?;
                did = next_id as i32;
                let is_dormant = d_reader.read_bool().map_err(|e| e.to_string())?;
                if is_dormant {
                    frame_state.dormant.insert(next_id);
                } else {
                    frame_state.dormant.remove(next_id);
                }
            }
            for (idx, slot) in self.entities.iter_mut().enumerate().take(MAX_ENTITIES) {
                if slot.is_some()
                    && !frame_state.members.contains(idx)
                    && !frame_state.dormant.contains(idx)
                    && !frame_state.outside.contains(idx)
                {
                    *slot = None;
                    if self.game_rules_id == Some(idx) {
                        self.game_rules_id = None;
                    }
                }
            }
        } else if is_delta {
            let n = reader.read_ubitvar().map_err(|e| e.to_string())?;
            if (n as usize) > MAX_ENTITIES {
                return Err("Invalid trailing delete count".into());
            }
            let mut tid: i32 = -1;
            for _ in 0..n {
                let step = reader.read_ubitvar().map_err(|e| e.to_string())? as i32;
                if step == 0 || tid + step >= (MAX_ENTITIES as i32) {
                    return Err("Invalid trailing delete index".into());
                }
                tid += step;
                let uid = tid as usize;
                frame_state.members.remove(uid);
                frame_state.dormant.remove(uid);
                self.entities[uid] = None;
                if self.game_rules_id == Some(uid) {
                    self.game_rules_id = None;
                }
            }
        }

        if length_idx != lengths.len() {
            return Err("Unused entity field lengths".into());
        }

        if restart {
            self.epoch += 1;
            self.frames.clear();
            self.frame_order.clear();
        }
        if let Some(df) = delta_from {
            self.frames.retain(|&t, _| t >= df);
            self.frame_order.retain(|&t| t >= df);
        }
        self.frames.insert(receive_tick, frame_state);
        self.frame_order.push(receive_tick);
        while self.frames.len() > MAX_FRAMES {
            if let Some(pos) = self
                .frame_order
                .iter()
                .position(|&t| t != receive_tick && delta_from.map(|df| t != df).unwrap_or(true))
            {
                let old = self.frame_order.remove(pos);
                self.frames.remove(&old);
            } else {
                break;
            }
        }
        if let Some(nb) = next_bank {
            self.banks[if bank == 0 { 1 } else { 0 }] = nb;
        }
        self.latest_tick = Some(receive_tick);
        self.waiting_full = false;

        Ok(Some(SnapshotReceipt {
            epoch: self.epoch,
            tick: receive_tick,
            full: !is_delta,
            baseline_ack: if update_baseline {
                Some(bank as u8)
            } else {
                None
            },
        }))
    }

    #[allow(clippy::too_many_arguments)]
    fn create_entity_at(
        &mut self,
        schema: &Schema,
        tables: &StringTables,
        bank: usize,
        next_bank: Option<&mut HashMap<usize, BaselineEntry>>,
        r: &mut BitReader<'_>,
        id: usize,
        blen: Option<usize>,
        fs: &mut FrameMembership,
    ) -> Result<(), String> {
        let class_id = r
            .read_bits(schema.class_id_bits)
            .map_err(|e| e.to_string())? as usize;
        let serial = r.read_bits(17).map_err(|e| e.to_string())?;
        let _token = r.read_varuint32().map_err(|e| e.to_string())?;
        let cls = schema.get_class(class_id)?;
        if cls.name == "CCSGameRulesProxy" {
            self.game_rules_id = Some(id);
        }

        let reuse_old = match &self.entities[id] {
            Some(old) if old.class_id == class_id && old.serial == serial => {
                Some(old.fields.clone())
            }
            _ => None,
        };

        let base: Arc<EntityFields> = match self.banks[bank].get(&id) {
            Some(entry) if entry.class_id == class_id => entry.fields.clone(),
            _ => self
                .class_baselines
                .get_or_decode(schema, tables, class_id)?,
        };

        let target = if let Some(nb) = next_bank {
            let mut merged = (*base).clone();
            merged.decode_in_place(schema, r, blen)?;
            let mut out = if let Some(old_fields) = reuse_old {
                let mut t = old_fields;
                merged.apply_to(schema, &mut t)?;
                t
            } else {
                merged.clone()
            };
            nb.insert(
                id,
                BaselineEntry {
                    class_id,
                    fields: Arc::new(merged),
                },
            );
            let _ = &mut out;
            out
        } else if let Some(mut old_fields) = reuse_old {
            base.apply_to(schema, &mut old_fields)?;
            old_fields.decode_in_place(schema, r, blen)?;
            old_fields
        } else {
            let mut fresh = (*base).clone();
            fresh.decode_in_place(schema, r, blen)?;
            fresh
        };

        self.entities[id] = Some(Entity {
            id,
            class_id,
            serial,
            fields: target,
        });
        fs.members.insert(id);
        fs.dormant.remove(id);
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn update_entity_at(
        &mut self,
        schema: &Schema,
        tables: &StringTables,
        overrides: &HashMap<usize, usize>,
        r: &mut BitReader<'_>,
        id: usize,
        blen: Option<usize>,
        fs: &mut FrameMembership,
    ) -> Result<(), String> {
        let ent = self.entities[id]
            .as_mut()
            .ok_or_else(|| "Update of unknown entity".to_string())?;
        if let Some(&alt_idx) = overrides.get(&id) {
            let alt_bytes = tables
                .indexed_baseline(alt_idx)
                .filter(|b| !b.is_empty())
                .ok_or_else(|| "Missing alternate baseline".to_string())?;
            let mut alt_reader = BitReader::new(alt_bytes).map_err(|e| e.to_string())?;
            let mut alt_fields = EntityFields::empty(ent.class_id);
            alt_fields.decode_in_place(schema, &mut alt_reader, None)?;
            alt_fields.apply_to(schema, &mut ent.fields)?;
        }
        ent.fields.decode_in_place(schema, r, blen)?;
        fs.members.insert(id);
        fs.dormant.remove(id);
        Ok(())
    }
}

fn take_bit_length(lengths: &[usize], idx: &mut usize) -> Result<Option<usize>, String> {
    if lengths.is_empty() {
        return Ok(None);
    }
    if *idx >= lengths.len() {
        return Err("Missing entity field length".into());
    }
    let l = lengths[*idx];
    *idx += 1;
    Ok(Some(l))
}
