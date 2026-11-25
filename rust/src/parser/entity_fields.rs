use std::collections::HashMap;
use std::sync::Arc;

use super::field_codec::FieldValue;
use super::field_paths::read_field_paths;
use super::schema::{MetadataValue, PathOperation, Schema, SchemaField};
use crate::wire::bits::BitReader;

const MAX_PATHS: usize = 65536;
const MAX_ARRAY_LEN: usize = 65536;
const MAX_RECORDS: usize = 262144;

#[derive(Debug, Clone)]
pub struct FieldRecord {
    pub path: Vec<u16>,
    pub field: Arc<SchemaField>,
    pub operation: PathOperation,
    pub value: FieldValue,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PointerState {
    pub present: bool,
    pub selector: Option<u32>,
}

#[derive(Debug, Clone)]
pub struct EntityFields {
    pub class_id: usize,
    pub values: HashMap<Vec<u16>, FieldRecord>,
    pub metadata: HashMap<Vec<u16>, MetadataValue>,
    pub pointers: HashMap<Vec<u16>, PointerState>,
}

impl EntityFields {
    pub fn empty(class_id: usize) -> Self {
        Self {
            class_id,
            values: HashMap::new(),
            metadata: HashMap::new(),
            pointers: HashMap::new(),
        }
    }

    pub fn field_by_name(&self, name: &str) -> Option<&FieldValue> {
        let mut found = None;
        let mut count = 0usize;
        for rec in self.values.values() {
            if rec.operation == PathOperation::Value && rec.field.name == name {
                found = Some(&rec.value);
                count += 1;
            }
        }
        if count == 1 {
            found
        } else {
            None
        }
    }

    fn remove_descendants(&mut self, prefix: &[u16], minimum_index: Option<u16>) {
        let matches = |candidate: &[u16]| -> bool {
            if candidate.len() <= prefix.len() || !candidate.starts_with(prefix) {
                return false;
            }
            match minimum_index {
                None => true,
                Some(min_idx) => candidate[prefix.len()] >= min_idx,
            }
        };
        self.values.retain(|k, _| !matches(k));
        self.pointers.retain(|k, _| !matches(k));
    }

    pub fn apply_to(&self, schema: &Schema, target: &mut EntityFields) -> Result<(), String> {
        if target.class_id != self.class_id {
            return Err("Entity schema identity mismatch".into());
        }
        let mut sorted: Vec<&FieldRecord> = self.values.values().collect();
        sorted.sort_by(|a, b| a.path.cmp(&b.path));

        for record in sorted {
            let resolved = schema.resolve(self.class_id, &record.path, |p| {
                self.metadata.get(p).copied()
            })?;
            for ancestor in &resolved.ancestors {
                if !ancestor.kind_is_pointer {
                    continue;
                }
                let next = self
                    .pointers
                    .get(&ancestor.path)
                    .copied()
                    .filter(|p| p.present)
                    .ok_or_else(|| "Stored field below absent pointer".to_string())?;
                let old = target.pointers.get(&ancestor.path).copied();
                if old
                    .map(|o| !o.present || o.selector != next.selector)
                    .unwrap_or(true)
                {
                    target.remove_descendants(&ancestor.path, None);
                }
                target.pointers.insert(ancestor.path.clone(), next);
                if next.selector.is_none() {
                    target.metadata.remove(&ancestor.path);
                }
            }
            if record.operation == PathOperation::Array {
                if let FieldValue::ArrayLen(len) = record.value {
                    target.remove_descendants(&record.path, Some(len as u16));
                }
            } else if record.operation == PathOperation::Pointer {
                let next = self
                    .pointers
                    .get(&record.path)
                    .copied()
                    .ok_or_else(|| "Missing stored pointer state".to_string())?;
                let old = target.pointers.get(&record.path).copied();
                if !next.present
                    || old
                        .map(|o| !o.present || o.selector != next.selector)
                        .unwrap_or(true)
                {
                    target.remove_descendants(&record.path, None);
                }
                target.pointers.insert(record.path.clone(), next);
            }
            target.values.insert(record.path.clone(), record.clone());
        }
        for (k, v) in &self.metadata {
            target.metadata.insert(k.clone(), *v);
        }
        for (k, v) in &self.pointers {
            target.pointers.entry(k.clone()).or_insert(*v);
        }
        if target.values.len() > MAX_RECORDS
            || target.metadata.len() > MAX_RECORDS
            || target.pointers.len() > MAX_RECORDS
        {
            return Err("Entity field storage budget".into());
        }
        Ok(())
    }

