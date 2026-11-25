use std::collections::BTreeMap;

use prost::Message;
use serde::Serialize;
use serde_json::Value;

use super::field_codec::FieldValue;
use super::packet_entities::{Entity, EntityTable};
use super::schema::Schema;
use super::string_tables::StringTables;
use crate::wire::proto::CMsgPlayerInfo;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EntityHandle {
    pub index: usize,
    pub serial: u32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerIdentity {
    pub domain: &'static str,
    pub slot: usize,
    pub steam_id: String,
    pub user_id: Option<i32>,
    pub controller: EntityHandle,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PauseClock {
    pub active: Option<bool>,
    pub total_paused_ticks: Option<i32>,
    pub start_tick: Option<i32>,
    pub technical: Option<bool>,
    pub semantics: &'static str,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RoundClock {
    pub total_rounds_played: Option<i32>,
    pub phase: &'static str,
    pub start_time: Option<f32>,
    pub duration: Option<i32>,
    pub committed_tick: i32,
    pub freeze_period: Option<bool>,
    pub warmup_period: Option<bool>,
    pub bomb_planted: Option<bool>,
    pub round_in_progress: Option<bool>,
    pub round_win_status: Option<i32>,
    pub pause: PauseClock,
    pub status: &'static str,
}

#[derive(Debug, Clone)]
pub struct EventProjection {
    pub actor: Option<String>,
    pub target: Option<String>,
    pub warmup: Option<bool>,
    pub round: Option<u32>,
    pub players: BTreeMap<String, Option<PlayerIdentity>>,
    pub pawns: BTreeMap<String, Option<EntityHandle>>,
    pub weapon: Option<String>,
    pub identity_resolved: bool,
}

pub fn valid_individual_steam_id(val: u64) -> Option<String> {
    if val == 0 {
        return None;
    }
    if (val >> 56) == 1
        && ((val >> 52) & 15) == 1
        && ((val >> 32) & 0xf_ffff) <= 4
        && (val & 0xffff_ffff) != 0
    {
        Some(val.to_string())
    } else {
        None
    }
}

fn int32_val(v: Option<&FieldValue>) -> Option<i32> {
    match v {
        Some(FieldValue::Int(x)) if *x >= i32::MIN as i64 && *x <= i32::MAX as i64 => {
            Some(*x as i32)
        }
        Some(FieldValue::Uint(x)) if *x <= i32::MAX as u64 => Some(*x as i32),
        _ => None,
    }
}

fn uint32_val(v: Option<&FieldValue>) -> Option<u32> {
    match v {
        Some(FieldValue::Int(x)) if *x >= 0 && *x <= u32::MAX as i64 => Some(*x as u32),
        Some(FieldValue::Uint(x)) if *x <= u32::MAX as u64 => Some(*x as u32),
        _ => None,
    }
}

fn uint64_val(v: Option<&FieldValue>) -> Option<u64> {
    match v {
        Some(FieldValue::Uint(x)) => Some(*x),
        Some(FieldValue::Int(x)) if *x >= 0 => Some(*x as u64),
        _ => None,
    }
}

fn bool_val(v: Option<&FieldValue>) -> Option<bool> {
    match v {
        Some(FieldValue::Bool(b)) => Some(*b),
        _ => None,
    }
}

fn f32_val(v: Option<&FieldValue>) -> Option<f32> {
    match v {
        Some(FieldValue::Float(fv)) => fv.as_finite().filter(|x| x.is_finite() && *x >= 0.0),
        _ => None,
    }
}

fn find_game_rules<'a>(schema: &Schema, entities: &'a EntityTable) -> Option<&'a Entity> {
    if entities.waiting_full {
        return None;
    }
    entities.iter().find(|e| {
        schema
            .get_class(e.class_id)
            .map(|c| c.name == "CCSGameRulesProxy")
            .unwrap_or(false)
    })
}

pub fn project_round_clock(
    schema: Option<&Schema>,
    entities: &EntityTable,
    committed_tick: i32,
) -> RoundClock {
    let rules = schema.and_then(|s| find_game_rules(s, entities));
    let get = |name: &str| rules.and_then(|r| r.fields.field_by_name(name));
    let get_nonneg_i32 = |name: &str| int32_val(get(name)).filter(|&v| v >= 0);

    let total_rounds_played = get_nonneg_i32("m_totalRoundsPlayed");
    let start_time = f32_val(get("m_fRoundStartTime"));
    let duration = get_nonneg_i32("m_iRoundTime");
    let freeze_period = bool_val(get("m_bFreezePeriod"));
    let warmup_period = bool_val(get("m_bWarmupPeriod"));
    let bomb_planted = bool_val(get("m_bBombPlanted"));
    let round_in_progress = bool_val(get("m_bRoundInProgress"));
    let round_win_status = int32_val(get("m_iRoundWinStatus"));

    let pause_active = bool_val(get("m_bGamePaused"));
    let total_paused_ticks = get_nonneg_i32("m_nTotalPausedTicks");
    let start_tick = get_nonneg_i32("m_nPauseStartTick");
    let technical = bool_val(get("m_bTechnicalTimeOut"));

    let phase = if warmup_period == Some(true) {
        "warmup"
    } else if warmup_period == Some(false) && freeze_period == Some(true) {
        "freezetime"
    } else {
        "unknown"
    };

    let mut present_count = 0usize;
    let flags = [
        total_rounds_played.is_some(),
        start_time.is_some(),
        duration.is_some(),
        freeze_period.is_some(),
        warmup_period.is_some(),
        bomb_planted.is_some(),
        pause_active.is_some(),
        total_paused_ticks.is_some(),
        start_tick.is_some(),
        technical.is_some(),
    ];
    for f in flags {
        if f {
            present_count += 1;
        }
    }
    let status = if present_count == 0 {
        "unavailable"
    } else if present_count == 10 {
        "available"
    } else {
        "partial"
    };

    RoundClock {
        total_rounds_played,
        phase,
        start_time,
        duration,
        committed_tick,
        freeze_period,
        warmup_period,
        bomb_planted,
        round_in_progress,
        round_win_status,
        pause: PauseClock {
            active: pause_active,
            total_paused_ticks,
            start_tick,
            technical,
            semantics: "unknown",
        },
        status,
    }
}

