use std::borrow::Cow;
use std::collections::HashMap;
use thiserror::Error;

pub const MAX_BYTES: usize = 4 * 1024 * 1024;

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum WireError {
    #[error("channel-byte-budget")]
    ChannelByteBudget,
    #[error("channel-bit-boundary")]
    ChannelBitBoundary,
    #[error("channel-bit-underflow")]
    ChannelBitUnderflow,
    #[error("channel-varuint32-overflow")]
    Varuint32Overflow,
    #[error("overflow-varint")]
    VarintOverflow,
    #[error("truncated-varint")]
    TruncatedVarint,
    #[error("invalid-field-number")]
    InvalidFieldNumber,
    #[error("truncated-field")]
    TruncatedField,
    #[error("unsupported-wire-type")]
    UnsupportedWireType,
    #[error("payload-limit")]
    PayloadLimit,
    #[error("ambiguous-or-wrong-wire-field")]
    AmbiguousOrWrongWireField,
    #[error("channel-body-boundary")]
    ChannelBodyBoundary,
    #[error("channel-message-budget")]
    ChannelMessageBudget,
    #[error("message-bit-span")]
    MessageBitSpan,
    #[error("unsupported-channel-tag")]
    UnsupportedChannelTag,
    #[error("channel-reliability-mismatch")]
    ChannelReliabilityMismatch,
    #[error("channel-empty-compressed-body")]
    ChannelEmptyCompressedBody,
    #[error("channel-history-count")]
    ChannelHistoryCount,
    #[error("unsupported-sequence-domain")]
    UnsupportedSequenceDomain,
    #[error("outgoing-sequence-restart-required")]
    OutgoingSequenceRestartRequired,
    #[error("reliable-marker-state")]
    ReliableMarkerState,
    #[error("lz4-budget")]
    Lz4Budget,
    #[error("lz4-decompress-failed: {0}")]
    Lz4Failed(String),
    #[error("snappy-decompress-failed: {0}")]
    SnappyFailed(String),
    #[error("manifest-compression: {0}")]
    ManifestCompression(&'static str),
    #[error("challenge-size")]
    ChallengeSize,
    #[error("unsupported-auth-protocol")]
    UnsupportedAuthProtocol,
    #[error("invalid-steam-key-size")]
    InvalidSteamKeySize,
    #[error("invalid-secure-flag")]
    InvalidSecureFlag,
    #[error("challenge-context-boundary")]
    ChallengeContextBoundary,
    #[error("auth-payload-size-or-protocol")]
    AuthPayloadSizeOrProtocol,
    #[error("player-name-boundary")]
    PlayerNameBoundary,
    #[error("encrypted-password-size")]
    EncryptedPasswordSize,
    #[error("connect-size-limit")]
    ConnectSizeLimit,
    #[error("connect-payload-boundary")]
    ConnectPayloadBoundary,
    #[error("observed-connect-writer-budget")]
    ObservedConnectWriterBudget,
    #[error("connection-inner-prefix-or-budget")]
    ConnectionInnerPrefixOrBudget,
    #[error("connection-inner-length")]
    ConnectionInnerLength,
    #[error("connection-inner-padding")]
    ConnectionInnerPadding,
    #[error("unsupported-ack-state")]
    UnsupportedAckState,
    #[error("signon-error: {0}")]
    Signon(&'static str),
    #[error("string-budget")]
    StringBudget,
    #[error("protobuf-decode: {0}")]
    Protobuf(String),
}

/// Zero-copy little-endian bit reader over a byte slice (up to 4 MiB).
#[derive(Debug, Clone)]
pub struct BitReader<'a> {
    data: &'a [u8],
    pos: usize,
    end: usize,
}

impl<'a> BitReader<'a> {
    pub fn new(data: &'a [u8]) -> Result<Self, WireError> {
        if data.len() > MAX_BYTES {
            return Err(WireError::ChannelByteBudget);
        }
        Ok(Self {
            data,
            pos: 0,
            end: data.len() * 8,
        })
    }

    pub fn with_bit_count(data: &'a [u8], bit_count: usize) -> Result<Self, WireError> {
        if data.len() > MAX_BYTES {
            return Err(WireError::ChannelByteBudget);
        }
        if bit_count > data.len() * 8 {
            return Err(WireError::ChannelBitBoundary);
        }
        Ok(Self {
            data,
            pos: 0,
            end: bit_count,
        })
    }

    #[inline]
    pub fn remaining_bits(&self) -> usize {
        self.end - self.pos
    }

    #[inline]
    pub fn position(&self) -> usize {
        self.pos
    }

    #[inline]
    pub fn read_bool(&mut self) -> Result<bool, WireError> {
        if self.pos >= self.end {
            return Err(WireError::ChannelBitUnderflow);
        }
        let byte = self.data[self.pos >> 3];
        let bit = (byte >> (self.pos & 7)) & 1;
        self.pos += 1;
        Ok(bit != 0)
    }

    #[inline]
    pub fn read_bits(&mut self, size: u8) -> Result<u32, WireError> {
        let size = size as usize;
        if size > 32 || self.pos + size > self.end {
            return Err(WireError::ChannelBitUnderflow);
        }
        if size == 0 {
            return Ok(0);
        }
        let val = self.peek_bits_raw(size);
        self.pos += size;
        Ok(val)
    }

    #[inline]
    pub fn read_bits64(&mut self, size: u8) -> Result<u64, WireError> {
        let size = size as usize;
        if size > 64 || self.pos + size > self.end {
            return Err(WireError::ChannelBitUnderflow);
        }
        if size == 0 {
            return Ok(0);
        }
        if size <= 32 {
            return Ok(self.read_bits(size as u8)? as u64);
        }
        let lo = self.read_bits(32)? as u64;
        let hi = self.read_bits((size - 32) as u8)? as u64;
        Ok(lo | (hi << 32))
    }

    #[inline]
    fn peek_bits_raw(&self, size: usize) -> u32 {
        let start = self.pos >> 3;
        let shift = self.pos & 7;
        let last_byte = (self.pos + size - 1) >> 3;
        let mut acc: u64 = 0;
        let count = last_byte - start + 1;
        for i in 0..count {
            acc |= (self.data[start + i] as u64) << (i * 8);
        }
        let shifted = acc >> shift;
        if size == 32 {
            shifted as u32
        } else {
            (shifted & ((1u64 << size) - 1)) as u32
        }
    }

    /// Peek up to 8 bits (zero-padded at end of stream) for Huffman primary lookup.
    #[inline]
    pub fn peek_huffman_prefix(&self) -> u8 {
        let avail = self.end - self.pos;
        if avail == 0 {
            return 0;
        }
        let start = self.pos >> 3;
        let shift = self.pos & 7;
        let mut val = (self.data[start] as u16) >> shift;
        if shift > 0 && start + 1 < self.data.len() {
            val |= (self.data[start + 1] as u16) << (8 - shift);
        }
        let mask = if avail >= 8 {
            0xffu16
        } else {
            (1u16 << avail) - 1
        };
        (val & mask) as u8
    }

    /// Peek up to 17 bits (zero-padded at end of stream) for Huffman long code lookup.
    #[inline]
    pub fn peek_huffman_code(&self) -> u32 {
        let avail = self.end - self.pos;
        if avail == 0 {
            return 0;
        }
        let start = self.pos >> 3;
        let shift = self.pos & 7;
        let mut acc: u32 = 0;
        let max_bytes = 3.min(self.data.len() - start);
        for i in 0..max_bytes {
            acc |= (self.data[start + i] as u32) << (i * 8);
        }
        let shifted = acc >> shift;
        let mask = if avail >= 17 {
            0x1ffff
        } else {
            (1u32 << avail) - 1
        };
        shifted & mask
    }

    #[inline]
    pub fn consume_bits(&mut self, count: usize) -> Result<(), WireError> {
        if self.pos + count > self.end {
            return Err(WireError::ChannelBitUnderflow);
        }
        self.pos += count;
        Ok(())
    }

    #[inline]
    pub fn read_byte(&mut self) -> Result<u8, WireError> {
        self.read_bits(8).map(|v| v as u8)
    }

    pub fn read_varuint32(&mut self) -> Result<u32, WireError> {
        let mut value: u32 = 0;
        for index in 0..5 {
            let byte = self.read_byte()?;
            if index == 4 && byte > 15 {
                return Err(WireError::Varuint32Overflow);
            }
            value |= ((byte & 127) as u32) << (7 * index);
            if byte & 128 == 0 {
                return Ok(value);
            }
        }
        Err(WireError::Varuint32Overflow)
    }

    #[inline]
    pub fn read_varint32(&mut self) -> Result<i32, WireError> {
        let v = self.read_varuint32()?;
        Ok(((v >> 1) as i32) ^ (-((v & 1) as i32)))
    }

    pub fn read_varuint64(&mut self) -> Result<u64, WireError> {
        let mut value: u64 = 0;
        for index in 0..10 {
            let byte = self.read_byte()?;
            if index == 9 && byte > 1 {
                return Err(WireError::VarintOverflow);
            }
            value |= ((byte & 127) as u64) << (7 * index);
            if byte & 128 == 0 {
                return Ok(value);
            }
        }
        Err(WireError::VarintOverflow)
    }

    #[inline]
    pub fn read_varint64(&mut self) -> Result<i64, WireError> {
        let v = self.read_varuint64()?;
        Ok(((v >> 1) as i64) ^ (-((v & 1) as i64)))
    }

    #[inline]
    pub fn read_ubitvar(&mut self) -> Result<u32, WireError> {
        let head = self.read_bits(6)?;
        let extra_bits = match head >> 4 {
            0 => 0,
            1 => 4,
            2 => 8,
            _ => 28,
        };
        let extra = self.read_bits(extra_bits)?;
        Ok((head & 15) | (extra << 4))
    }

    #[inline]
    pub fn read_ubitvar_fp(&mut self) -> Result<u32, WireError> {
        if self.read_bool()? {
            return self.read_bits(2);
        }
        if self.read_bool()? {
            return self.read_bits(4);
        }
        if self.read_bool()? {
            return self.read_bits(10);
        }
        if self.read_bool()? {
            return self.read_bits(17);
        }
        self.read_bits(31)
    }

    #[inline]
    pub fn read_f32_le(&mut self) -> Result<f32, WireError> {
        let bits = self.read_bits(32)?;
        Ok(f32::from_bits(bits))
    }

    pub fn read_bytes(&mut self, size: usize) -> Result<Cow<'a, [u8]>, WireError> {
        if size > MAX_BYTES || self.pos + size * 8 > self.end {
            return Err(WireError::ChannelBodyBoundary);
        }
        if size == 0 {
            return Ok(Cow::Borrowed(&[]));
        }
        let shift = self.pos & 7;
        let start = self.pos >> 3;
        self.pos += size * 8;
        if shift == 0 {
            Ok(Cow::Borrowed(&self.data[start..start + size]))
        } else {
            let mut out = Vec::with_capacity(size);
            for i in 0..size {
                let lo = self.data[start + i] >> shift;
                let hi = self.data[start + i + 1] << (8 - shift);
                out.push(lo | hi);
            }
            Ok(Cow::Owned(out))
        }
    }

    pub fn discard_bytes(&mut self, size: usize) -> Result<(), WireError> {
        if size > MAX_BYTES || self.pos + size * 8 > self.end {
            return Err(WireError::ChannelBodyBoundary);
        }
        self.pos += size * 8;
        Ok(())
    }

    pub fn read_string_nul(&mut self, max_len: usize) -> Result<Vec<u8>, WireError> {
        let mut out = Vec::new();
        for _ in 0..=max_len {
            let b = self.read_byte()?;
            if b == 0 {
                return Ok(out);
            }
            if out.len() == max_len {
                return Err(WireError::StringBudget);
            }
            out.push(b);
        }
        Err(WireError::StringBudget)
    }
}

