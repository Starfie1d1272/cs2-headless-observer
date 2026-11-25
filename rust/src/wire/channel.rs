use std::collections::{HashMap, HashSet};
use std::fmt;

use super::bits::{encode_varint, scalar_varint, wire_fields, BitReader, WireError, MAX_BYTES};
use super::compression::lz4_block;

#[derive(Clone, PartialEq, Eq)]
pub struct ChannelFrame {
    pub reliable: bool,
    pub compressed: bool,
    pub reliable_tick_hint: Option<u32>,
    pub sequence: Option<u32>,
    pub acknowledgement: Option<u32>,
    pub history_raw: [u16; 3],
    pub body: Vec<u8>,
}

impl fmt::Debug for ChannelFrame {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ChannelFrame")
            .field("reliable", &self.reliable)
            .field("compressed", &self.compressed)
            .field("reliable_tick_hint", &self.reliable_tick_hint)
            .field("sequence", &self.sequence)
            .field("acknowledgement", &self.acknowledgement)
            .field("history_raw", &self.history_raw)
            .field("body_len", &self.body.len())
            .finish()
    }
}

pub fn decode_frame(data: &[u8], gns_reliable: bool) -> Result<ChannelFrame, WireError> {
    let mut reader = BitReader::new(data)?;
    let tag = reader.read_varuint32()?;
    if !(1..=4).contains(&tag) {
        return Err(WireError::UnsupportedChannelTag);
    }
    let reliable = tag == 1 || tag == 3;
    let compressed = tag == 3 || tag == 4;
    if reliable && !gns_reliable {
        return Err(WireError::ChannelReliabilityMismatch);
    }
    let mut tick = None;
    let mut sequence = None;
    let mut ack = None;
    let mut history = [0u16; 3];
    if reliable {
        tick = Some(reader.read_varuint32()?);
    } else {
        sequence = Some(reader.read_varuint32()?);
        ack = Some(reader.read_varuint32()?);
        for item in &mut history {
            *item = reader.read_bits(16)? as u16;
        }
    }
    let size = if compressed {
        let s = reader.read_varuint32()? as usize;
        if s == 0 {
            return Err(WireError::ChannelEmptyCompressedBody);
        }
        Some(s)
    } else {
        None
    };
    let rem_bytes = reader.remaining_bits() / 8;
    let raw_body = reader.read_bytes(rem_bytes)?;
    let body = if let Some(expected) = size {
        lz4_block(&raw_body, expected)?
    } else {
        raw_body.into_owned()
    };
    Ok(ChannelFrame {
        reliable,
        compressed,
        reliable_tick_hint: tick,
        sequence,
        acknowledgement: ack,
        history_raw: history,
        body,
    })
}

pub fn reliable_frame(message_bytes: &[u8], tick_hint: u32) -> Result<Vec<u8>, WireError> {
    if message_bytes.len() > MAX_BYTES - 6 {
        return Err(WireError::ChannelByteBudget);
    }
    let mut out = Vec::with_capacity(1 + 5 + message_bytes.len());
    out.push(0x01);
    encode_varint(tick_hint as u64, &mut out);
    out.extend_from_slice(message_bytes);
    Ok(out)
}

pub fn unreliable_frame(
    message_bytes: &[u8],
    sequence: u32,
    acknowledgement: u32,
    history_raw: [u16; 3],
) -> Result<Vec<u8>, WireError> {
    if message_bytes.len() > MAX_BYTES - 17 {
        return Err(WireError::ChannelByteBudget);
    }
    let mut out = Vec::with_capacity(1 + 5 + 5 + 6 + message_bytes.len());
    out.push(0x02);
    encode_varint(sequence as u64, &mut out);
    encode_varint(acknowledgement as u64, &mut out);
    for h in history_raw {
        out.extend_from_slice(&h.to_le_bytes());
    }
    out.extend_from_slice(message_bytes);
    Ok(out)
}

#[derive(Clone, PartialEq, Eq)]
pub struct NetMessage {
    pub message_id: u32,
    pub body: Vec<u8>,
}

impl fmt::Debug for NetMessage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("NetMessage")
            .field("message_id", &self.message_id)
            .field("body_len", &self.body.len())
            .finish()
    }
}

