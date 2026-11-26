use std::collections::{BTreeMap, HashMap, HashSet};

use prost::Message;
use serde::Serialize;
use serde_json::Value;

use super::packet_entities::EntityTable;
use super::projection::{project_native_event, project_round_clock, PlayerIdentity, RoundClock};
use super::schema::Schema;
use super::string_tables::StringTables;
use crate::wire::bits::{scalar_bytes, scalar_varint, wire_fields, BitReader, MAX_BYTES};
use crate::wire::compression::expand_lzss;
use crate::wire::proto::{
    CMsgSource1LegacyGameEvent, CMsgSource1LegacyGameEventList, CNetMsgTick, CSvcMsgClassInfo,
    CSvcMsgCreateStringTable, CSvcMsgFlattenedSerializer, CSvcMsgPacketEntities, CSvcMsgServerInfo,
    CSvcMsgUpdateStringTable, GameEventDescriptor,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceIdentity {
    pub channel: u64,
    pub world: u64,
}

#[derive(Debug, Clone)]
pub struct ServerInfoState {
    pub protocol: i32,
    pub server_count: u32,
    pub max_classes: usize,
    pub player_slot: i32,
    pub tick_interval: f32,
    pub map_name: String,
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

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CursorRecord {
    pub kind: &'static str,
    pub channel: u64,
    pub world: u64,
    pub sequence: u64,
    pub committed_tick: i32,
    pub tick_interval: f32,
    pub map: String,
    pub warmup: Option<bool>,
    pub round: Option<u32>,
    pub round_clock: RoundClock,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RawEventRecord {
    pub kind: &'static str,
    pub name: String,
    pub channel: u64,
    pub world: u64,
    pub sequence: u64,
    pub event_tick: i32,
    pub committed_tick: Option<i32>,
    pub tick_interval: Option<f32>,
    pub map: Option<String>,
    pub warmup: Option<bool>,
    pub round: Option<u32>,
    pub residence_us: Option<u64>,
    #[serde(skip)]
    pub sdk_queue_age_us: Option<i64>,
    #[serde(skip)]
    pub dequeue_ns: Option<u64>,
    pub fields: BTreeMap<String, Value>,
    pub players: BTreeMap<String, Option<PlayerIdentity>>,
}

#[derive(Debug, Clone)]
pub enum CoreOutput {
    Receipt {
        tick: i32,
        full: bool,
        baseline_ack: Option<u8>,
        epoch: u64,
    },
    Cursor(CursorRecord),
    RawEvent(RawEventRecord),
    EventSubscriptions {
        descriptor_generation: u64,
        ids: Vec<i32>,
        player_slot: Option<i32>,
    },
    Gap {
        reason: String,
    },
    Recovery {
        reason: String,
        snapshot_epoch: u64,
        world_reinitialization: bool,
    },
    WorldReset {
        reason: String,
    },
    Diagnostic {
        reason: String,
        event_id: Option<i32>,
    },
    Blocked {
        reason: String,
    },
}

fn read_manifest_string(r: &mut BitReader<'_>) -> Result<String, String> {
    let bytes = r.read_string_nul(4096).map_err(|e| e.to_string())?;
    String::from_utf8(bytes).map_err(|_| "manifest-string-encoding".to_string())
}

fn decode_resource_manifest_stats(data: &[u8]) -> Result<(usize, usize), String> {
    if data.len() > 128 * 1024 {
        return Err("manifest-wire-budget".into());
    }
    if data.is_empty() {
        return Ok((0, 0));
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
    let mut name_bytes = 0usize;
    for _ in 0..ext_count {
        name_bytes += read_manifest_string(&mut r)?.len();
    }
    for _ in 0..dir_count {
        name_bytes += read_manifest_string(&mut r)?.len();
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
    for _ in 0..res_count {
        let d = r.read_bits(dir_bits).map_err(|e| e.to_string())? as usize;
        let name = read_manifest_string(&mut r)?;
        let e = r.read_bits(ext_bits).map_err(|e| e.to_string())? as usize;
        if d >= dir_count || e >= ext_count {
            return Err("manifest-symbol-index".into());
        }
        name_bytes += name.len();
    }
    if r.remaining_bits() >= 8 {
        return Err("manifest-payload-trailing-bytes".into());
    }
    Ok((name_bytes, res_count))
}

pub struct ObserverCore {
    pub identity: SourceIdentity,
    pub network_tick: i32,
    last_cursor: Option<i32>,
    pub tables: StringTables,
    pub entities: EntityTable,
    pub server: Option<ServerInfoState>,
    serializers: Option<CSvcMsgFlattenedSerializer>,
    classes: Option<CSvcMsgClassInfo>,
    pub schema: Option<Schema>,
    descriptors: HashMap<i32, GameEventDescriptor>,
    pub descriptor_generation: u64,
    pub known_creation_sequence: u32,
    pub spawn_groups: BTreeMap<u32, SpawnGroup>,
    pub ready_spawn_groups: HashSet<u32>,
    manifest_name_bytes: usize,
    manifest_resources: usize,
    pub halted: bool,
}

impl ObserverCore {
    pub fn new(identity: SourceIdentity) -> Self {
        Self {
            identity,
            network_tick: -1,
            last_cursor: None,
            tables: StringTables::new(),
            entities: EntityTable::new(),
            server: None,
            serializers: None,
            classes: None,
            schema: None,
            descriptors: HashMap::new(),
            descriptor_generation: 0,
            known_creation_sequence: 0,
            spawn_groups: BTreeMap::new(),
            ready_spawn_groups: HashSet::new(),
            manifest_name_bytes: 0,
            manifest_resources: 0,
            halted: false,
        }
    }

    pub fn ready(&self) -> bool {
        !self.halted && self.schema.is_some() && self.server.is_some()
    }

    pub fn class_count(&self) -> usize {
        self.classes.as_ref().map(|c| c.classes.len()).unwrap_or(0)
    }

    pub fn committed_tick(&self) -> Option<i32> {
        self.entities.latest_tick
    }

    pub fn admit_creation_sequence(&mut self, seq: u32) {
        self.known_creation_sequence = self.known_creation_sequence.max(seq);
    }

    fn admit_manifest(&mut self, payload: &[u8]) -> Result<(), String> {
        let (names, count) = decode_resource_manifest_stats(payload)?;
        if self.manifest_name_bytes + names > MAX_BYTES || self.manifest_resources + count > 16384 {
            return Err("spawn-group-session-manifest-budget".into());
        }
        self.manifest_name_bytes += names;
        self.manifest_resources += count;
        Ok(())
    }

    pub fn ready_world_groups(&mut self) -> Result<Vec<u32>, String> {
        if self.server.is_none() {
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

    pub fn reset_world(&mut self, next_world: u64) {
        self.identity.world = next_world;
        self.network_tick = -1;
        self.last_cursor = None;
        self.tables.clear();
        self.entities.reset();
        self.server = None;
        self.serializers = None;
        self.classes = None;
        self.schema = None;
        self.descriptors.clear();
        self.descriptor_generation += 1;
        self.known_creation_sequence = 0;
        self.spawn_groups.clear();
        self.ready_spawn_groups.clear();
        self.manifest_name_bytes = 0;
        self.manifest_resources = 0;
        self.halted = false;
    }

    fn try_build_schema(&mut self) -> Result<(), String> {
        if self.schema.is_some() {
            return Ok(());
        }
        let (Some(srv), Some(ser), Some(cls)) = (&self.server, &self.serializers, &self.classes)
        else {
            return Ok(());
        };
        if cls.classes.is_empty() {
            return Err("ClassInfo index exceeds announced class count".into());
        }
        let mut class_list = Vec::with_capacity(cls.classes.len());
        for c in &cls.classes {
            let cid = c
                .class_id
                .ok_or_else(|| "ClassInfo index exceeds announced class count".to_string())?;
            if cid < 0 || (cid as usize) >= cls.classes.len() {
                return Err("ClassInfo index exceeds announced class count".into());
            }
            let cname = c.class_name.clone().unwrap_or_default();
            class_list.push((cid, cname));
        }
        let schema = Schema::build(ser, &class_list, srv.max_classes)?;
        self.schema = Some(schema);
        Ok(())
    }

    pub fn consume(
        &mut self,
        message_id: u32,
        body: &[u8],
        context_tick: Option<i32>,
        sdk_queue_age_us: Option<i64>,
    ) -> Vec<CoreOutput> {
        let mut out = Vec::new();
        if self.halted && message_id != 51 {
            out.push(CoreOutput::Blocked {
                reason: "world-reinitialization-required".into(),
            });
            return out;
        }
        let res = self.consume_inner(message_id, body, context_tick, sdk_queue_age_us, &mut out);
        if let Err(reason) = res {
            if message_id == 207 {
                out.push(CoreOutput::Gap { reason });
            } else {
                self.entities.recover();
                self.last_cursor = None;
                if message_id != 55 {
                    self.halted = true;
                }
                out.push(CoreOutput::Recovery {
                    reason,
                    snapshot_epoch: self.entities.epoch,
                    world_reinitialization: self.halted,
                });
            }
        }
        out
    }

    fn consume_inner(
        &mut self,
        message_id: u32,
        body: &[u8],
        context_tick: Option<i32>,
        sdk_queue_age_us: Option<i64>,
        out: &mut Vec<CoreOutput>,
    ) -> Result<(), String> {
        match message_id {
            4 => {
                let msg = CNetMsgTick::decode(body).map_err(|e| e.to_string())?;
                let tick = msg
                    .tick
                    .filter(|&t| t <= i32::MAX as u32)
                    .ok_or_else(|| "Invalid network clock".to_string())?;
                self.network_tick = tick as i32;
            }
            8 => {
                let f = wire_fields(body, MAX_BYTES).map_err(|e| e.to_string())?;
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
                self.admit_creation_sequence(seq);
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
                let f = wire_fields(body, MAX_BYTES).map_err(|e| e.to_string())?;
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
                let f = wire_fields(body, MAX_BYTES).map_err(|e| e.to_string())?;
                let seq = scalar_varint(&f, 3)
                    .map_err(|e| e.to_string())?
                    .unwrap_or(0) as u32;
                self.admit_creation_sequence(seq);
            }
            12 => {
                let f = wire_fields(body, MAX_BYTES).map_err(|e| e.to_string())?;
                if let Some(handle) = scalar_varint(&f, 1).map_err(|e| e.to_string())? {
                    let h = handle as u32;
                    self.spawn_groups.remove(&h);
                    self.ready_spawn_groups.remove(&h);
                }
            }
            40 => {
                let msg = CSvcMsgServerInfo::decode(body).map_err(|e| e.to_string())?;
                let interval = msg.tick_interval.unwrap_or(0.0);
                let map_name = msg.map_name.clone().unwrap_or_default();
                if !interval.is_finite() || interval <= 0.0 || interval > 1.0 || map_name.is_empty()
                {
                    return Err("Invalid ServerInfo clock/map".into());
                }
                let max_classes = msg
                    .max_classes
                    .filter(|&m| m >= 1)
                    .ok_or_else(|| "Missing ServerInfo max_classes".to_string())?
                    as usize;
                let next_srv = ServerInfoState {
                    protocol: msg.protocol.unwrap_or(0),
                    server_count: msg.server_count.unwrap_or(0) as u32,
                    max_classes,
                    player_slot: msg.player_slot.unwrap_or(-1),
                    tick_interval: interval,
                    map_name,
                };
                if let Some(ref prev) = self.server {
                    if prev.server_count != next_srv.server_count
                        || prev.map_name != next_srv.map_name
                        || prev.max_classes != next_srv.max_classes
                        || prev.protocol != next_srv.protocol
                        || prev.tick_interval != next_srv.tick_interval
                    {
                        return Err("ServerInfo changed without world boundary".into());
                    }
                } else if let Some(ref manifest) = msg.game_session_manifest {
                    self.admit_manifest(manifest)?;
                }
                self.server = Some(next_srv);
                self.try_build_schema()?;
            }
            41 => {
                if self.schema.is_some() {
                    return Err("Serializer replacement needs world boundary".into());
                }
                let msg = CSvcMsgFlattenedSerializer::decode(body).map_err(|e| e.to_string())?;
                self.serializers = Some(msg);
                self.try_build_schema()?;
            }
            42 => {
                let msg = CSvcMsgClassInfo::decode(body).map_err(|e| e.to_string())?;
                if msg.create_on_client == Some(true) {
                    if self.schema.is_none() {
                        return Err("Cached classes unavailable".into());
                    }
                    return Ok(());
                }
                if self.schema.is_some() {
                    return Err("Class replacement needs world boundary".into());
                }
                self.classes = Some(msg);
                self.try_build_schema()?;
            }
            44 => {
                let msg = CSvcMsgCreateStringTable::decode(body).map_err(|e| e.to_string())?;
                self.tables.create(&msg)?;
            }
            45 => {
                let msg = CSvcMsgUpdateStringTable::decode(body).map_err(|e| e.to_string())?;
                self.tables.update(&msg)?;
            }
            51 => {
                self.reset_world(self.identity.world + 1);
                out.push(CoreOutput::WorldReset {
                    reason: "clear-all-string-tables".into(),
                });
            }
            55 => {
                let schema = self
                    .schema
                    .as_ref()
                    .ok_or_else(|| "Entities before schema readiness".to_string())?;
                let msg = CSvcMsgPacketEntities::decode(body).map_err(|e| e.to_string())?;
                if let Some(seq) = msg.max_spawngroup_creationsequence {
                    if seq > self.known_creation_sequence {
                        return Err("Snapshot exceeds admitted world creation sequence".into());
                    }
                }
                let prior_epoch = self.entities.epoch;
                let recv_tick = context_tick.unwrap_or(self.network_tick);
                if let Some(receipt) =
                    self.entities
                        .decode_packet(schema, &self.tables, &msg, recv_tick)?
                {
                    out.push(CoreOutput::Receipt {
                        tick: receipt.tick,
                        full: receipt.full,
                        baseline_ack: receipt.baseline_ack,
                        epoch: receipt.epoch,
                    });
                    if receipt.epoch != prior_epoch {
                        out.push(CoreOutput::Gap {
                            reason: "snapshot-epoch-restarted".into(),
                        });
                        self.last_cursor = None;
                    }
                    if let Some(ref srv) = self.server {
                        let advance = match self.last_cursor {
                            None => true,
                            Some(lc) => ((receipt.tick - lc) as f32) * srv.tick_interval >= 1.0,
                        };
                        if advance {
                            self.last_cursor = Some(receipt.tick);
                            let round_clock = project_round_clock(
                                self.schema.as_ref(),
                                &mut self.entities,
                                receipt.tick,
                            );
                            let empty_fields = BTreeMap::new();
                            let empty_types = BTreeMap::new();
                            let proj = project_native_event(
                                self.schema.as_ref(),
                                &mut self.entities,
                                &self.tables,
                                "cursor",
                                &empty_fields,
                                &empty_types,
                            );
                            out.push(CoreOutput::Cursor(CursorRecord {
                                kind: "cursor",
                                channel: self.identity.channel,
                                world: self.identity.world,
                                sequence: 0,
                                committed_tick: receipt.tick,
                                tick_interval: srv.tick_interval,
                                map: srv.map_name.clone(),
                                warmup: proj.warmup,
                                round: proj.round,
                                round_clock,
                            }));
                        }
                    }
                }
            }
            205 => {
                let msg =
                    CMsgSource1LegacyGameEventList::decode(body).map_err(|e| e.to_string())?;
                if msg.descriptors.len() > 512 {
                    return Err("Event descriptor budget".into());
                }
                let mut next = HashMap::new();
                for d in msg.descriptors {
                    let eid = d
                        .eventid
                        .filter(|&id| (0..512).contains(&id))
                        .ok_or_else(|| "Invalid event descriptor".to_string())?;
                    let ename = d.name.as_deref().unwrap_or("");
                    if ename.is_empty()
                        || ename.len() > 256
                        || next.contains_key(&eid)
                        || d.keys.len() > 256
                    {
                        return Err("Invalid event descriptor".into());
                    }
                    let mut names = HashSet::new();
                    for k in &d.keys {
                        let kname = k.name.as_deref().unwrap_or("");
                        let ktype = k.r#type.unwrap_or(-1);
                        if kname.is_empty()
                            || kname.len() > 256
                            || !names.insert(kname.to_string())
                            || ktype < 0
                        {
                            return Err("Invalid event key descriptor".into());
                        }
                    }
                    next.insert(eid, d);
                }
                let ids: Vec<i32> = next.keys().copied().collect();
                self.descriptors = next;
                self.descriptor_generation += 1;
                out.push(CoreOutput::EventSubscriptions {
                    descriptor_generation: self.descriptor_generation,
                    ids,
                    player_slot: self.server.as_ref().map(|s| s.player_slot),
                });
            }
            207 => {
                let msg = CMsgSource1LegacyGameEvent::decode(body).map_err(|e| e.to_string())?;
                let eid = msg.eventid.unwrap_or(-1);
                let Some(d) = self.descriptors.get(&eid) else {
                    out.push(CoreOutput::Gap {
                        reason: "event-descriptor-missing".into(),
                    });
                    return Ok(());
                };
                if d.keys.iter().any(|k| k.r#type.unwrap_or(0) > 9) {
                    out.push(CoreOutput::Diagnostic {
                        reason: "unsupported-event-field-type".into(),
                        event_id: Some(eid),
                    });
                    return Ok(());
                }
                if msg.keys.len() != d.keys.len() {
                    return Err("Event key count mismatch".into());
                }
                let mut fields = BTreeMap::new();
                let mut types = BTreeMap::new();
                for (def, val) in d.keys.iter().zip(msg.keys.iter()) {
                    let def_ty = def.r#type.unwrap_or(0);
                    if let Some(vt) = val.r#type {
                        if vt != def_ty {
                            return Err("Event key type mismatch".into());
                        }
                    }
                    let kname = def.name.clone().unwrap_or_default();
                    let jval = match def_ty {
                        1 => Value::String(val.val_string.clone().unwrap_or_default()),
                        2 => serde_json::Number::from_f64(val.val_float.unwrap_or(0.0) as f64)
                            .map(Value::Number)
                            .unwrap_or(Value::Null),
                        3 | 8 => Value::from(val.val_long.unwrap_or(0)),
                        4 | 9 => Value::from(val.val_short.unwrap_or(0)),
                        5 => Value::from(val.val_byte.unwrap_or(0)),
                        6 => Value::Bool(val.val_bool.unwrap_or(false)),
                        7 => Value::String(val.val_uint64.unwrap_or(0).to_string()),
                        _ => Value::Null,
                    };
                    fields.insert(kname.clone(), jval);
                    types.insert(kname, def_ty);
                }
                let ename = d.name.clone().unwrap_or_default();
                let proj = project_native_event(
                    self.schema.as_ref(),
                    &mut self.entities,
                    &self.tables,
                    &ename,
                    &fields,
                    &types,
                );
                let event_tick = msg
                    .server_tick
                    .unwrap_or_else(|| context_tick.unwrap_or(self.network_tick));
                out.push(CoreOutput::RawEvent(RawEventRecord {
                    kind: "event",
                    name: ename,
                    channel: self.identity.channel,
                    world: self.identity.world,
                    sequence: 0,
                    event_tick,
                    committed_tick: self.entities.latest_tick,
                    tick_interval: self.server.as_ref().map(|s| s.tick_interval),
                    map: self.server.as_ref().map(|s| s.map_name.clone()),
                    warmup: proj.warmup,
                    round: proj.round,
                    residence_us: None,
                    sdk_queue_age_us,
                    dequeue_ns: None,
                    fields,
                    players: proj.players,
                }));
            }
            _ => {}
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wire::bits::{encode_pb_bytes, encode_pb_varint};
    use crate::wire::channel::{decode_frame, decode_messages};

    fn decode_b64(input: &str) -> Vec<u8> {
        let table = |c: u8| -> Option<u8> {
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
                break;
            }
            let a = table(chunk[0]).unwrap();
            let b = table(chunk[1]).unwrap();
            out.push((a << 2) | (b >> 4));
            if chunk.len() > 2 && chunk[2] != b'=' {
                let c = table(chunk[2]).unwrap();
                out.push((b << 4) | (c >> 2));
                if chunk.len() > 3 && chunk[3] != b'=' {
                    let d = table(chunk[3]).unwrap();
                    out.push((c << 6) | d);
                }
            }
        }
        out
    }

    #[test]
    fn test_synthetic_channel_fixture_replay() {
        let json_str = include_str!("../../../tests/fixtures/synthetic-channel.json");
        let val: Value = serde_json::from_str(json_str).unwrap();
        let frames = val["frames"].as_array().unwrap();

        let mut core = ObserverCore::new(SourceIdentity {
            channel: 1,
            world: 1,
        });

        let mut cursors = Vec::new();
        let mut events = Vec::new();

        for f in frames {
            let reliable = f["reliable"].as_bool().unwrap();
            let body = decode_b64(f["bodyBase64"].as_str().unwrap());
            let frame = decode_frame(&body, reliable).unwrap();
            let (msgs, _) = decode_messages(&frame.body, None, None).unwrap();
            let mut ctx_tick = if frame.reliable {
                frame.reliable_tick_hint.unwrap_or(0) as i32
            } else {
                0
            };
            for m in msgs {
                if m.message_id == 4 {
                    if let Ok(t) = CNetMsgTick::decode(m.body.as_slice()) {
                        if let Some(tv) = t.tick {
                            if tv > 0 {
                                ctx_tick = tv as i32;
                            }
                        }
                    }
                } else if m.message_id == 55 {
                    if let Ok(pe) = CSvcMsgPacketEntities::decode(m.body.as_slice()) {
                        if let Some(st) = pe.server_tick {
                            if st > 0 {
                                ctx_tick = st as i32;
                            }
                        }
                    }
                }
                for out in core.consume(m.message_id, &m.body, Some(ctx_tick), None) {
                    match out {
                        CoreOutput::Cursor(c) => cursors.push(c),
                        CoreOutput::RawEvent(e) => events.push(e),
                        CoreOutput::Recovery { reason, .. } => {
                            panic!("unexpected recovery: {reason}");
                        }
                        _ => {}
                    }
                }
            }
        }

        assert_eq!(cursors.len(), 1);
        assert_eq!(cursors[0].kind, "cursor");
        assert_eq!(cursors[0].committed_tick, 100);
        assert_eq!(cursors[0].map, "de_test");
        assert_eq!(cursors[0].round_clock.status, "unavailable");

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, "event");
        assert_eq!(events[0].name, "round_freeze_end");
        assert_eq!(events[0].event_tick, 100);
        assert_eq!(events[0].committed_tick, Some(100));
        assert_eq!(events[0].residence_us, None);
    }

    #[test]
    fn test_weapon_fire_player_identity_projection() {
        let steam: u64 = 76561198000000123;
        let mut core = ObserverCore::new(SourceIdentity {
            channel: 1,
            world: 2,
        });

        let mut srv = Vec::new();
        encode_pb_varint(1, 14191, &mut srv);
        encode_pb_varint(2, 7, &mut srv);
        encode_pb_varint(11, 1, &mut srv);
        srv.push(0x6d);
        srv.extend_from_slice(&(1.0f32 / 64.0f32).to_le_bytes());
        encode_pb_bytes(15, b"de_test", &mut srv);
        core.consume(40, &srv, Some(99), None);

        let mut ser_msg = Vec::new();
        let mut s = Vec::new();
        encode_pb_varint(1, 0, &mut s);
        encode_pb_varint(2, 0, &mut s);
        encode_pb_varint(3, 0, &mut s);
        encode_pb_bytes(1, &s, &mut ser_msg);
        for sym in ["CCSPlayerController", "m_steamID", "uint64", "fixed64"] {
            encode_pb_bytes(2, sym.as_bytes(), &mut ser_msg);
        }
        let mut fld = Vec::new();
        encode_pb_varint(1, 2, &mut fld);
        encode_pb_varint(2, 1, &mut fld);
        encode_pb_varint(10, 3, &mut fld);
        encode_pb_bytes(3, &fld, &mut ser_msg);
        core.consume(41, &ser_msg, Some(99), None);

        let mut cls = Vec::new();
        let mut c0 = Vec::new();
        encode_pb_varint(1, 0, &mut c0);
        encode_pb_bytes(3, b"CCSPlayerController", &mut c0);
        encode_pb_bytes(2, &c0, &mut cls);
        core.consume(42, &cls, Some(99), None);

        let pack_bits = |bits: &[u8]| -> Vec<u8> {
            let mut out = vec![0u8; bits.len().div_ceil(8)];
            for (i, &b) in bits.iter().enumerate() {
                if b != 0 {
                    out[i / 8] |= 1 << (i & 7);
                }
            }
            out
        };
        let push_bits = |vec: &mut Vec<u8>, val: u64, count: u8| {
            for i in 0..count {
                vec.push(((val >> i) & 1) as u8);
            }
        };

        let mut fw = vec![0u8, 1, 0];
        push_bits(&mut fw, steam, 64);
        let fw_bytes = pack_bits(&fw);

        let mut st_bits = vec![1u8, 1, 0];
        push_bits(&mut st_bits, 48, 8);
        push_bits(&mut st_bits, 0, 8);
        st_bits.push(1);
        push_bits(&mut st_bits, fw_bytes.len() as u64, 17);
        for &b in &fw_bytes {
            push_bits(&mut st_bits, b as u64, 8);
        }
        let mut st_ib = Vec::new();
        encode_pb_bytes(1, b"instancebaseline", &mut st_ib);
        encode_pb_varint(2, 1, &mut st_ib);
        encode_pb_bytes(7, &pack_bits(&st_bits), &mut st_ib);
        core.consume(44, &st_ib, Some(99), None);

        let mut uinfo_val = vec![0x11u8];
        uinfo_val.extend_from_slice(&steam.to_le_bytes());
        encode_pb_varint(3, 42, &mut uinfo_val);
        let mut ui_bits = vec![1u8, 1, 0];
        push_bits(&mut ui_bits, 48, 8);
        push_bits(&mut ui_bits, 0, 8);
        ui_bits.push(1);
        push_bits(&mut ui_bits, uinfo_val.len() as u64, 17);
        for &b in &uinfo_val {
            push_bits(&mut ui_bits, b as u64, 8);
        }
        let mut st_ui = Vec::new();
        encode_pb_bytes(1, b"userinfo", &mut st_ui);
        encode_pb_varint(2, 1, &mut st_ui);
        encode_pb_bytes(7, &pack_bits(&ui_bits), &mut st_ui);
        core.consume(44, &st_ui, Some(99), None);

        let mut pe_bits = Vec::new();
        push_bits(&mut pe_bits, 1, 6);
        push_bits(&mut pe_bits, 2, 2);
        pe_bits.push(0);
        push_bits(&mut pe_bits, 1, 17);
        push_bits(&mut pe_bits, 0, 8);
        pe_bits.extend_from_slice(&fw);
        let mut pe = Vec::new();
        encode_pb_varint(2, 1, &mut pe);
        encode_pb_varint(10, 0, &mut pe);
        encode_pb_varint(12, 99, &mut pe);
        encode_pb_bytes(7, &pack_bits(&pe_bits), &mut pe);
        encode_pb_bytes(19, &[], &mut pe);
        core.consume(55, &pe, Some(99), None);

        let mut desc = Vec::new();
        encode_pb_varint(1, 17, &mut desc);
        encode_pb_bytes(2, b"weapon_fire", &mut desc);
        for (t, n) in [(9u64, "userid"), (1, "weapon"), (6, "silenced")] {
            let mut k = Vec::new();
            encode_pb_varint(1, t, &mut k);
            encode_pb_bytes(2, n.as_bytes(), &mut k);
            encode_pb_bytes(3, &k, &mut desc);
        }
        let mut ev_list = Vec::new();
        encode_pb_bytes(1, &desc, &mut ev_list);
        core.consume(205, &ev_list, Some(99), None);

        let mut ev = Vec::new();
        encode_pb_varint(2, 17, &mut ev);
        let mut k0 = Vec::new();
        encode_pb_varint(1, 9, &mut k0);
        encode_pb_varint(5, 0, &mut k0);
        encode_pb_bytes(3, &k0, &mut ev);
        let mut k1 = Vec::new();
        encode_pb_varint(1, 1, &mut k1);
        encode_pb_bytes(2, b"ak47", &mut k1);
        encode_pb_bytes(3, &k1, &mut ev);
        let mut k2 = Vec::new();
        encode_pb_varint(1, 6, &mut k2);
        encode_pb_varint(7, 0, &mut k2);
        encode_pb_bytes(3, &k2, &mut ev);

        let outs = core.consume(207, &ev, Some(100), Some(1200));
        let raw_ev = outs
            .into_iter()
            .find_map(|o| match o {
                CoreOutput::RawEvent(e) => Some(e),
                _ => None,
            })
            .unwrap();
        assert_eq!(raw_ev.kind, "event");
        assert_eq!(raw_ev.name, "weapon_fire");
        assert_eq!(raw_ev.event_tick, 100);
        assert_eq!(raw_ev.sdk_queue_age_us, Some(1200));
        assert_eq!(raw_ev.residence_us, None);
        assert_eq!(
            raw_ev.fields.get("weapon").and_then(|v| v.as_str()),
            Some("ak47")
        );
        let p = raw_ev.players.get("userid").unwrap().as_ref().unwrap();
        assert_eq!(p.user_id, Some(42));
        assert_eq!(p.slot, 0);
        assert_eq!(p.controller.index, 1);
        assert_eq!(p.controller.serial, 1);
    }
}