pub fn read_varint(data: &[u8], pos: &mut usize) -> Result<u64, WireError> {
    let mut value: u64 = 0;
    for shift in (0..70).step_by(7) {
        if *pos >= data.len() {
            return Err(WireError::TruncatedVarint);
        }
        let byte = data[*pos];
        *pos += 1;
        if shift == 63 && byte > 1 {
            return Err(WireError::VarintOverflow);
        }
        value |= ((byte & 127) as u64) << shift;
        if byte < 128 {
            return Ok(value);
        }
    }
    Err(WireError::VarintOverflow)
}

pub fn encode_varint(mut value: u64, out: &mut Vec<u8>) {
    while value >= 128 {
        out.push(((value & 127) as u8) | 128);
        value >>= 7;
    }
    out.push(value as u8);
}

pub fn encode_pb_varint(tag: u32, value: u64, out: &mut Vec<u8>) {
    encode_varint((tag as u64) << 3, out);
    encode_varint(value, out);
}

pub fn encode_pb_bytes(tag: u32, bytes: &[u8], out: &mut Vec<u8>) {
    encode_varint(((tag as u64) << 3) | 2, out);
    encode_varint(bytes.len() as u64, out);
    out.extend_from_slice(bytes);
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WireFieldValue<'a> {
    Varint(u64),
    Fixed64([u8; 8]),
    Bytes(&'a [u8]),
    Fixed32([u8; 4]),
}

pub fn wire_fields<'a>(
    data: &'a [u8],
    limit: usize,
) -> Result<HashMap<u32, Vec<WireFieldValue<'a>>>, WireError> {
    if limit == 0 || limit > MAX_BYTES || data.len() > limit {
        return Err(WireError::PayloadLimit);
    }
    let mut pos = 0;
    let mut result: HashMap<u32, Vec<WireFieldValue<'a>>> = HashMap::new();
    while pos < data.len() {
        let key = read_varint(data, &mut pos)?;
        let number = key >> 3;
        let wire = (key & 7) as u8;
        if number == 0 || number >= (1 << 29) {
            return Err(WireError::InvalidFieldNumber);
        }
        let val = match wire {
            0 => WireFieldValue::Varint(read_varint(data, &mut pos)?),
            1 => {
                if data.len() - pos < 8 {
                    return Err(WireError::TruncatedField);
                }
                let mut arr = [0u8; 8];
                arr.copy_from_slice(&data[pos..pos + 8]);
                pos += 8;
                WireFieldValue::Fixed64(arr)
            }
            2 => {
                let size = read_varint(data, &mut pos)? as usize;
                if size > data.len() - pos {
                    return Err(WireError::TruncatedField);
                }
                let slice = &data[pos..pos + size];
                pos += size;
                WireFieldValue::Bytes(slice)
            }
            5 => {
                if data.len() - pos < 4 {
                    return Err(WireError::TruncatedField);
                }
                let mut arr = [0u8; 4];
                arr.copy_from_slice(&data[pos..pos + 4]);
                pos += 4;
                WireFieldValue::Fixed32(arr)
            }
            _ => return Err(WireError::UnsupportedWireType),
        };
        result.entry(number as u32).or_default().push(val);
    }
    Ok(result)
}

