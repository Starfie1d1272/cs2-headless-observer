use crate::wire::bits::{BitReader, WireError};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Quantizer {
    pub raw: bool,
    pub bits: u8,
    pub low: f32,
    pub high: f32,
    pub multiplier: f64,
    pub decode_multiplier: f64,
    pub flags: u32,
}

const MAX_FLOAT: f32 = f32::MAX;

pub fn create_quantizer(
    mut bits: i32,
    mut flags: i32,
    mut low: f32,
    mut high: f32,
) -> Result<Quantizer, String> {
    if !(1..=31).contains(&bits) {
        return Ok(Quantizer {
            raw: true,
            bits: 32,
            low: -MAX_FLOAT,
            high: MAX_FLOAT,
            multiplier: 0.0,
            decode_multiplier: 0.0,
            flags: 0,
        });
    }
    let mut uflags = (flags as u32) & 15;
    if !low.is_finite() || !high.is_finite() || high <= low {
        return Err("Invalid native quantizer range".into());
    }
    if (low == 0.0 && (uflags & 1) != 0) || (high == 0.0 && (uflags & 2) != 0) {
        uflags &= !4;
    }
    if low == 0.0 && (uflags & 4) != 0 {
        uflags = (uflags & !4) | 1;
    }
    if high == 0.0 && (uflags & 4) != 0 {
        uflags = (uflags & !4) | 2;
    }
    if low > 0.0 || high < 0.0 {
        uflags &= !4;
    }
    if (uflags & 8) != 0 {
        uflags &= 8;
    }

    let mut steps = 1u32 << bits;
    if (uflags & 1) != 0 {
        let offset = (high - low) / (steps as f32);
        high -= offset;
    } else if (uflags & 2) != 0 {
        let offset = (high - low) / (steps as f32);
        low += offset;
    }
    if (uflags & 8) != 0 {
        let delta = (high as i32).wrapping_sub(low as i32) as u32;
        let exponent = if delta > 1 {
            31 - delta.leading_zeros()
        } else {
            0
        };
        let range = 1u32 << (exponent + 1);
        while (1u32 << bits) < range {
            bits += 1;
            if bits > 31 {
                return Err("Unsupported native quantizer derived width".into());
            }
        }
        steps = 1u32 << bits;
        let offset = (range as f32) / (steps as f32);
        high = (low + (range as f32)) - offset;
    }

    let maximum = steps - 1;
    let delta = (high - low) as f64;
    let mut multiplier = maximum as f64;
    if delta.abs() > (0.001f32 as f64) {
        multiplier /= delta;
    }
    let overflows = |val: f64| -> bool {
        let product = val * delta;
        !product.is_finite()
            || product < 0.0
            || (product as u32) > maximum
            || product > maximum as f64
    };
    if overflows(multiplier) {
        let mut word: u32 = 0x3f80_0000;
        while overflows((f32::from_bits(word) as f64) * multiplier) {
            word = word.wrapping_sub(1);
            if word < 0x3f70_0000 {
                return Err("Native quantizer multiplier budget".into());
            }
        }
        multiplier *= f32::from_bits(word) as f64;
    }
    let decode_multiplier = 1.0 / (maximum as f64);
    let quantize = |value: f32| -> f32 {
        if value < low {
            return low;
        }
        if value > high {
            return high;
        }
        let encoded = (((value - low) as f64) * multiplier + 0.5) as u32;
        let decoded =
            ((encoded as f64) * decode_multiplier * ((high - low) as f64) + (low as f64)) as f32;
        decoded.min(high)
    };
    let mut effective = uflags;
    for (bit, val) in [(1u32, low), (2u32, high), (4u32, 0.0f32)] {
        if (uflags & bit) != 0 && quantize(val) == val {
            effective &= !bit;
        }
    }
    let _ = flags;
    flags = effective as i32;
    Ok(Quantizer {
        raw: false,
        bits: bits as u8,
        low,
        high,
        multiplier,
        decode_multiplier,
        flags: flags as u32,
    })
}

pub fn create_field_quantizer(
    bit_count: Option<i32>,
    encode_flags: Option<i32>,
    low_value: Option<f32>,
    high_value: Option<f32>,
) -> Result<Quantizer, String> {
    let bits = bit_count.unwrap_or(0);
    let mut low = low_value.unwrap_or(-MAX_FLOAT);
    let mut high = high_value.unwrap_or(MAX_FLOAT);
    if (1..=31).contains(&bits) {
        if low == -MAX_FLOAT {
            low = 0.0;
        }
        if high == MAX_FLOAT {
            high = (((1u32 << bits) - 1) as i32) as f32;
        }
    }
    create_quantizer(bits, encode_flags.unwrap_or(0), low, high)
}

#[inline]
pub fn decode_quantized(reader: &mut BitReader<'_>, q: &Quantizer) -> Result<f32, WireError> {
    if q.raw {
        return reader.read_f32_le();
    }
    if (q.flags & 1) != 0 && reader.read_bool()? {
        return Ok(q.low);
    }
    if (q.flags & 2) != 0 && reader.read_bool()? {
        return Ok(q.high);
    }
    if (q.flags & 4) != 0 && reader.read_bool()? {
        return Ok(0.0);
    }
    let raw = reader.read_bits(q.bits)?;
    let val =
        ((raw as f64) * q.decode_multiplier * ((q.high - q.low) as f64) + (q.low as f64)) as f32;
    Ok(val.min(q.high))
}
