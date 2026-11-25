use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use super::field_codec::{CoordinateProfile, FieldCodec, FieldEncoding};
use super::schema_profile::{
    field_serializer_fallback, is_pointer_field_name, lookup_boxed_type, lookup_custom,
    lookup_enum_signed, lookup_primitive, remap_type_alias,
};
use crate::wire::proto::{CSvcMsgFlattenedSerializer, ProtoFlattenedSerializerField};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContainerKind {
    Fixed(usize),
    Vector,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FieldKind {
    Scalar,
    Struct,
    Pointer,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PathOperation {
    Value,
    Pointer,
    Array,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetadataValue {
    ArrayLen(u32),
    Selector(u32),
}

#[derive(Debug, Clone)]
pub struct SchemaField {
    pub name: String,
    pub send_node: String,
    pub type_name: String,
    pub base_type: String,
    pub container: Option<ContainerKind>,
    pub kind: FieldKind,
    pub serializer: Option<usize>,
    pub variants: Vec<usize>,
    pub codec: Option<FieldCodec>,
}

#[derive(Debug, Clone)]
pub struct Serializer {
    pub name: String,
    pub version: i32,
    pub fields: Vec<Arc<SchemaField>>,
}

#[derive(Debug, Clone)]
pub struct Ancestor<'a> {
    pub kind_is_pointer: bool,
    pub field: &'a Arc<SchemaField>,
    pub path: Vec<u16>,
}

#[derive(Debug, Clone)]
pub struct ResolvedPath<'a> {
    pub field: &'a Arc<SchemaField>,
    pub operation: PathOperation,
    pub ancestors: Vec<Ancestor<'a>>,
}

#[derive(Debug, Clone)]
pub struct Schema {
    pub coordinate_profile: CoordinateProfile,
    pub class_id_bits: u8,
    pub max_classes: usize,
    serializers: Vec<Serializer>,
    classes: Vec<Option<usize>>,
}

struct ParsedShape {
    element: String,
    container: Option<ContainerKind>,
    atomic_string: bool,
}

const VECTOR_NAMES: &[&str] = &[
    "CNetworkUtlVectorBase",
    "CUtlVectorEmbeddedNetworkVar",
    "C_NetworkUtlVectorBase",
    "C_UtlVectorEmbeddedNetworkVar",
    "CUtlVector",
];

fn parse_shape(type_str: &str) -> Result<ParsedShape, String> {
    let value = type_str.trim();
    if let Some(open_bracket) = value.rfind('[') {
        if value.ends_with(']') {
            let num_str = &value[open_bracket + 1..value.len() - 1];
            if !num_str.is_empty() && num_str.bytes().all(|b| b.is_ascii_digit()) {
                let size: usize = num_str
                    .parse()
                    .map_err(|_| "Fixed array extent budget".to_string())?;
                if !(1..=32767).contains(&size) {
                    return Err("Fixed array extent budget".into());
                }
                let element = value[..open_bracket].trim();
                if element.ends_with(']') && element.contains('[') {
                    return Err("Unsupported nested fixed array shape".into());
                }
                if element == "char" && size > 1 {
                    return Ok(ParsedShape {
                        element: "char".into(),
                        container: None,
                        atomic_string: true,
                    });
                }
                return Ok(ParsedShape {
                    element: element.to_string(),
                    container: Some(ContainerKind::Fixed(size)),
                    atomic_string: false,
                });
            }
        }
    }
    if let Some(open) = value.find('<') {
        let prefix = value[..open].trim();
        if VECTOR_NAMES.contains(&prefix) {
            if !value.ends_with('>') {
                return Err("Malformed vector type".into());
            }
            let args = &value[open + 1..value.len() - 1];
            let mut depth = 0i32;
            let mut end = args.len();
            for (i, ch) in args.char_indices() {
                match ch {
                    '<' => depth += 1,
                    '>' => {
                        depth -= 1;
                        if depth < 0 {
                            return Err("Malformed vector argument".into());
                        }
                    }
                    ',' if depth == 0 => {
                        end = i;
                        break;
                    }
                    _ => {}
                }
            }
            if depth != 0 {
                return Err("Malformed vector argument".into());
            }
            let element = args[..end].trim();
            if element.is_empty() {
                return Err("Missing vector element".into());
            }
            return Ok(ParsedShape {
                element: element.to_string(),
                container: Some(ContainerKind::Vector),
                atomic_string: false,
            });
        }
    }
    Ok(ParsedShape {
        element: value.to_string(),
        container: None,
        atomic_string: false,
    })
}

fn serializer_key(name: &str, version: i32) -> Result<String, String> {
    if name.is_empty() || name.contains('\0') || version < 0 {
        return Err("Invalid serializer identity".into());
    }
    Ok(format!("{}\0{}", name.to_ascii_lowercase(), version))
}

impl Schema {
    pub fn build(
        message: &CSvcMsgFlattenedSerializer,
        classes: &[(i32, String)],
        max_classes: usize,
    ) -> Result<Self, String> {
        if !(1..=65536).contains(&max_classes) {
            return Err("Class count budget".into());
        }
        if message.symbols.len() > 250_000
            || message.fields.len() > 100_000
            || message.serializers.len() > 8192
            || classes.len() > max_classes
        {
            return Err("Schema graph budget".into());
        }
        let class_id_bits = (32 - (max_classes as u32).leading_zeros()) as u8;
        let coordinate_profile = CoordinateProfile::from_proto(message.coord_size_params.as_ref())?;

        let get_symbol = |idx: Option<i32>, required: bool| -> Result<Option<String>, String> {
            let Some(i) = idx else {
                if required {
                    return Err("Missing schema symbol".into());
                }
                return Ok(None);
            };
            if i < 0 || (i as usize) >= message.symbols.len() {
                return Err("Invalid schema symbol index".into());
            }
            let val = &message.symbols[i as usize];
            if val.len() > 4096 || val.contains('\0') {
                return Err("Invalid schema symbol".into());
            }
            Ok(Some(val.clone()))
        };

        struct RawNode {
            name: String,
            version: i32,
            field_indices: Vec<usize>,
        }
        let mut nodes: Vec<RawNode> = Vec::new();
        let mut node_map: HashMap<String, usize> = HashMap::new();
        let mut refs = 0usize;

        for s in &message.serializers {
            let name = get_symbol(s.serializer_name_sym, true)?.unwrap();
            let version = s.serializer_version.unwrap_or(0);
            let id = serializer_key(&name, version)?;
            refs += s.fields_index.len();
            if refs > 1_000_000 {
                return Err("Serializer reference budget".into());
            }
            let mut indices = Vec::with_capacity(s.fields_index.len());
            for &fi in &s.fields_index {
                if fi < 0 || (fi as usize) >= message.fields.len() {
                    return Err("Invalid serializer field index".into());
                }
                indices.push(fi as usize);
            }
            if let Some(&existing_idx) = node_map.get(&id) {
                if nodes[existing_idx].field_indices != indices {
                    return Err("Conflicting duplicate serializer identity".into());
                }
            } else {
                let idx = nodes.len();
                node_map.insert(id, idx);
                nodes.push(RawNode {
                    name,
                    version,
                    field_indices: indices,
                });
            }
        }

        let resolve_ref =
            |name_idx: Option<i32>, version: Option<i32>| -> Result<Option<usize>, String> {
                let Some(ni) = name_idx else {
                    return Ok(None);
                };
                let name = get_symbol(Some(ni), true)?.unwrap();
                let id = serializer_key(&name, version.unwrap_or(0))?;
                let idx = node_map
                    .get(&id)
                    .copied()
                    .ok_or_else(|| "Unresolved versioned serializer".to_string())?;
                Ok(Some(idx))
            };

        let mut class_vec: Vec<Option<usize>> = vec![None; max_classes];
        let mut queue: Vec<usize> = Vec::new();
        let mut queued: HashSet<usize> = HashSet::new();

        for (cid, cname) in classes {
            if *cid < 0 || (*cid as usize) >= max_classes || cname.is_empty() {
                return Err("Invalid class declaration".into());
            }
            let cu = *cid as usize;
            if class_vec[cu].is_some() {
                return Err("Invalid class declaration".into());
            }
            let id = serializer_key(cname, 0)?;
            let node_idx = node_map
                .get(&id)
                .copied()
                .ok_or_else(|| "Missing version0 class root".to_string())?;
            class_vec[cu] = Some(node_idx);
            if queued.insert(node_idx) {
                queue.push(node_idx);
            }
        }

        let build_field = |f: &ProtoFlattenedSerializerField| -> Result<Arc<SchemaField>, String> {
            let name = get_symbol(f.var_name_sym, true)?.unwrap();
            let type_name = get_symbol(f.var_type_sym, true)?.unwrap();
            let send_raw = get_symbol(f.send_node_sym, false)?;
            let send_node = match send_raw.as_deref() {
                None | Some("") | Some("(root)") => String::new(),
                Some(s) => s.to_string(),
            };
            let parsed = parse_shape(&type_name)?;
            let pointer = parsed.element.ends_with('*') || is_pointer_field_name(&name);
            let element = if parsed.element.ends_with('*') {
                parsed.element[..parsed.element.len() - 1]
                    .trim()
                    .to_string()
            } else {
                parsed.element
            };
            let base_type = remap_type_alias(&element)?;
            let serializer = resolve_ref(f.field_serializer_name_sym, f.field_serializer_version)?;
            if f.polymorphic_types.len() > 8192 {
                return Err("Polymorphic type budget".into());
            }
            let mut variants = Vec::with_capacity(f.polymorphic_types.len());
            for v in &f.polymorphic_types {
                let vid = resolve_ref(
                    v.polymorphic_field_serializer_name_sym,
                    v.polymorphic_field_serializer_version,
                )?
                .ok_or_else(|| "Missing polymorphic serializer".to_string())?;
                variants.push(vid);
            }
            let explicit_custom = get_symbol(f.var_serializer_sym, false)?;
            let custom = explicit_custom
                .as_deref()
                .and_then(|s| lookup_custom(&s.to_ascii_lowercase()))
                .or_else(|| {
                    field_serializer_fallback(&name.to_ascii_lowercase())
                        .and_then(|s| lookup_custom(&s.to_ascii_lowercase()))
                });

            let kind = match serializer {
                Some(_) => {
                    if pointer {
                        FieldKind::Pointer
                    } else {
                        FieldKind::Struct
                    }
                }
                None => FieldKind::Scalar,
            };

            let mut codec = None;
            if kind == FieldKind::Scalar {
                if !variants.is_empty() {
                    return Err("Polymorphic scalar has no serializer".into());
                }
                let base_lower = base_type.to_ascii_lowercase();
                let mut wtype = if let Some(ref ei) = f.var_enum_info {
                    Some(super::schema_profile::WireType {
                        category: if ei.is_signed_enum.unwrap_or(false) {
                            1
                        } else {
                            2
                        },
                        dimensions: 1,
                    })
                } else if let Some(signed) = lookup_enum_signed(&base_lower) {
                    Some(super::schema_profile::WireType {
                        category: if signed { 1 } else { 2 },
                        dimensions: 1,
                    })
                } else if parsed.atomic_string {
                    Some(super::schema_profile::WireType {
                        category: 5,
                        dimensions: 1,
                    })
                } else {
                    let normalized = if let Some(b) = lookup_boxed_type(&base_lower) {
                        b
                    } else if base_type.starts_with("CStrongHandle") {
                        "uint64"
                    } else if base_type == "CNetworkedQuantizedFloat" {
                        "float32"
                    } else {
                        base_lower.as_str()
                    };
                    lookup_primitive(normalized)
                };
                if let Some((_, cwt)) = custom {
                    wtype = Some(cwt);
                }
                let wt =
                    wtype.ok_or_else(|| format!("Unsupported native field type: {base_type}"))?;
                let encoder =
                    get_symbol(f.var_encoder_sym, false)?.unwrap_or_else(|| "default".into());
                let encoding = FieldEncoding {
                    category: wt.category,
                    dimensions: wt.dimensions,
                    encoder,
                    bit_count: f.bit_count,
                    encode_flags: f.encode_flags,
                    low_value: f.low_value,
                    high_value: f.high_value,
                };
                codec = Some(FieldCodec::create(&encoding, coordinate_profile)?);
            } else if !variants.is_empty() && kind != FieldKind::Pointer {
                return Err("Unsupported by-value polymorphic field".into());
            }

            Ok(Arc::new(SchemaField {
                name,
                send_node,
                type_name,
                base_type,
                container: parsed.container,
                kind,
                serializer,
                variants,
                codec,
            }))
        };

        let mut built_fields: HashMap<usize, Arc<SchemaField>> = HashMap::new();
        let mut serializers: Vec<Option<Serializer>> = vec![None; nodes.len()];

        let mut qi = 0;
        while qi < queue.len() {
            let node_idx = queue[qi];
            qi += 1;
            if serializers[node_idx].is_some() {
                continue;
            }
            let node = &nodes[node_idx];
            let mut fields = Vec::with_capacity(node.field_indices.len());
            for &fi in &node.field_indices {
                let f = match built_fields.get(&fi) {
                    Some(existing) => existing.clone(),
                    None => {
                        let built = build_field(&message.fields[fi])?;
                        built_fields.insert(fi, built.clone());
                        built
                    }
                };
                if let Some(sidx) = f.serializer {
                    if queued.insert(sidx) {
                        queue.push(sidx);
                    }
                }
                for &vidx in &f.variants {
                    if queued.insert(vidx) {
                        queue.push(vidx);
                    }
                }
                fields.push(f);
            }
            serializers[node_idx] = Some(Serializer {
                name: node.name.clone(),
                version: node.version,
                fields,
            });
            if queue.len() > 1_000_000 {
                return Err("Schema traversal budget".into());
            }
        }

        // Cycle check for by-value struct serializers
        let mut visiting = HashSet::new();
        let mut visited = HashSet::new();
        for first in 0..serializers.len() {
            if serializers[first].is_none() || visited.contains(&first) {
                continue;
            }
            let mut stack = vec![(first, false)];
            while let Some((cur, exit)) = stack.pop() {
                if exit {
                    visiting.remove(&cur);
                    visited.insert(cur);
                    continue;
                }
                if visiting.contains(&cur) {
                    return Err("Recursive by-value serializer".into());
                }
                if visited.contains(&cur) {
                    continue;
                }
                visiting.insert(cur);
                stack.push((cur, true));
                if let Some(ser) = &serializers[cur] {
                    for f in &ser.fields {
                        if f.kind == FieldKind::Struct && f.container != Some(ContainerKind::Vector)
                        {
                            if let Some(sidx) = f.serializer {
                                stack.push((sidx, false));
                            }
                        }
                    }
                }
            }
        }

        let final_serializers = serializers
            .into_iter()
            .map(|s| {
                s.unwrap_or(Serializer {
                    name: String::new(),
                    version: 0,
                    fields: Vec::new(),
                })
            })
            .collect();

        Ok(Self {
            coordinate_profile,
            class_id_bits,
            max_classes,
            serializers: final_serializers,
            classes: class_vec,
        })
    }

    pub fn field_count_total(&self) -> usize {
        self.serializers.iter().map(|s| s.fields.len()).sum()
    }

    pub fn get_class(&self, class_id: usize) -> Result<&Serializer, String> {
        let sidx = self
            .classes
            .get(class_id)
            .and_then(|o| *o)
            .ok_or_else(|| "Unknown class ID".to_string())?;
        Ok(&self.serializers[sidx])
    }

    pub fn resolve<'a, F>(
        &'a self,
        class_id: usize,
        path: &[u16],
        mut metadata: F,
    ) -> Result<ResolvedPath<'a>, String>
    where
        F: FnMut(&[u16]) -> Option<MetadataValue>,
    {
        if path.is_empty() || path.len() > 10 || path[0] == 32767 || path.iter().any(|&v| v > 32767)
        {
            return Err("Invalid field path".into());
        }
        let mut node = self.get_class(class_id)?;
        let mut cursor = 0usize;
        let mut ancestors = Vec::new();

        while cursor < path.len() {
            let fidx = path[cursor] as usize;
            let field = node
                .fields
                .get(fidx)
                .ok_or_else(|| "Unresolved field path".to_string())?;
            let prefix = &path[..cursor + 1];
            cursor += 1;

            if let Some(container) = field.container {
                if cursor == path.len() {
                    return Ok(ResolvedPath {
                        field,
                        operation: PathOperation::Array,
                        ancestors,
                    });
                }
                ancestors.push(Ancestor {
                    kind_is_pointer: false,
                    field,
                    path: prefix.to_vec(),
                });
                let index = path[cursor] as u32;
                cursor += 1;
                let known = metadata(prefix);
                let size = match container {
                    ContainerKind::Fixed(s) => Some(s as u32),
                    ContainerKind::Vector => match known {
                        Some(MetadataValue::ArrayLen(s)) => Some(s),
                        _ => None,
                    },
                };
                if let Some(sz) = size {
                    if index >= sz {
                        return Err("Array field path out of bounds".into());
                    }
                }
            }

            if cursor == path.len() {
                if field.kind == FieldKind::Struct {
                    return Err("Field path ends at by-value serializer".into());
                }
                let op = if field.kind == FieldKind::Pointer {
                    PathOperation::Pointer
                } else {
                    PathOperation::Value
                };
                return Ok(ResolvedPath {
                    field,
                    operation: op,
                    ancestors,
                });
            }

            let mut target = field
                .serializer
                .ok_or_else(|| "Scalar field path has descendants".to_string())?;
            if field.kind == FieldKind::Pointer {
                ancestors.push(Ancestor {
                    kind_is_pointer: true,
                    field,
                    path: path[..cursor].to_vec(),
                });
            }
            if !field.variants.is_empty() {
                if let Some(MetadataValue::Selector(sel)) = metadata(&path[..cursor]) {
                    if sel == 0 || (sel as usize) > field.variants.len() {
                        return Err("Invalid active polymorphic selector".into());
                    }
                    target = field.variants[(sel - 1) as usize];
                }
            }
            node = &self.serializers[target];
        }
        Err("Incomplete field path".into())
    }
}
