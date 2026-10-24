/** Fixed CS2 14191/10924 profile. Evidence and hashes live in the private observer research records.
 * Wire metadata remains authoritative; no unknown enum or custom type is guessed.
 * Resource aliases are FieldTypeAliases only, never replay RenamedTypes.
 */
export type NativeWireType = Readonly<{ category: number; dimensions: number }>;
export const nativePrimitiveTypes: Readonly<Record<string, NativeWireType>> = Object.freeze({
  "char": {
    "category": 1,
    "dimensions": 1
  },
  "int8": {
    "category": 1,
    "dimensions": 1
  },
  "uint8": {
    "category": 2,
    "dimensions": 1
  },
  "int16": {
    "category": 1,
    "dimensions": 1
  },
  "uint16": {
    "category": 2,
    "dimensions": 1
  },
  "int32": {
    "category": 1,
    "dimensions": 1
  },
  "uint32": {
    "category": 2,
    "dimensions": 1
  },
  "int64": {
    "category": 1,
    "dimensions": 1
  },
  "uint64": {
    "category": 2,
    "dimensions": 1
  },
  "float32": {
    "category": 3,
    "dimensions": 1
  },
  "float64": {
    "category": 4,
    "dimensions": 1
  },
  "Vector2D": {
    "category": 3,
    "dimensions": 2
  },
  "Vector": {
    "category": 3,
    "dimensions": 3
  },
  "VectorWS": {
    "category": 3,
    "dimensions": 3
  },
  "Vector4D": {
    "category": 3,
    "dimensions": 4
  },
  "QAngle": {
    "category": 3,
    "dimensions": 3
  },
  "QuaternionStorage": {
    "category": 3,
    "dimensions": 4
  },
  "Quaternion": {
    "category": 3,
    "dimensions": 4
  },
  "Color": {
    "category": 2,
    "dimensions": 1
  },
  "bool": {
    "category": 7,
    "dimensions": 1
  },
  "matrix3x4_t": {
    "category": 3,
    "dimensions": 8
  },
  "string_t": {
    "category": 5,
    "dimensions": 1
  },
  "CUtlString": {
    "category": 5,
    "dimensions": 1
  },
  "matrix3x4a_t": {
    "category": 3,
    "dimensions": 8
  },
  "CUtlBinaryBlock": {
    "category": 6,
    "dimensions": 0
  },
  "CTransform": {
    "category": 3,
    "dimensions": 6
  },
  "CTransformWS": {
    "category": 3,
    "dimensions": 6
  },
  "RadianEuler": {
    "category": 3,
    "dimensions": 3
  },
  "DegreeEuler": {
    "category": 3,
    "dimensions": 3
  },
  "CGlobalSymbol": {
    "category": 5,
    "dimensions": 1
  },
  "CUtlSymbolLarge": {
    "category": 5,
    "dimensions": 1
  },
  "RotationVector": {
    "category": 3,
    "dimensions": 3
  }
});
export const nativeCustomTypes: Readonly<Record<string, NativeWireType>> = Object.freeze({
  "animTimeSerializer": {
    "category": 2,
    "dimensions": 1
  },
  "ClampHealth": {
    "category": 1,
    "dimensions": 1
  },
  "funcRotatingSimulationTimeSerializer": {
    "category": 2,
    "dimensions": 1
  },
  "minusone": {
    "category": 2,
    "dimensions": 1
  },
  "angle_normalize_positive": {
    "category": 3,
    "dimensions": 1
  },
  "simulationTimeSerializer": {
    "category": 2,
    "dimensions": 1
  },
  "StepSimulationFuncRotatingAnglesSerializer": {
    "category": 3,
    "dimensions": 3
  },
  "cellx": {
    "category": 1,
    "dimensions": 1
  },
  "celly": {
    "category": 1,
    "dimensions": 1
  },
  "cellz": {
    "category": 1,
    "dimensions": 1
  },
  "posx": {
    "category": 3,
    "dimensions": 1
  },
  "posy": {
    "category": 3,
    "dimensions": 1
  },
  "posz": {
    "category": 3,
    "dimensions": 1
  },
  "gameSceneNode": {
    "category": 2,
    "dimensions": 1
  },
  "gameSceneNodeStepSimulationAnglesSerializer": {
    "category": 3,
    "dimensions": 3
  },
  "gameSceneNodeStepSimulationOriginSerializer": {
    "category": 3,
    "dimensions": 3
  },
  "fish_pos_x": {
    "category": 3,
    "dimensions": 1
  },
  "fish_pos_y": {
    "category": 3,
    "dimensions": 1
  },
  "fish_pos_z": {
    "category": 3,
    "dimensions": 1
  },
  "ehandle": {
    "category": 2,
    "dimensions": 1
  }
});
export const nativeEnumSignedness: Readonly<Record<string, boolean>> = Object.freeze({
  "AnimLoopMode_t": true,
  "AnimationAlgorithm_t": true,
  "BeamType_t": false,
  "BloodType": true,
  "CSPlayerBlockingUseAction_t": false,
  "CSPlayerState": false,
  "CSWeaponMode": false,
  "CustomCameraMode_t": false,
  "DoorState_t": false,
  "EHudPanelClassStatus_t": true,
  "EKillTypes_t": false,
  "EntityDissolveType_t": true,
  "EntityPlatformTypes_t": false,
  "FixAngleSet_t": false,
  "MedalRank_t": false,
  "MoveCollide_t": false,
  "MoveType_t": false,
  "PlayerConnectedState": true,
  "PointWorldTextJustifyHorizontal_t": false,
  "PointWorldTextJustifyVertical_t": false,
  "PointWorldTextReorientMode_t": false,
  "QuestProgress::Reason": false,
  "RenderFx_t": false,
  "RenderMode_t": false,
  "ShardSolid_t": false,
  "SolidType_t": false,
  "SurroundingBoundsType_t": false,
  "TakeDamageFlags_t": false,
  "ValueRemapperHapticsType_t": false,
  "ValueRemapperInputType_t": false,
  "ValueRemapperMomentumType_t": false,
  "ValueRemapperOutputType_t": false,
  "ValueRemapperRatchetType_t": false,
  "WeaponGameplayAnimState": false,
  "attributeprovidertypes_t": false,
  "loadout_slot_t": true
});
export const nativeTypeAliases = [
  {
    "from": "CHandle<",
    "to": "uint32",
    "prefix": true
  },
  {
    "from": "CUtlStringToken",
    "to": "uint32",
    "prefix": false
  },
  {
    "from": "gender_t",
    "to": "uint8",
    "prefix": false
  },
  {
    "from": "BloodType",
    "to": "int32",
    "prefix": false
  },
  {
    "from": "PrecipitationType_t",
    "to": "int32",
    "prefix": false
  },
  {
    "from": "CNetworkedQuantizedFloat",
    "to": "float32",
    "prefix": false
  },
  {
    "from": "CGameSceneNodeHandle",
    "to": "uint64",
    "prefix": false
  },
  {
    "from": "HSequence",
    "to": "int32",
    "prefix": false
  },
  {
    "from": "PoseController_FModType_t",
    "to": "uint32",
    "prefix": false
  },
  {
    "from": "ShatterPanelMode",
    "to": "uint8",
    "prefix": false
  },
  {
    "from": "DecalMode_t",
    "to": "DecalRtEncoding_t",
    "prefix": false
  },
  {
    "from": "BeamClipStyle_t",
    "to": "int32",
    "prefix": false
  },
  {
    "from": "EGrenadeThrowState",
    "to": "uint32",
    "prefix": false
  },
  {
    "from": "CEntityIndex",
    "to": "int32",
    "prefix": false
  },
  {
    "from": "CSWeaponState_t",
    "to": "uint32",
    "prefix": false
  },
  {
    "from": "WorldGroupId_t",
    "to": "uint32",
    "prefix": false
  },
  {
    "from": "PlayerAnimEvent_t",
    "to": "WeaponGameplayAnimState",
    "prefix": false
  },
  {
    "from": "WeaponAttackType_t",
    "to": "int32",
    "prefix": false
  },
  {
    "from": "DecalRtEncoding_t",
    "to": "uint8",
    "prefix": false
  }
] as const;
const nativePointerFieldNames = new Set<string>(["CBodyComponent", "CBodyComponentPoint", "CBodyComponentBaseAnimating", "C_BodyComponentBaseAnimating", "CBodyComponentBaseAnimatingOverlay", "C_BodyComponentBaseAnimatingOverlay", "CBodyComponentBaseModelEntity", "CPhysicsComponent", "CRenderComponent"]);
export const nativeFieldSerializerFallbacks: Readonly<Record<string, string>> = Object.freeze({"m_flSimulationTime": "simulationTimeSerializer"});
export const nativeBoxedTypes: Readonly<Record<string, string>> = Object.freeze({
  "AttachmentHandle_t": "uint8",
  "CEntityIndex": "int32",
  "CPlayerSlot": "int32",
  "GameTick_t": "int32",
  "GameTime_t": "float32",
  "HSequence": "int32",
  "ModelConfigHandle_t": "uint32",
  "ResourceId_t": "uint64",
  "WorldGroupId_t": "uint32"
});

export const isNativePointerFieldName = (name:string):boolean => nativePointerFieldNames.has(name);
for(const value of Object.values(nativePrimitiveTypes))Object.freeze(value);
for(const value of Object.values(nativeCustomTypes))Object.freeze(value);
for(const value of nativeTypeAliases)Object.freeze(value);
Object.freeze(nativeTypeAliases);
