use prost::Message;

#[derive(Clone, PartialEq, Message)]
pub struct CNetMsgTick {
    #[prost(uint32, optional, tag = "1")]
    pub tick: Option<u32>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CMsgPlayerInfo {
    #[prost(string, optional, tag = "1")]
    pub name: Option<String>,
    #[prost(fixed64, optional, tag = "2")]
    pub xuid: Option<u64>,
    #[prost(int32, optional, tag = "3")]
    pub userid: Option<i32>,
    #[prost(fixed64, optional, tag = "4")]
    pub steamid: Option<u64>,
    #[prost(bool, optional, tag = "5")]
    pub fakeplayer: Option<bool>,
    #[prost(bool, optional, tag = "6")]
    pub ishltv: Option<bool>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgServerInfo {
    #[prost(int32, optional, tag = "1")]
    pub protocol: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub server_count: Option<i32>,
    #[prost(bool, optional, tag = "3")]
    pub is_dedicated: Option<bool>,
    #[prost(bool, optional, tag = "4")]
    pub is_hltv: Option<bool>,
    #[prost(int32, optional, tag = "10")]
    pub max_clients: Option<i32>,
    #[prost(int32, optional, tag = "11")]
    pub max_classes: Option<i32>,
    #[prost(int32, optional, tag = "12")]
    pub player_slot: Option<i32>,
    #[prost(float, optional, tag = "13")]
    pub tick_interval: Option<f32>,
    #[prost(string, optional, tag = "14")]
    pub game_dir: Option<String>,
    #[prost(string, optional, tag = "15")]
    pub map_name: Option<String>,
    #[prost(bytes = "vec", optional, tag = "20")]
    pub game_session_manifest: Option<Vec<u8>>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgClassInfoClass {
    #[prost(int32, optional, tag = "1")]
    pub class_id: Option<i32>,
    #[prost(string, optional, tag = "3")]
    pub class_name: Option<String>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgClassInfo {
    #[prost(bool, optional, tag = "1")]
    pub create_on_client: Option<bool>,
    #[prost(message, repeated, tag = "2")]
    pub classes: Vec<CSvcMsgClassInfoClass>,
}

#[derive(Clone, PartialEq, Message)]
pub struct ProtoFlattenedSerializerEnumInfo {
    #[prost(bool, optional, tag = "1")]
    pub is_signed_enum: Option<bool>,
}

#[derive(Clone, PartialEq, Message)]
pub struct ProtoFlattenedSerializerPolymorphicField {
    #[prost(int32, optional, tag = "1")]
    pub polymorphic_field_serializer_name_sym: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub polymorphic_field_serializer_version: Option<i32>,
}

#[derive(Clone, PartialEq, Message)]
pub struct ProtoFlattenedSerializerField {
    #[prost(int32, optional, tag = "1")]
    pub var_type_sym: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub var_name_sym: Option<i32>,
    #[prost(int32, optional, tag = "3")]
    pub bit_count: Option<i32>,
    #[prost(float, optional, tag = "4")]
    pub low_value: Option<f32>,
    #[prost(float, optional, tag = "5")]
    pub high_value: Option<f32>,
    #[prost(int32, optional, tag = "6")]
    pub encode_flags: Option<i32>,
    #[prost(int32, optional, tag = "7")]
    pub field_serializer_name_sym: Option<i32>,
    #[prost(int32, optional, tag = "8")]
    pub field_serializer_version: Option<i32>,
    #[prost(int32, optional, tag = "9")]
    pub send_node_sym: Option<i32>,
    #[prost(int32, optional, tag = "10")]
    pub var_encoder_sym: Option<i32>,
    #[prost(message, repeated, tag = "11")]
    pub polymorphic_types: Vec<ProtoFlattenedSerializerPolymorphicField>,
    #[prost(int32, optional, tag = "12")]
    pub var_serializer_sym: Option<i32>,
    #[prost(message, optional, tag = "13")]
    pub var_enum_info: Option<ProtoFlattenedSerializerEnumInfo>,
}

#[derive(Clone, PartialEq, Message)]
pub struct ProtoFlattenedSerializer {
    #[prost(int32, optional, tag = "1")]
    pub serializer_name_sym: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub serializer_version: Option<i32>,
    #[prost(int32, repeated, packed = "false", tag = "3")]
    pub fields_index: Vec<i32>,
}

#[derive(Clone, PartialEq, Message)]
pub struct ProtoCoordSizeParams {
    #[prost(int32, optional, tag = "1")]
    pub coord_integer_bits: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub coord_fractional_bits: Option<i32>,
    #[prost(int32, optional, tag = "3")]
    pub coord_integer_bits_mp: Option<i32>,
    #[prost(int32, optional, tag = "4")]
    pub coord_fractional_bits_mp: Option<i32>,
    #[prost(int32, optional, tag = "5")]
    pub normal_fractional_bits: Option<i32>,
    #[prost(int32, optional, tag = "6")]
    pub angle_bits: Option<i32>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgFlattenedSerializer {
    #[prost(message, repeated, tag = "1")]
    pub serializers: Vec<ProtoFlattenedSerializer>,
    #[prost(string, repeated, tag = "2")]
    pub symbols: Vec<String>,
    #[prost(message, repeated, tag = "3")]
    pub fields: Vec<ProtoFlattenedSerializerField>,
    #[prost(message, optional, tag = "4")]
    pub coord_size_params: Option<ProtoCoordSizeParams>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgCreateStringTable {
    #[prost(string, optional, tag = "1")]
    pub name: Option<String>,
    #[prost(int32, optional, tag = "2")]
    pub num_entries: Option<i32>,
    #[prost(bool, optional, tag = "3")]
    pub user_data_fixed_size: Option<bool>,
    #[prost(int32, optional, tag = "4")]
    pub user_data_size: Option<i32>,
    #[prost(int32, optional, tag = "5")]
    pub user_data_size_bits: Option<i32>,
    #[prost(int32, optional, tag = "6")]
    pub flags: Option<i32>,
    #[prost(bytes = "vec", optional, tag = "7")]
    pub string_data: Option<Vec<u8>>,
    #[prost(int32, optional, tag = "8")]
    pub uncompressed_size: Option<i32>,
    #[prost(bool, optional, tag = "9")]
    pub data_compressed: Option<bool>,
    #[prost(bool, optional, tag = "10")]
    pub using_varint_bitcounts: Option<bool>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgUpdateStringTable {
    #[prost(int32, optional, tag = "1")]
    pub table_id: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub num_changed_entries: Option<i32>,
    #[prost(bytes = "vec", optional, tag = "3")]
    pub string_data: Option<Vec<u8>>,
}

#[derive(Clone, PartialEq, Message)]
pub struct AlternateBaseline {
    #[prost(int32, optional, tag = "1")]
    pub entity_index: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub baseline_index: Option<i32>,
}

#[derive(Clone, PartialEq, Message)]
pub struct NonTransmittedEntities {
    #[prost(int32, optional, tag = "1")]
    pub header_count: Option<i32>,
    #[prost(bytes = "vec", optional, tag = "2")]
    pub data: Option<Vec<u8>>,
}

#[derive(Clone, PartialEq, Message)]
pub struct OutOfPvsEntityUpdates {
    #[prost(int32, optional, tag = "1")]
    pub count: Option<i32>,
    #[prost(bytes = "vec", optional, tag = "2")]
    pub data: Option<Vec<u8>>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CSvcMsgPacketEntities {
    #[prost(int32, optional, tag = "1")]
    pub max_entries: Option<i32>,
    #[prost(int32, optional, tag = "2")]
    pub updated_entries: Option<i32>,
    #[prost(bool, optional, tag = "3")]
    pub legacy_is_delta: Option<bool>,
    #[prost(bool, optional, tag = "4")]
    pub update_baseline: Option<bool>,
    #[prost(int32, optional, tag = "5")]
    pub baseline: Option<i32>,
    #[prost(int32, optional, tag = "6")]
    pub delta_from: Option<i32>,
    #[prost(bytes = "vec", optional, tag = "7")]
    pub entity_data: Option<Vec<u8>>,
    #[prost(bool, optional, tag = "8")]
    pub pending_full_frame: Option<bool>,
    #[prost(uint32, optional, tag = "9")]
    pub active_spawngroup_handle: Option<u32>,
    #[prost(uint32, optional, tag = "10")]
    pub max_spawngroup_creationsequence: Option<u32>,
    #[prost(uint32, optional, tag = "12")]
    pub server_tick: Option<u32>,
    #[prost(bytes = "vec", optional, tag = "13")]
    pub serialized_entities: Option<Vec<u8>>,
    #[prost(message, repeated, tag = "15")]
    pub alternate_baselines: Vec<AlternateBaseline>,
    #[prost(message, optional, tag = "19")]
    pub non_transmitted_entities: Option<NonTransmittedEntities>,
    #[prost(message, optional, tag = "23")]
    pub outofpvs_entity_updates: Option<OutOfPvsEntityUpdates>,
}

#[derive(Clone, PartialEq, Message)]
pub struct GameEventKeyDescriptor {
    #[prost(int32, optional, tag = "1")]
    pub r#type: Option<i32>,
    #[prost(string, optional, tag = "2")]
    pub name: Option<String>,
}

#[derive(Clone, PartialEq, Message)]
pub struct GameEventDescriptor {
    #[prost(int32, optional, tag = "1")]
    pub eventid: Option<i32>,
    #[prost(string, optional, tag = "2")]
    pub name: Option<String>,
    #[prost(message, repeated, tag = "3")]
    pub keys: Vec<GameEventKeyDescriptor>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CMsgSource1LegacyGameEventList {
    #[prost(message, repeated, tag = "1")]
    pub descriptors: Vec<GameEventDescriptor>,
}

#[derive(Clone, PartialEq, Message)]
pub struct GameEventKeyValue {
    #[prost(int32, optional, tag = "1")]
    pub r#type: Option<i32>,
    #[prost(string, optional, tag = "2")]
    pub val_string: Option<String>,
    #[prost(float, optional, tag = "3")]
    pub val_float: Option<f32>,
    #[prost(int32, optional, tag = "4")]
    pub val_long: Option<i32>,
    #[prost(int32, optional, tag = "5")]
    pub val_short: Option<i32>,
    #[prost(int32, optional, tag = "6")]
    pub val_byte: Option<i32>,
    #[prost(bool, optional, tag = "7")]
    pub val_bool: Option<bool>,
    #[prost(uint64, optional, tag = "8")]
    pub val_uint64: Option<u64>,
}

#[derive(Clone, PartialEq, Message)]
pub struct CMsgSource1LegacyGameEvent {
    #[prost(string, optional, tag = "1")]
    pub event_name: Option<String>,
    #[prost(int32, optional, tag = "2")]
    pub eventid: Option<i32>,
    #[prost(message, repeated, tag = "3")]
    pub keys: Vec<GameEventKeyValue>,
    #[prost(int32, optional, tag = "4")]
    pub server_tick: Option<i32>,
    #[prost(int32, optional, tag = "5")]
    pub passthrough: Option<i32>,
}