    pub fn decode_in_place(
        &mut self,
        schema: &Schema,
        reader: &mut BitReader<'_>,
        bit_length: Option<usize>,
    ) -> Result<(), String> {
        let initial_bits = reader.remaining_bits();
        if let Some(bl) = bit_length {
            if bl > initial_bits {
                return Err("Invalid entity field bit length".into());
            }
        }
        let budget = bit_length.unwrap_or(initial_bits);
        let paths = read_field_paths(reader, MAX_PATHS, budget)?;

        for path in paths {
            let resolved =
                schema.resolve(self.class_id, &path, |p| self.metadata.get(p).copied())?;
            for ancestor in &resolved.ancestors {
                if ancestor.kind_is_pointer
                    && self
                        .pointers
                        .get(&ancestor.path)
                        .map(|p| !p.present)
                        .unwrap_or(false)
                {
                    return Err("Field below absent pointer".into());
                }
            }
            let field = resolved.field.clone();
            let op = resolved.operation;
            let ancestors_paths: Vec<(bool, Vec<u16>)> = resolved
                .ancestors
                .iter()
                .map(|a| (a.kind_is_pointer, a.path.clone()))
                .collect();

            let value = match op {
                PathOperation::Array => {
                    let container = field
                        .container
                        .ok_or_else(|| "Missing array definition".to_string())?;
                    let size = match container {
                        super::schema::ContainerKind::Fixed(s) => s as u32,
                        super::schema::ContainerKind::Vector => {
                            reader.read_varuint32().map_err(|e| e.to_string())?
                        }
                    };
                    if (size as usize) > MAX_ARRAY_LEN {
                        return Err("Array length budget".into());
                    }
                    self.remove_descendants(&path, Some(size as u16));
                    self.metadata
                        .insert(path.clone(), MetadataValue::ArrayLen(size));
                    FieldValue::ArrayLen(size)
                }
                PathOperation::Pointer => {
                    let present = reader.read_bool().map_err(|e| e.to_string())?;
                    let mut selector = None;
                    if present && !field.variants.is_empty() {
                        let sel = reader.read_ubitvar().map_err(|e| e.to_string())?;
                        if sel == 0 || (sel as usize) > field.variants.len() {
                            return Err("Invalid polymorphic pointer selector".into());
                        }
                        selector = Some(sel);
                    }
                    let old = self.pointers.get(&path).copied();
                    if !present
                        || old
                            .map(|o| !o.present || o.selector != selector)
                            .unwrap_or(true)
                    {
                        self.remove_descendants(&path, None);
                    }
                    self.pointers
                        .insert(path.clone(), PointerState { present, selector });
                    if let Some(sel) = selector {
                        self.metadata
                            .insert(path.clone(), MetadataValue::Selector(sel));
                    }
                    FieldValue::Pointer(present)
                }
                PathOperation::Value => {
                    let codec = field
                        .codec
                        .as_ref()
                        .ok_or_else(|| "Missing field codec".to_string())?;
                    codec.decode(reader).map_err(|e| e.to_string())?
                }
            };

            if initial_bits - reader.remaining_bits() > budget {
                return Err("Entity field boundary exceeded".into());
            }

            for (is_ptr, apath) in ancestors_paths {
                if !is_ptr {
                    continue;
                }
                if !self.pointers.contains_key(&apath) {
                    let active_sel = match self.metadata.get(&apath).copied() {
                        Some(MetadataValue::Selector(s)) => Some(s),
                        _ => None,
                    };
                    self.pointers.insert(
                        apath,
                        PointerState {
                            present: true,
                            selector: active_sel,
                        },
                    );
                }
            }

            self.values.insert(
                path.clone(),
                FieldRecord {
                    path,
                    field,
                    operation: op,
                    value,
                },
            );

            if self.values.len() > MAX_RECORDS
                || self.metadata.len() > MAX_RECORDS
                || self.pointers.len() > MAX_RECORDS
            {
                return Err("Entity field storage budget".into());
            }
        }

        let consumed = initial_bits - reader.remaining_bits();
        if let Some(bl) = bit_length {
            if consumed != bl {
                return Err("Entity field length mismatch".into());
            }
        }
        Ok(())
    }
}