pub fn project_native_event(
    schema: Option<&Schema>,
    entities: &EntityTable,
    tables: &StringTables,
    name: &str,
    fields: &BTreeMap<String, Value>,
    types: &BTreeMap<String, i32>,
) -> EventProjection {
    let mut players: BTreeMap<String, Option<PlayerIdentity>> = BTreeMap::new();
    let mut pawns: BTreeMap<String, Option<EntityHandle>> = BTreeMap::new();

    for (key, &ty) in types {
        if ty != 9 {
            continue;
        }
        let resolved_player = (|| -> Option<PlayerIdentity> {
            let s = schema?;
            if entities.waiting_full {
                return None;
            }
            let raw = fields.get(key)?.as_i64()?;
            let value = (raw as u64) & 65535;
            if value == 65535 {
                return None;
            }
            let slot = (value & 255) as usize;
            let controller = entities.get(slot + 1)?;
            let cname = &s.get_class(controller.class_id).ok()?.name;
            if !cname.ends_with("PlayerController") {
                return None;
            }
            let steam_u64 = uint64_val(controller.fields.field_by_name("m_steamID"))?;
            let sid = valid_individual_steam_id(steam_u64)?;
            let info_bytes = tables.userinfo_entry(slot)?;
            if info_bytes.is_empty() {
                return None;
            }
            let stored = CMsgPlayerInfo::decode(info_bytes).ok()?;
            if stored.fakeplayer.unwrap_or(false) || stored.ishltv.unwrap_or(false) {
                return None;
            }
            let stored_sid = stored
                .xuid
                .and_then(valid_individual_steam_id)
                .or_else(|| stored.steamid.and_then(valid_individual_steam_id))?;
            if stored_sid != sid {
                return None;
            }
            Some(PlayerIdentity {
                domain: "player-controller-slot",
                slot,
                steam_id: sid,
                user_id: stored.userid.filter(|&u| u > 0),
                controller: EntityHandle {
                    index: controller.id,
                    serial: controller.serial,
                },
            })
        })();
        players.insert(key.clone(), resolved_player);
    }

    for (key, &ty) in types {
        if ty != 9 {
            continue;
        }
        let pawn_key = format!("{key}_pawn");
        if types.get(&pawn_key).copied() != Some(8) {
            continue;
        }
        let resolved_pawn = (|| -> Option<EntityHandle> {
            let player = players.get(key)?.as_ref()?;
            let controller = entities.get(player.controller.index)?;
            let raw_pawn = fields.get(&pawn_key)?.as_i64()?;
            let handle = (raw_pawn as u64) as u32;
            if handle == 0xFFFF_FFFF || handle == 0xFFFF_FFFE {
                return None;
            }
            let pawn = entities.get((handle & 0x7fff) as usize)?;
            if pawn.serial != (handle >> 15) {
                return None;
            }
            let linked = uint32_val(
                controller
                    .fields
                    .field_by_name("m_hPlayerPawn")
                    .or_else(|| controller.fields.field_by_name("m_hPawn")),
            )?;
            if (linked & 0x3fff) as usize != pawn.id
                || ((linked >> 14) & 0x3ff) != (pawn.serial & 0x3ff)
            {
                return None;
            }
            Some(EntityHandle {
                index: pawn.id,
                serial: pawn.serial,
            })
        })();
        pawns.insert(key.clone(), resolved_pawn);
    }

    let mut warmup = None;
    let mut round = None;
    if let Some(rules) = schema.and_then(|s| find_game_rules(s, entities)) {
        warmup = bool_val(rules.fields.field_by_name("m_bWarmupPeriod"));
        round = uint32_val(rules.fields.field_by_name("m_totalRoundsPlayed"));
    }

    let actor = match name {
        "player_death" => players
            .get("attacker")
            .and_then(|p| p.as_ref())
            .map(|p| p.steam_id.clone()),
        "weapon_fire" => players
            .get("userid")
            .and_then(|p| p.as_ref())
            .map(|p| p.steam_id.clone()),
        _ => None,
    };
    let target = if name == "player_death" {
        players
            .get("userid")
            .and_then(|p| p.as_ref())
            .map(|p| p.steam_id.clone())
    } else {
        None
    };
    let weapon = fields
        .get("weapon")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let identity_resolved = match name {
        "weapon_fire" => actor.is_some(),
        "player_death" => actor.is_some() && target.is_some(),
        _ => false,
    };

    EventProjection {
        actor,
        target,
        warmup,
        round,
        players,
        pawns,
        weapon,
        identity_resolved,
    }
}