pub fn decode_messages(
    data: &[u8],
    bit_count: Option<usize>,
    discard_bodies: &HashSet<u32>,
) -> Result<(Vec<NetMessage>, usize), WireError> {
    let mut reader = match bit_count {
        Some(bc) => BitReader::with_bit_count(data, bc)?,
        None => BitReader::new(data)?,
    };
    let mut result = Vec::new();
    while reader.remaining_bits() >= 8 {
        if result.len() >= 16384 {
            return Err(WireError::ChannelMessageBudget);
        }
        let message_id = reader.read_ubitvar()?;
        let size = reader.read_varuint32()? as usize;
        let body = if discard_bodies.contains(&message_id) {
            reader.discard_bytes(size)?;
            Vec::new()
        } else {
            reader.read_bytes(size)?.into_owned()
        };
        result.push(NetMessage { message_id, body });
    }
    let trailing = reader.remaining_bits();
    Ok((result, trailing))
}

pub fn encode_message(message_id: u32, body: &[u8]) -> Result<(Vec<u8>, usize), WireError> {
    if body.len() > MAX_BYTES - 10 {
        return Err(WireError::ChannelBodyBoundary);
    }
    let selector: u64 = if message_id < 16 {
        0
    } else if message_id < 256 {
        1
    } else if message_id < 4096 {
        2
    } else {
        3
    };
    let extra = [0usize, 4, 8, 28][selector as usize];
    let header_bits = 6 + extra;
    let header: u64 =
        ((message_id & 15) as u64) | (selector << 4) | (((message_id >> 4) as u64) << 6);

    let mut payload = Vec::with_capacity(5 + body.len());
    encode_varint(body.len() as u64, &mut payload);
    payload.extend_from_slice(body);

    let total_bits = header_bits + payload.len() * 8;
    let total_bytes = total_bits.div_ceil(8);
    let mut out = vec![0u8; total_bytes];

    for (i, slot) in out.iter_mut().enumerate().take(8) {
        let shift = i * 8;
        if shift >= header_bits {
            break;
        }
        *slot = ((header >> shift) & 0xff) as u8;
    }

    let byte_off = header_bits / 8;
    let bit_shift = header_bits & 7;
    for (idx, &b) in payload.iter().enumerate() {
        out[byte_off + idx] |= b << bit_shift;
        if bit_shift > 0 && byte_off + idx + 1 < total_bytes {
            out[byte_off + idx + 1] |= b >> (8 - bit_shift);
        }
    }

    Ok((out, total_bits))
}

