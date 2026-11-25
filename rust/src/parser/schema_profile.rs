#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WireType {
    pub category: u8,
    pub dimensions: u8,
}

pub fn lookup_primitive(name_lower: &str) -> Option<WireType> {
    let (cat, dim) = match name_lower {
        "char" | "int8" | "int16" | "int32" | "int64" => (1, 1),
        "uint8" | "uint16" | "uint32" | "uint64" | "color" => (2, 1),
        "float32" => (3, 1),
        "float64" => (4, 1),
        "vector2d" => (3, 2),
        "vector" | "vectorws" | "qangle" | "radianeuler" | "degreeeuler" | "rotationvector" => {
            (3, 3)
        }
        "vector4d" | "quaternionstorage" | "quaternion" => (3, 4),
        "bool" => (7, 1),
        "matrix3x4_t" | "matrix3x4a_t" => (3, 8),
        "string_t" | "cutlstring" | "cglobalsymbol" | "cutlsymbollarge" => (5, 1),
        "cutlbinaryblock" => (6, 0),
        "ctransform" | "ctransformws" => (3, 6),
        _ => return None,
    };
    Some(WireType {
        category: cat,
        dimensions: dim,
    })
}

pub fn lookup_custom(name_lower: &str) -> Option<(&'static str, WireType)> {
    let (canonical, cat, dim) = match name_lower {
        "animtimeserializer" => ("animTimeSerializer", 2, 1),
        "clamphealth" => ("ClampHealth", 1, 1),
        "funcrotatingsimulationtimeserializer" => ("funcRotatingSimulationTimeSerializer", 2, 1),
        "minusone" => ("minusone", 2, 1),
        "angle_normalize_positive" => ("angle_normalize_positive", 3, 1),
        "simulationtimeserializer" => ("simulationTimeSerializer", 2, 1),
        "stepsimulationfuncrotatinganglesserializer" => {
            ("StepSimulationFuncRotatingAnglesSerializer", 3, 3)
        }
        "cellx" => ("cellx", 1, 1),
        "celly" => ("celly", 1, 1),
        "cellz" => ("cellz", 1, 1),
        "posx" => ("posx", 3, 1),
        "posy" => ("posy", 3, 1),
        "posz" => ("posz", 3, 1),
        "gamescenenode" => ("gameSceneNode", 2, 1),
        "gamescenenodestepsimulationanglesserializer" => {
            ("gameSceneNodeStepSimulationAnglesSerializer", 3, 3)
        }
        "gamescenenodestepsimulationoriginserializer" => {
            ("gameSceneNodeStepSimulationOriginSerializer", 3, 3)
        }
        "fish_pos_x" => ("fish_pos_x", 3, 1),
        "fish_pos_y" => ("fish_pos_y", 3, 1),
        "fish_pos_z" => ("fish_pos_z", 3, 1),
        "ehandle" => ("ehandle", 2, 1),
        _ => return None,
    };
    Some((
        canonical,
        WireType {
            category: cat,
            dimensions: dim,
        },
    ))
}

pub fn lookup_enum_signed(name_lower: &str) -> Option<bool> {
    let signed = match name_lower {
        "animloopmode_t"
        | "animationalgorithm_t"
        | "bloodtype"
        | "ehudpanelclassstatus_t"
        | "entitydissolvetype_t"
        | "playerconnectedstate"
        | "loadout_slot_t" => true,
        "beamtype_t"
        | "csplayerblockinguseaction_t"
        | "csplayerstate"
        | "csweaponmode"
        | "customcameramode_t"
        | "doorstate_t"
        | "ekilltypes_t"
        | "entityplatformtypes_t"
        | "fixangleset_t"
        | "medalrank_t"
        | "movecollide_t"
        | "movetype_t"
        | "pointworldtextjustifyhorizontal_t"
        | "pointworldtextjustifyvertical_t"
        | "pointworldtextreorientmode_t"
        | "questprogress::reason"
        | "renderfx_t"
        | "rendermode_t"
        | "shardsolid_t"
        | "solidtype_t"
        | "surroundingboundstype_t"
        | "takedamageflags_t"
        | "valueremapperhapticstype_t"
        | "valueremapperinputtype_t"
        | "valueremappermomentumtype_t"
        | "valueremapperoutputtype_t"
        | "valueremapperratchettype_t"
        | "weapongameplayanimstate"
        | "attributeprovidertypes_t" => false,
        _ => return None,
    };
    Some(signed)
}

pub fn lookup_boxed_type(name_lower: &str) -> Option<&'static str> {
    match name_lower {
        "attachmenthandle_t" => Some("uint8"),
        "centityindex" | "cplayerslot" | "gametick_t" | "hsequence" => Some("int32"),
        "gametime_t" => Some("float32"),
        "modelconfighandle_t" | "worldgroupid_t" => Some("uint32"),
        "resourceid_t" => Some("uint64"),
        _ => None,
    }
}

pub fn remap_type_alias(type_name: &str) -> Result<String, String> {
    let mut current = type_name.to_string();
    for _ in 0..16 {
        let lower = current.to_ascii_lowercase();
        let next = if lower.starts_with("chandle<") {
            Some("uint32")
        } else {
            match current.as_str() {
                "CUtlStringToken"
                | "PoseController_FModType_t"
                | "EGrenadeThrowState"
                | "CSWeaponState_t"
                | "WorldGroupId_t" => Some("uint32"),
                "gender_t" | "ShatterPanelMode" | "DecalRtEncoding_t" => Some("uint8"),
                "BloodType"
                | "PrecipitationType_t"
                | "HSequence"
                | "BeamClipStyle_t"
                | "CEntityIndex"
                | "WeaponAttackType_t" => Some("int32"),
                "CNetworkedQuantizedFloat" => Some("float32"),
                "CGameSceneNodeHandle" => Some("uint64"),
                "DecalMode_t" => Some("DecalRtEncoding_t"),
                "PlayerAnimEvent_t" => Some("WeaponGameplayAnimState"),
                _ => None,
            }
        };
        match next {
            Some(n) if n != current => current = n.to_string(),
            _ => return Ok(current),
        }
    }
    Err("Type alias recursion budget".into())
}

pub fn is_pointer_field_name(name: &str) -> bool {
    matches!(
        name,
        "CBodyComponent"
            | "CBodyComponentPoint"
            | "CBodyComponentBaseAnimating"
            | "C_BodyComponentBaseAnimating"
            | "CBodyComponentBaseAnimatingOverlay"
            | "C_BodyComponentBaseAnimatingOverlay"
            | "CBodyComponentBaseModelEntity"
            | "CPhysicsComponent"
            | "CRenderComponent"
    )
}

pub fn field_serializer_fallback(name_lower: &str) -> Option<&'static str> {
    match name_lower {
        "m_flsimulationtime" => Some("simulationTimeSerializer"),
        _ => None,
    }
}
