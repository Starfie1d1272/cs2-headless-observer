"""Static-derived Source 2 payloads INSIDE authenticated, reassembled GNS messages.

No raw UDP, SNP ACK/fragment implementation, credential handling or automatic reply.
See CHANNEL-EVIDENCE.md; bodies remain private and repr excludes their bytes.
"""
from dataclasses import dataclass, field
from handshake import encode_varint, uint
from wire import ProbeError

MAX_BYTES = 4 * 1024**2  # Research resource budget, not a claimed server limit.


class Bits:
    def __init__(self, data, count=None):
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise ProbeError('channel-byte-budget')
        self.data, self.pos = data, 0
        self.end = len(data) * 8 if count is None else count
        if type(self.end) is not int or not 0 <= self.end <= len(data) * 8:
            raise ProbeError('channel-bit-boundary')

    def read(self, size):
        if not 0 <= size <= 32 or self.pos + size > self.end:
            raise ProbeError('channel-bit-underflow')
        start, shift = self.pos // 8, self.pos & 7
        value = int.from_bytes(self.data[start:(self.pos + size + 7) // 8], 'little')
        self.pos += size
        return (value >> shift) & ((1 << size) - 1)

    def varuint(self):
        value = 0
        for index in range(5):
            byte = self.read(8)
            if index == 4 and byte > 15:
                raise ProbeError('channel-varuint32-overflow')
            value |= (byte & 127) << (7 * index)
            if not byte & 128:
                return value
        raise ProbeError('channel-varuint32-overflow')

    def ubitvar(self):
        head = self.read(6)
        return (head & 15) | (self.read((0, 4, 8, 28)[head >> 4]) << 4)

    def bytes(self, size):
        if size > MAX_BYTES or self.pos + size * 8 > self.end:
            raise ProbeError('channel-body-boundary')
        if self.pos & 7:
            start, shift = self.pos // 8, self.pos & 7
            self.pos += size * 8
            value = int.from_bytes(self.data[start:start + size + 1], 'little') >> shift
            return (value & ((1 << (size * 8)) - 1)).to_bytes(size, 'little')
        start = self.pos // 8
        self.pos += size * 8
        return self.data[start:start + size]


def lz4_block(data, expected_size):
    """Bounded independent LZ4 block, no dictionary or frame format. Exact output size."""
    if not isinstance(data, bytes) or len(data) > MAX_BYTES or type(expected_size) is not int or not 0 <= expected_size <= MAX_BYTES:
        raise ProbeError('lz4-budget')
    out, pos, last_match_start = bytearray(), 0, None

    def length(value):
        nonlocal pos
        if value == 15:
            while True:
                if pos == len(data):
                    raise ProbeError('lz4-length-underflow')
                byte = data[pos]
                pos += 1
                value += byte
                if value > expected_size:
                    raise ProbeError('lz4-output-budget')
                if byte != 255:
                    break
        return value

    while pos < len(data):
        token = data[pos]
        pos += 1
        literals = length(token >> 4)
        if pos + literals > len(data) or len(out) + literals > expected_size:
            raise ProbeError('lz4-literal-boundary')
        out += data[pos:pos + literals]
        pos += literals
        if pos == len(data):
            if len(out) != expected_size or (last_match_start is not None and (literals < 5 or len(out) - last_match_start < 12)):
                raise ProbeError('lz4-end-boundary')
            return bytes(out)
        if pos + 2 > len(data):
            raise ProbeError('lz4-offset-underflow')
        offset = int.from_bytes(data[pos:pos + 2], 'little')
        pos += 2
        if offset == 0 or offset > len(out):
            raise ProbeError('lz4-invalid-offset')
        match = length(token & 15) + 4
        if len(out) + match > expected_size:
            raise ProbeError('lz4-output-budget')
        last_match_start = len(out)
        for _ in range(match):
            out.append(out[-offset])
    raise ProbeError('lz4-missing-final-literals')


@dataclass(frozen=True)
class ChannelFrame:
    reliable: bool
    compressed: bool
    reliable_tick_hint: int | None
    sequence: int | None
    acknowledgement: int | None
    history_raw: tuple[int, ...]
    body: bytes = field(repr=False)


def decode_frame(data: bytes, *, gns_reliable: bool):
    """Require the actual GNS message's reliability flag; no transport inference."""
    if type(gns_reliable) is not bool:
        raise ProbeError('gns-reliability-required')
    reader = Bits(data)
    tag = reader.varuint()
    if tag not in (1, 2, 3, 4):
        raise ProbeError('unsupported-channel-tag')
    reliable, compressed = tag in (1, 3), tag in (3, 4)
    # GNS promotes oversized unreliable messages to reliable delivery. The
    # application tag still selects its original sequence/ACK header layout.
    if reliable and not gns_reliable:
        raise ProbeError('channel-reliability-mismatch')
    tick, sequence, ack, history = None, None, None, ()
    if reliable:
        tick = reader.varuint()
    else:
        sequence, ack = reader.varuint(), reader.varuint()
        history = tuple(reader.read(16) for _ in range(3))
    size = reader.varuint() if compressed else None
    if compressed and size == 0:
        raise ProbeError('channel-empty-compressed-body')
    body = reader.bytes((reader.end - reader.pos) // 8)
    if compressed:
        body = lz4_block(body, size)
    return ChannelFrame(reliable, compressed, tick, sequence, ack, history, body)


def reliable_frame(message_bytes: bytes, tick_hint: int):
    """Uncompressed tag 1; caller supplies actual tick context and GNS reliable send."""
    if not isinstance(message_bytes, bytes) or len(message_bytes) > MAX_BYTES - 6:
        raise ProbeError('channel-byte-budget')
    return b'\x01' + encode_varint(uint(tick_hint)) + message_bytes


@dataclass(frozen=True)
class NetMessage:
    message_id: int
    body: bytes = field(repr=False)


def messages(data: bytes, bit_count=None):
    """UBitVar id + unaligned VarInt32 byte length + protobuf bytes. No schema decode.

    Like the observed loop, fewer than 8 trailing bits are padding, not a message.
    Their values are not assumed zero. Does not parse netchannel/GNS headers.
    """
    reader, result = Bits(data, bit_count), []
    while reader.end - reader.pos >= 8:
        if len(result) >= 16384:
            raise ProbeError('channel-message-budget')
        message_id = reader.ubitvar()
        result.append(NetMessage(message_id, reader.bytes(reader.varuint())))
    return result, reader.end - reader.pos


def encode_message(message_id, body):
    uint(message_id)
    if not isinstance(body, bytes) or len(body) > MAX_BYTES - 10:
        raise ProbeError('channel-body-boundary')
    selector = 0 if message_id < 16 else 1 if message_id < 256 else 2 if message_id < 4096 else 3
    extra = (0, 4, 8, 28)[selector]
    header = (message_id & 15) | (selector << 4) | ((message_id >> 4) << 6)
    data = encode_varint(len(body)) + body
    count = 6 + extra + len(data) * 8
    packed = header | (int.from_bytes(data, 'little') << (6 + extra))
    return packed.to_bytes((count + 7) // 8, 'little'), count


def join_messages(encoded):
    """Concatenate exact bit spans; pad only the final byte, never each message."""
    output, used = bytearray(), 0
    for data, count in encoded:
        if not isinstance(data, bytes) or type(count) is not int or count <= 0 or len(data) != (count + 7) // 8:
            raise ProbeError('message-bit-span')
        if used + count > MAX_BYTES * 8:
            raise ProbeError('channel-byte-budget')
        offset, shift = used // 8, used & 7
        output.extend(bytes((used + count + 7) // 8 - len(output)))
        for index, byte in enumerate(data):
            if index == len(data) - 1 and count & 7:
                byte &= (1 << (count & 7)) - 1
            output[offset + index] |= (byte << shift) & 255
            if shift and offset + index + 1 < len(output):
                output[offset + index + 1] |= byte >> (8 - shift)
        used += count
    return bytes(output), used


def unreliable_frame(message_bytes, sequence, acknowledgement, history_raw):
    """Explicit Source 2 header fields. No invented timings, scheduler or SNP ACK."""
    if not isinstance(message_bytes, bytes) or len(message_bytes) > MAX_BYTES - 17:
        raise ProbeError('channel-byte-budget')
    if len(history_raw) != 3:
        raise ProbeError('channel-history-count')
    history = b''.join(uint(value, 16).to_bytes(2, 'little') for value in history_raw)
    return b'\x02' + encode_varint(uint(sequence)) + encode_varint(uint(acknowledgement)) + history + message_bytes


class UnreliableOrder:
    """Observation-only duplicate/out-of-order filter. Does not transmit ACK or retry.

    Reject signed-boundary/wrap cases pending exact initialization/wrap evidence.
    GNS reliable order/fragmentation remain the SDK's responsibility.
    """
    def __init__(self, initial=None):
        if initial is not None and (type(initial) is not int or not 0 <= initial <= 0x7fffffff):
            raise ProbeError('unsupported-sequence-domain')
        self.last = initial

    def accept(self, frame):
        if frame.reliable or type(frame.sequence) is not int or not 0 <= frame.sequence <= 0x7fffffff:
            raise ProbeError('unsupported-sequence-domain')
        if self.last is not None and frame.sequence <= self.last:
            return {'accepted': False, 'gap': 0}
        gap = 0 if self.last is None else frame.sequence - self.last - 1
        self.last = frame.sequence
        return {'accepted': True, 'gap': gap}



class UnreliableFeedback:
    """Source 2 receive acknowledgements, separate from SDK reliable-stream ACKs.

    networksystem 0be6e0 / 0c2230: sequence starts at 1, received starts at 0.
    Three history values describe received, late and missing frames. Latency is
    deliberately 'unmeasured' (0xfffd), never an invented timing measurement.
    """
    UNKNOWN, LATE, DROPPED = 0xfffd, 0xfffe, 0xffff

    def __init__(self):
        self.sequence, self.received = 1, 0
        self.history = {}

    def observe(self, frame):
        if frame.reliable:
            return
        sequence = frame.sequence
        if type(sequence) is not int or not 0 <= sequence <= 0x7fffffff:
            raise ProbeError('unsupported-sequence-domain')
        if sequence <= self.received:
            if self.history.get(sequence) == self.DROPPED:
                self.history[sequence] = self.LATE
            return
        previous = self.received
        self.received = sequence
        self.history = {
            n: (self.UNKNOWN if n == sequence or n <= 0 else
                self.DROPPED if n > previous else self.history.get(n, self.UNKNOWN))
            for n in range(sequence, sequence - 3, -1)
        }

    def frame(self, body=b''):
        if self.sequence > 0x7fffffff:
            raise ProbeError('outgoing-sequence-restart-required')
        packet = unreliable_frame(body, self.sequence, self.received,
            tuple(self.history.get(n, self.UNKNOWN) for n in range(self.received, self.received - 3, -1)))
        self.sequence += 1
        return packet


class ReliableMessageFilter:
    """Fixed engine08b010 application marker, separate from GNS and net sequence.

    Clear/world-reset retains both fields. Replacing the game-client owner resets
    its marker but does not infer removal of the retained channel's filter.
    """
    def __init__(self):
        self.last_tick = 0
        self.filtered = False

    def replace_client_owner(self):
        self.last_tick = 0

    def accept(self, message_id, body):
        if message_id != 61:
            return not self.filtered
        from wire import fields, scalar
        values = fields(body)
        state = scalar(values, 3)
        if state not in (None, 0, 1):
            raise ProbeError('reliable-marker-state')
        tick = scalar(values, 1) or 0
        tick &= 0xffffffff
        if tick & 0x80000000:
            tick -= 0x100000000
        if not state:
            self.filtered = False
        elif tick <= self.last_tick:
            self.filtered = True
        else:
            self.last_tick = tick
        return True
