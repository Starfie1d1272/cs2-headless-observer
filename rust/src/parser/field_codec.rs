use super::quantized_float::{create_field_quantizer, decode_quantized, Quantizer};
use crate::wire::bits::{BitReader, WireError};
use crate::wire::proto::ProtoCoordSizeParams;

#[derive(Debug, Clone, PartialEq)]
pub enum FloatVal {
    Finite(f32),
    NonFinite(u32),
}

impl FloatVal {
    pub fn as_finite(&self) -> Option<f32> {
        match self {
            FloatVal::Finite(v) => Some(*v),
            FloatVal::NonFinite(_) => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum FieldValue {
    None,
    Bool(bool),
    Int(i64),
    Uint(u64),
    Float(FloatVal),
    FloatVec(Vec<FloatVal>),
    Bytes(Vec<u8>),
    ArrayLen(u32),
    Pointer(bool),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CoordinateProfile {
    pub integer: u8,
    pub fraction: u8,
    pub integer_mp: u8,
    pub fraction_mp: u8,
    pub normal: u8,
    pub angle: u8,
}

impl Default for CoordinateProfile {
    fn default() -> Self {
        Self {
            integer: 14,
            fraction: 5,
            integer_mp: 11,
            fraction_mp: 3,
            normal: 11,
            angle: 20,
        }
    }
}

impl CoordinateProfile {
    pub fn from_proto(params: Option<&ProtoCoordSizeParams>) -> Result<Self, String> {
        let Some(p) = params else {
            return Ok(Self::default());
        };
        let vals = [
            p.coord_integer_bits,
            p.coord_fractional_bits,
            p.coord_integer_bits_mp,
            p.coord_fractional_bits_mp,
            p.normal_fractional_bits,
            p.angle_bits,
        ];
        for v in vals {
            match v {
                Some(x) if (1..=31).contains(&x) => {}
                _ => return Err("Invalid coordinate profile".into()),
            }
        }
        let integer = vals[0].unwrap() as u8;
        let fraction = vals[1].unwrap() as u8;
        let integer_mp = vals[2].unwrap() as u8;
        let fraction_mp = vals[3].unwrap() as u8;
        let normal = vals[4].unwrap() as u8;
        let angle = vals[5].unwrap() as u8;
        if integer.max(integer_mp) + 3 + fraction.max(fraction_mp) > 32 {
            return Err("Coordinate profile bit budget".into());
        }
        Ok(Self {
            integer,
            fraction,
            integer_mp,
            fraction_mp,
            normal,
            angle,
        })
    }
}

#[derive(Debug, Clone)]
pub struct FieldEncoding {
    pub category: u8,
    pub dimensions: u8,
    pub encoder: String,
    pub bit_count: Option<i32>,
    pub encode_flags: Option<i32>,
    pub low_value: Option<f32>,
    pub high_value: Option<f32>,
}

#[derive(Debug, Clone)]
pub enum FieldCodec {
    Noop,
    Bool,
    FloatRaw,
    FloatQuantized {
        dim: u8,
        q: Quantizer,
    },
    Coord {
        dim: u8,
        integral: bool,
        profile: CoordinateProfile,
    },
    Normal {
        profile: CoordinateProfile,
    },
    QAngleCoord {
        profile: CoordinateProfile,
    },
    QAnglePrecise {
        profile: CoordinateProfile,
    },
    QAngleBits {
        count: u8,
        width: u8,
        raw: bool,
    },
    IntVarint {
        signed: bool,
    },
    IntFixed8 {
        signed: bool,
    },
    IntFixed32 {
        signed: bool,
    },
    IntFixed64 {
        signed: bool,
    },
    Binary {
        limit: usize,
    },
    StringNul {
        limit: usize,
    },
}

fn read_raw_f32(r: &mut BitReader<'_>) -> Result<FloatVal, WireError> {
    let bits = r.read_bits(32)?;
    if (bits & 0x7f80_0000) == 0x7f80_0000 {
        Ok(FloatVal::NonFinite(bits))
    } else {
        Ok(FloatVal::Finite(f32::from_bits(bits)))
    }
}

fn read_coord(r: &mut BitReader<'_>, p: &CoordinateProfile) -> Result<f32, WireError> {
    let integer = r.read_bool()?;
    let fraction = r.read_bool()?;
    if !integer && !fraction {
        return Ok(0.0);
    }
    let negative = r.read_bool()?;
    let whole = if integer {
        r.read_bits(p.integer)? + 1
    } else {
        0
    };
    let part = if fraction {
        (r.read_bits(p.fraction)? as f32) * 2.0f32.powi(-(p.fraction as i32))
    } else {
        0.0
    };
    let val = (whole as f32) + part;
    Ok(if negative { -val } else { val })
}

fn read_integral(r: &mut BitReader<'_>, p: &CoordinateProfile) -> Result<f32, WireError> {
    let compact = r.read_bool()?;
    if !r.read_bool()? {
        return Ok(0.0);
    }
    let negative = r.read_bool()?;
    let bits = if compact { p.integer_mp } else { p.integer };
    let val = (r.read_bits(bits)? + 1) as f32;
    Ok(if negative { -val } else { val })
}

fn present_triple<F>(r: &mut BitReader<'_>, mut f: F) -> Result<Vec<FloatVal>, WireError>
where
    F: FnMut(&mut BitReader<'_>) -> Result<f32, WireError>,
{
    let p0 = r.read_bool()?;
    let p1 = r.read_bool()?;
    let p2 = r.read_bool()?;
    let v0 = if p0 { f(r)? } else { 0.0 };
    let v1 = if p1 { f(r)? } else { 0.0 };
    let v2 = if p2 { f(r)? } else { 0.0 };
    Ok(vec![
        FloatVal::Finite(v0),
        FloatVal::Finite(v1),
        FloatVal::Finite(v2),
    ])
}

fn read_normal(r: &mut BitReader<'_>, p: &CoordinateProfile) -> Result<Vec<FloatVal>, WireError> {
    let x = r.read_bool()?;
    let y = r.read_bool()?;
    let scale = 1.0f32 / (((1u32 << p.normal) - 1) as f32);
    let read_comp = |r: &mut BitReader<'_>| -> Result<f32, WireError> {
        let sign = r.read_bool()?;
        let val = (r.read_bits(p.normal)? as f32) * scale;
        Ok(if sign { -val } else { val })
    };
    let a = if x { read_comp(r)? } else { 0.0 };
    let b = if y { read_comp(r)? } else { 0.0 };
    let negative = r.read_bool()?;
    let sum = a * a + b * b;
    let z = if sum < 1.0 { (1.0 - sum).sqrt() } else { 0.0 };
    Ok(vec![
        FloatVal::Finite(a),
        FloatVal::Finite(b),
        FloatVal::Finite(if negative { -z } else { z }),
    ])
}

impl FieldCodec {
    pub fn create(encoding: &FieldEncoding, profile: CoordinateProfile) -> Result<Self, String> {
        let cat = encoding.category;
        let dim = encoding.dimensions;
        let enc = encoding.encoder.to_ascii_lowercase();
        if cat > 7 || (cat != 6 && dim < 1) {
            return Err("Invalid native wire type".into());
        }
        let string_limit = 65536usize;
        let binary_limit = 4 * 1024 * 1024usize;

        if cat == 3 {
            if !matches!(dim, 1 | 2 | 3 | 4 | 6 | 8) {
                return Err("Unsupported float dimension".into());
            }
            if enc == "default" {
                let q = create_field_quantizer(
                    encoding.bit_count,
                    encoding.encode_flags,
                    encoding.low_value,
                    encoding.high_value,
                )?;
                return Ok(FieldCodec::FloatQuantized { dim, q });
            }
            if enc == "coord" || enc == "coord_integral" {
                if !matches!(dim, 1 | 3 | 6 | 8) {
                    return Err("Unsupported coordinate dimension".into());
                }
                return Ok(FieldCodec::Coord {
                    dim,
                    integral: enc == "coord_integral",
                    profile,
                });
            }
            if enc == "normal" {
                if dim != 3 {
                    return Err("Unsupported normal dimension".into());
                }
                return Ok(FieldCodec::Normal { profile });
            }
            if matches!(
                enc.as_str(),
                "qangle" | "qangle_precise" | "qangle_pitch_yaw"
            ) {
                if dim != 3 {
                    return Err("Unsupported angle dimension".into());
                }
                let width = encoding.bit_count.unwrap_or(0);
                if !(0..=32).contains(&width) {
                    return Err("Invalid angle bitcount".into());
                }
                if width == 0 && enc == "qangle" {
                    return Ok(FieldCodec::QAngleCoord { profile });
                }
                if width == 0 && enc == "qangle_precise" {
                    return Ok(FieldCodec::QAnglePrecise { profile });
                }
                let count = if enc == "qangle_pitch_yaw" { 2 } else { 3 };
                let raw = enc != "qangle_precise" && (width == 0 || width == 32);
                return Ok(FieldCodec::QAngleBits {
                    count,
                    width: width as u8,
                    raw,
                });
            }
            return Err(format!("Unsupported float encoder: {enc}"));
        }

        if dim != 1 && !(cat == 6 && dim == 0) {
            return Err("Unsupported scalar dimension".into());
        }

        if cat == 1 || cat == 2 {
            let signed = cat == 1;
            return match enc.as_str() {
                "default" => Ok(FieldCodec::IntVarint { signed }),
                "fixed8" => Ok(FieldCodec::IntFixed8 { signed }),
                "fixed32" => Ok(FieldCodec::IntFixed32 { signed }),
                "fixed64" => Ok(FieldCodec::IntFixed64 { signed }),
                _ => Err(format!("Unsupported integer encoder: {enc}")),
            };
        }

        if enc != "default" {
            return Err(format!("Unsupported scalar encoder: {enc}"));
        }
        match cat {
            0 => Ok(FieldCodec::Noop),
            4 => Ok(FieldCodec::FloatRaw),
            7 => Ok(FieldCodec::Bool),
            6 => Ok(FieldCodec::Binary {
                limit: binary_limit,
            }),
            5 => Ok(FieldCodec::StringNul {
                limit: string_limit,
            }),
            _ => Err("Unsupported native wire type".into()),
        }
    }

    pub fn decode(&self, r: &mut BitReader<'_>) -> Result<FieldValue, WireError> {
        match self {
            FieldCodec::Noop => Ok(FieldValue::None),
            FieldCodec::Bool => Ok(FieldValue::Bool(r.read_bool()?)),
            FieldCodec::FloatRaw => Ok(FieldValue::Float(read_raw_f32(r)?)),
            FieldCodec::FloatQuantized { dim, q } => {
                if *dim == 1 {
                    let v = if q.raw {
                        read_raw_f32(r)?
                    } else {
                        FloatVal::Finite(decode_quantized(r, q)?)
                    };
                    Ok(FieldValue::Float(v))
                } else {
                    let mut vec = Vec::with_capacity(*dim as usize);
                    for _ in 0..*dim {
                        let v = if q.raw {
                            read_raw_f32(r)?
                        } else {
                            FloatVal::Finite(decode_quantized(r, q)?)
                        };
                        vec.push(v);
                    }
                    Ok(FieldValue::FloatVec(vec))
                }
            }
            FieldCodec::Coord {
                dim,
                integral,
                profile,
            } => {
                if *dim == 1 {
                    let v = if *integral {
                        read_integral(r, profile)?
                    } else {
                        read_coord(r, profile)?
                    };
                    return Ok(FieldValue::Float(FloatVal::Finite(v)));
                }
                let mut vals = Vec::with_capacity(*dim as usize);
                for _ in 0..3 {
                    let v = if *integral {
                        read_integral(r, profile)?
                    } else {
                        read_coord(r, profile)?
                    };
                    vals.push(FloatVal::Finite(v));
                }
                if *dim == 6 || *dim == 8 {
                    vals.extend(present_triple(r, |r| read_coord(r, profile))?);
                }
                Ok(FieldValue::FloatVec(vals))
            }
            FieldCodec::Normal { profile } => Ok(FieldValue::FloatVec(read_normal(r, profile)?)),
            FieldCodec::QAngleCoord { profile } => {
                Ok(FieldValue::FloatVec(present_triple(r, |r| {
                    read_coord(r, profile)
                })?))
            }
            FieldCodec::QAnglePrecise { profile } => {
                let scale = 360.0f32 / ((1u32 << profile.angle) as f32);
                Ok(FieldValue::FloatVec(present_triple(r, |r| {
                    let bits = r.read_bits(profile.angle)?;
                    Ok(((bits as f32) * scale) - 180.0)
                })?))
            }
            FieldCodec::QAngleBits { count, width, raw } => {
                let mut vals = Vec::with_capacity(3);
                let scale = 360.0f32 / ((1u64 << (*width & 31)) as f32);
                for _ in 0..*count {
                    if *raw {
                        vals.push(read_raw_f32(r)?);
                    } else {
                        let bits = r.read_bits(*width)? as i32;
                        vals.push(FloatVal::Finite((bits as f32) * scale));
                    }
                }
                if *count == 2 {
                    vals.push(FloatVal::Finite(0.0));
                }
                Ok(FieldValue::FloatVec(vals))
            }
            FieldCodec::IntVarint { signed } => {
                let val = r.read_varuint64()?;
                if *signed {
                    let s = ((val >> 1) as i64) ^ (-((val & 1) as i64));
                    Ok(FieldValue::Int(s))
                } else {
                    Ok(FieldValue::Uint(val))
                }
            }
            FieldCodec::IntFixed8 { signed } => {
                let v = r.read_bits(8)? as u8;
                if *signed {
                    Ok(FieldValue::Int((v as i8) as i64))
                } else {
                    Ok(FieldValue::Uint(v as u64))
                }
            }
            FieldCodec::IntFixed32 { signed } => {
                let v = r.read_bits(32)?;
                if *signed {
                    Ok(FieldValue::Int((v as i32) as i64))
                } else {
                    Ok(FieldValue::Uint(v as u64))
                }
            }
            FieldCodec::IntFixed64 { signed } => {
                let v = r.read_bits64(64)?;
                if *signed {
                    Ok(FieldValue::Int(v as i64))
                } else {
                    Ok(FieldValue::Uint(v))
                }
            }
            FieldCodec::Binary { limit } => {
                let size = r.read_varuint32()? as usize;
                if size > *limit || size * 8 > r.remaining_bits() {
                    return Err(WireError::ChannelBodyBoundary);
                }
                let bytes = r.read_bytes(size)?.into_owned();
                Ok(FieldValue::Bytes(bytes))
            }
            FieldCodec::StringNul { limit } => {
                let bytes = r.read_string_nul(*limit)?;
                Ok(FieldValue::Bytes(bytes))
            }
        }
    }
}