pub fn scalar_varint(
    fields: &HashMap<u32, Vec<WireFieldValue<'_>>>,
    number: u32,
) -> Result<Option<u64>, WireError> {
    match fields.get(&number) {
        None => Ok(None),
        Some(v) if v.len() == 1 => match &v[0] {
            WireFieldValue::Varint(x) => Ok(Some(*x)),
            _ => Err(WireError::AmbiguousOrWrongWireField),
        },
        _ => Err(WireError::AmbiguousOrWrongWireField),
    }
}

pub fn scalar_bytes<'a>(
    fields: &HashMap<u32, Vec<WireFieldValue<'a>>>,
    number: u32,
) -> Result<Option<&'a [u8]>, WireError> {
    match fields.get(&number) {
        None => Ok(None),
        Some(v) if v.len() == 1 => match &v[0] {
            WireFieldValue::Bytes(b) => Ok(Some(*b)),
            _ => Err(WireError::AmbiguousOrWrongWireField),
        },
        _ => Err(WireError::AmbiguousOrWrongWireField),
    }
}

pub fn scalar_fixed32(
    fields: &HashMap<u32, Vec<WireFieldValue<'_>>>,
    number: u32,
) -> Result<Option<[u8; 4]>, WireError> {
    match fields.get(&number) {
        None => Ok(None),
        Some(v) if v.len() == 1 => match &v[0] {
            WireFieldValue::Fixed32(b) => Ok(Some(*b)),
            _ => Err(WireError::AmbiguousOrWrongWireField),
        },
        _ => Err(WireError::AmbiguousOrWrongWireField),
    }
}