pub fn join_messages(encoded: &[(Vec<u8>, usize)]) -> Result<(Vec<u8>, usize), WireError> {
    let mut output = Vec::new();
    let mut used = 0usize;
    for (data, count) in encoded {
        if *count == 0 || data.len() != count.div_ceil(8) {
            return Err(WireError::MessageBitSpan);
        }
        if used + *count > MAX_BYTES * 8 {
            return Err(WireError::ChannelByteBudget);
        }
        let offset = used / 8;
        let shift = used & 7;
        let needed_bytes = (used + *count).div_ceil(8);
        if output.len() < needed_bytes {
            output.resize(needed_bytes, 0);
        }
        for (index, &raw_byte) in data.iter().enumerate() {
            let mut byte = raw_byte;
            if index == data.len() - 1 && (*count & 7) != 0 {
                byte &= (1u8 << (*count & 7)) - 1;
            }
            output[offset + index] |= byte << shift;
            if shift > 0 && offset + index + 1 < output.len() {
                output[offset + index + 1] |= byte >> (8 - shift);
            }
        }
        used += *count;
    }
    Ok((output, used))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct OrderAccept {
    pub accepted: bool,
    pub gap: u32,
}

#[derive(Debug, Clone)]
pub struct UnreliableOrder {
    pub last: Option<u32>,
}

impl UnreliableOrder {
    pub fn new(initial: Option<u32>) -> Result<Self, WireError> {
        if let Some(v) = initial {
            if v > 0x7FFF_FFFF {
                return Err(WireError::UnsupportedSequenceDomain);
            }
        }
        Ok(Self { last: initial })
    }

    pub fn accept(&mut self, frame: &ChannelFrame) -> Result<OrderAccept, WireError> {
        if frame.reliable {
            return Err(WireError::UnsupportedSequenceDomain);
        }
        let seq = frame.sequence.ok_or(WireError::UnsupportedSequenceDomain)?;
        if seq > 0x7FFF_FFFF {
            return Err(WireError::UnsupportedSequenceDomain);
        }
        if let Some(last) = self.last {
            if seq <= last {
                return Ok(OrderAccept {
                    accepted: false,
                    gap: 0,
                });
            }
            let gap = seq - last - 1;
            self.last = Some(seq);
            return Ok(OrderAccept {
                accepted: true,
                gap,
            });
        }
        self.last = Some(seq);
        Ok(OrderAccept {
            accepted: true,
            gap: 0,
        })
    }
}

#[derive(Debug, Clone)]
pub struct UnreliableFeedback {
    pub sequence: u32,
    pub received: u32,
    pub history: HashMap<u32, u16>,
}

impl Default for UnreliableFeedback {
    fn default() -> Self {
        Self::new()
    }
}

impl UnreliableFeedback {
    pub const UNKNOWN: u16 = 0xFFFD;
    pub const LATE: u16 = 0xFFFE;
    pub const DROPPED: u16 = 0xFFFF;

    pub fn new() -> Self {
        Self {
            sequence: 1,
            received: 0,
            history: HashMap::new(),
        }
    }

    pub fn observe(&mut self, frame: &ChannelFrame) -> Result<(), WireError> {
        if frame.reliable {
            return Ok(());
        }
        let seq = frame.sequence.ok_or(WireError::UnsupportedSequenceDomain)?;
        if seq > 0x7FFF_FFFF {
            return Err(WireError::UnsupportedSequenceDomain);
        }
        if seq <= self.received {
            if self.history.get(&seq).copied() == Some(Self::DROPPED) {
                self.history.insert(seq, Self::LATE);
            }
            return Ok(());
        }
        let previous = self.received;
        self.received = seq;
        let mut next = HashMap::with_capacity(3);
        for offset in 0..3u32 {
            if let Some(n) = seq.checked_sub(offset) {
                let status = if n == seq || n == 0 {
                    Self::UNKNOWN
                } else if n > previous {
                    Self::DROPPED
                } else {
                    self.history.get(&n).copied().unwrap_or(Self::UNKNOWN)
                };
                next.insert(n, status);
            }
        }
        self.history = next;
        Ok(())
    }

    pub fn frame(&mut self, body: &[u8]) -> Result<Vec<u8>, WireError> {
        if self.sequence > 0x7FFF_FFFF {
            return Err(WireError::OutgoingSequenceRestartRequired);
        }
        let mut hist = [Self::UNKNOWN; 3];
        for (i, slot) in hist.iter_mut().enumerate() {
            if let Some(n) = self.received.checked_sub(i as u32) {
                *slot = self.history.get(&n).copied().unwrap_or(Self::UNKNOWN);
            }
        }
        let pkt = unreliable_frame(body, self.sequence, self.received, hist)?;
        self.sequence += 1;
        Ok(pkt)
    }
}

#[derive(Debug, Clone, Default)]
pub struct ReliableMessageFilter {
    pub last_tick: i32,
    pub filtered: bool,
}

impl ReliableMessageFilter {
    pub fn new() -> Self {
        Self {
            last_tick: 0,
            filtered: false,
        }
    }

    pub fn replace_client_owner(&mut self) {
        self.last_tick = 0;
    }

    pub fn accept(&mut self, message_id: u32, body: &[u8]) -> Result<bool, WireError> {
        if message_id != 61 {
            return Ok(!self.filtered);
        }
        let values = wire_fields(body, 65535)?;
        let state = scalar_varint(&values, 3)?;
        if !matches!(state, None | Some(0) | Some(1)) {
            return Err(WireError::ReliableMarkerState);
        }
        let tick = (scalar_varint(&values, 1)?.unwrap_or(0) as u32) as i32;
        if state.unwrap_or(0) == 0 {
            self.filtered = false;
        } else if tick <= self.last_tick {
            self.filtered = true;
        } else {
            self.last_tick = tick;
        }
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wire::bits::{wire_fields, WireError};
    use crate::wire::compression::lz4_block;
    use crate::wire::handshake::signon_message_bits;

    fn hex(s: &str) -> Vec<u8> {
        let s: String = s.chars().filter(|c| !c.is_whitespace()).collect();
        (0..s.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
            .collect()
    }

    #[test]
    fn test_literal_ubitvar_widths_and_six_bit_signon() {
        let cases = [
            (15u32, "0f00", 14usize),
            (16, "500000", 18),
            (255, "df0300", 18),
            (256, "200400", 22),
            (4095, "ef3f00", 22),
            (4096, "304000000000", 42),
            (0xFFFF_FFFF, "ffffffff0300", 42),
        ];
        let empty = HashSet::new();
        for (number, encoded, bits) in cases {
            let expected_bytes = hex(encoded);
            assert_eq!(
                encode_message(number, b"").unwrap(),
                (expected_bytes.clone(), bits)
            );
            let (decoded, tail) = decode_messages(&expected_bytes, Some(bits), &empty).unwrap();
            assert_eq!(decoded.len(), 1);
            assert_eq!(decoded[0].message_id, number);
            assert!(decoded[0].body.is_empty());
            assert_eq!(tail, 0);
        }
        let (data, bits) = signon_message_bits(3, 17).unwrap();
        assert_eq!(
            encode_message(7, &hex("080310111800")).unwrap(),
            (data, bits)
        );
    }

    #[test]
    fn test_unaligned_multiple_messages_and_trailing_padding() {
        let first = encode_message(7, b"\x08\x03").unwrap();
        let second = encode_message(40, b"\x08\x01").unwrap();
        let total_bits = first.1 + second.1;
        let (data, joined_bits) = join_messages(&[first, second]).unwrap();
        assert_eq!(joined_bits, total_bits);
        let empty = HashSet::new();
        let (parsed, padding) = decode_messages(&data, None, &empty).unwrap();
        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[0].message_id, 7);
        assert_eq!(parsed[0].body, b"\x08\x03");
        assert_eq!(parsed[1].message_id, 40);
        assert_eq!(parsed[1].body, b"\x08\x01");
        assert_eq!(padding, data.len() * 8 - total_bits);
        assert!(decode_messages(&data, Some(total_bits - 1), &empty).is_err());
        assert!(decode_messages(b"\x07", None, &empty).is_err());
    }

    #[test]
    fn test_frame_headers_reliability_and_order() {
        let (payload, _) = signon_message_bits(3, 17).unwrap();
        let rel = reliable_frame(&payload, 6400).unwrap();
        let frame = decode_frame(&rel, true).unwrap();
        assert_eq!(frame.reliable_tick_hint, Some(6400));
        assert_eq!(frame.body, payload);
        let dbg = format!("{frame:?}");
        assert!(!dbg.contains(&format!("{:02x}", payload[0])));
        assert_eq!(
            decode_frame(&rel, false).unwrap_err(),
            WireError::ChannelReliabilityMismatch
        );

        let mut order = UnreliableOrder::new(None).unwrap();
        let incoming = |seq: u8| {
            let mut pkt = vec![2u8, seq, 4];
            pkt.extend_from_slice(&1u16.to_le_bytes());
            pkt.extend_from_slice(&0xFFFDu16.to_le_bytes());
            pkt.extend_from_slice(&0xFFFFu16.to_le_bytes());
            decode_frame(&pkt, false).unwrap()
        };
        let a = order.accept(&incoming(10)).unwrap();
        assert!(a.accepted && a.gap == 0);
        let b = order.accept(&incoming(12)).unwrap();
        assert!(b.accepted && b.gap == 1);
        assert!(!order.accept(&incoming(11)).unwrap().accepted);
        assert!(!order.accept(&incoming(12)).unwrap().accepted);
        assert_eq!(incoming(12).history_raw, [1, 0xFFFD, 0xFFFF]);

        let mut pkt = vec![2u8, 12, 4];
        pkt.extend_from_slice(&1u16.to_le_bytes());
        pkt.extend_from_slice(&0xFFFDu16.to_le_bytes());
        pkt.extend_from_slice(&0xFFFFu16.to_le_bytes());
        let promoted = decode_frame(&pkt, true).unwrap();
        assert!(!promoted.reliable);
        assert_eq!(promoted.sequence, Some(12));
        assert_eq!(
            decode_frame(b"\x02\x01\x01", false).unwrap_err(),
            WireError::ChannelBitUnderflow
        );
    }

    #[test]
    fn test_unreliable_feedback_literal_sequence_ack_and_loss_history() {
        let mut feedback = UnreliableFeedback::new();
        assert_eq!(
            feedback.frame(b"").unwrap(),
            hex("02 01 00 fd ff fd ff fd ff")
        );
        let incoming = |n: u8| {
            let mut pkt = vec![2u8, n, 0];
            pkt.extend_from_slice(&hex("fd ff fd ff fd ff"));
            decode_frame(&pkt, false).unwrap()
        };
        feedback.observe(&incoming(3)).unwrap();
        assert_eq!(
            feedback.frame(b"").unwrap(),
            hex("02 02 03 fd ff ff ff ff ff")
        );
        feedback.observe(&incoming(2)).unwrap();
        assert_eq!(
            feedback.frame(b"").unwrap(),
            hex("02 03 03 fd ff fe ff ff ff")
        );
        feedback.observe(&incoming(3)).unwrap();
        let rel = reliable_frame(b"", 100).unwrap();
        feedback
            .observe(&decode_frame(&rel, true).unwrap())
            .unwrap();
        assert_eq!(
            feedback.frame(b"x").unwrap(),
            hex("02 04 03 fd ff fe ff ff ff 78")
        );
        feedback.observe(&incoming(6)).unwrap();
        assert_eq!(
            feedback.frame(b"").unwrap(),
            hex("02 05 06 fd ff ff ff ff ff")
        );
        assert_eq!(feedback.history.len(), 3);
        feedback.sequence = 0x8000_0000;
        assert_eq!(
            feedback.frame(b"").unwrap_err(),
            WireError::OutgoingSequenceRestartRequired
        );
    }

    #[test]
    fn test_compression_is_lz4_block_after_channel_header() {
        let block = b"\x50hello";
        assert_eq!(lz4_block(block, 5).unwrap(), b"hello");
        assert_eq!(
            decode_frame(&[&b"\x03\x11\x05"[..], block].concat(), true)
                .unwrap()
                .body,
            b"hello"
        );
        let mut header = vec![0x04, 0x01, 0x01];
        header.extend_from_slice(&[0u8; 6]);
        let mut pkt = header.clone();
        pkt.push(0x05);
        pkt.extend_from_slice(block);
        assert_eq!(decode_frame(&pkt, false).unwrap().body, b"hello");
        let promoted = decode_frame(&pkt, true).unwrap();
        assert!(!promoted.reliable);
        assert_eq!(promoted.body, b"hello");

        for (bad, size) in [
            (&b""[..], 0usize),
            (b"\xf0", 15),
            (b"\x50hi", 5),
            (b"\x10a\0\0", 5),
            (b"\x10a\x02\0", 5),
            (b"\x10a\x01\0", 5),
            (block, 4),
            (block, 6),
        ] {
            assert!(
                lz4_block(bad, size).is_err(),
                "expected err for {bad:?} size={size}"
            );
        }
        assert_eq!(lz4_block(b"\0", 0).unwrap(), b"");
        assert_eq!(
            decode_frame(b"\x03\x11\0\0", true).unwrap_err(),
            WireError::ChannelEmptyCompressedBody
        );
        assert_eq!(
            decode_frame(b"\xff\xff\xff\xff\xff", true).unwrap_err(),
            WireError::Varuint32Overflow
        );
    }

    #[test]
    fn test_malformed_protobuf_fields() {
        let oversized = vec![0x08u8; 65536];
        let cases: [&[u8]; 6] = [
            b"\x00",
            b"\x0a\xff",
            b"\x0f",
            b"\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff",
            b"\x0a\x03a",
            &oversized,
        ];
        for data in cases {
            assert!(wire_fields(data, 65535).is_err());
        }
    }
}
