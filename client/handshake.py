"""Source-backed, in-memory handshake components; NOT a network client.

No sockets, Steam login, ticket generation, password encryption or GNS cryptography.
Callers must supply an authorized SDK ticket and the actual transport/initialization.
Binary payloads contain credentials: never print, persist or upload their contents.
Static scope: engine2 SHA 6456df18...39ee21; see HANDSHAKE-EVIDENCE.md.
"""
from dataclasses import dataclass, field
import struct
from wire import ProbeError, fields, scalar


def uint(value, bits=32):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ProbeError('unsigned-integer-range')
    return value


def encode_varint(value):
    uint(value, 64)
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def number(tag, value):
    return encode_varint(tag << 3) + encode_varint(uint(value))


def blob(tag, value):
    if not isinstance(value, bytes):
        raise ProbeError('bytes-required')
    return encode_varint((tag << 3) | 2) + encode_varint(len(value)) + value


@dataclass(frozen=True)
class Challenge:
    number: int = field(repr=False)
    server_steam_id: int = field(repr=False)
    secure: bool
    context: bytes = field(repr=False)
    auth_protocol: int = 3


def parse_challenge_body(body):
    """Body AFTER inner type 0x41, not UDP or GNS ciphertext. Server-selected auth=2 or auth=3.

    The bounded trailing NUL-string interpretation remains static-derived; real
    ordinary-viewer traffic has not yet confirmed this exact accepted subset.
    """
    if len(body) < 20 or len(body) > 2400:
        raise ProbeError('challenge-size')
    challenge, auth, key_size, server, secure = struct.unpack_from('<IIHQB', body)
    if auth not in (2, 3):
        raise ProbeError('unsupported-auth-protocol')
    if auth == 3 and key_size != 0:
        raise ProbeError('invalid-steam-key-size')
    if secure not in (0, 1):
        raise ProbeError('invalid-secure-flag')
    context = body[19:]
    if not context.endswith(b'\0') or b'\0' in context[:-1]:
        raise ProbeError('challenge-context-boundary')
    return Challenge(challenge, server, bool(secure) if auth == 3 else False, context[:-1], auth)



def connect_payload(*, host_version, challenge: Challenge, auth_steam: bytes,
                    player_name: str, encrypted_password: bytes | None,
                    reservation_cookie: int, low_violence: bool):
    """C2S_CONNECT_Message protobuf only; transport framing is a separate layer.

    encrypted_password must be the actual 96-byte transformed password, or None
    only if that authorized source requires no password. Transformation is
    implemented in password.transform_password for the documented bytes subset.
    This does not clear or repurpose relay flags.
    """
    if (challenge.auth_protocol not in (2, 3)
        or (challenge.auth_protocol == 3 and not 8 < len(auth_steam) <= 2048)
        or (challenge.auth_protocol == 2 and auth_steam)):
        raise ProbeError('auth-payload-size-or-protocol')
    name = player_name.encode('utf8')
    if not name or len(name) > 127 or b'\0' in name:
        raise ProbeError('player-name-boundary')
    if encrypted_password is not None and len(encrypted_password) != 96:
        raise ProbeError('encrypted-password-size')
    if type(low_violence) is not bool:
        raise ProbeError('low-violence-type')
    payload = number(1, host_version) + number(2, challenge.auth_protocol) + number(3, challenge.number)
    payload += b'\x21' + struct.pack('<Q', uint(reservation_cookie, 64))
    payload += number(5, int(low_violence))
    if encrypted_password is not None:
        payload += blob(6, encrypted_password)
    payload += blob(7, blob(1, name))
    if challenge.auth_protocol == 3:
        payload += blob(8, auth_steam)
    payload += blob(9, challenge.context)
    if len(payload) > 2400:
        raise ProbeError('connect-size-limit')
    return payload


def signon_payload(state, spawn_count):
    """CNETMsg_SignonState for the queue boundary, message ID 7. No netchannel frame."""
    if state not in range(2, 7):
        raise ProbeError('unsupported-ack-state')
    return number(1, state) + number(2, spawn_count) + number(3, 0)


class SignonSequence:
    """Conservative normal-network subset, starting after validated S2C_CONNECTION.

    No replay/local exceptions. Tracks received states, not a successful session.
    NEW requires its ClientInfo transition; SPAWN requires event-parser and
    network-world initialization. FULL is tracked separately from online success.
    """
    def __init__(self):
        self.state = 2
        self.received_state = 2
        self.full_from_entities = False
        self.spawn_count = None
        self.closed = False
        self.initialization_blocked = False

    def server_info(self, server_count):
        uint(server_count)
        if self.spawn_count is not None and server_count != self.spawn_count:
            self.closed = True
            raise ProbeError('server-count-changed-new-instance-required')
        self.spawn_count = server_count

    def receive(self, message):
        if self.closed:
            raise ProbeError('connection-closed')
        decoded = fields(message)
        state, count = scalar(decoded, 1), scalar(decoded, 2)
        if state is None or state not in range(2, 8) or count is None:
            raise ProbeError('missing-or-unsupported-signon')
        uint(count)
        if self.spawn_count is not None and count not in (self.spawn_count, 0xffffffff):
            raise ProbeError('spawn-count-mismatch')
        if state == self.state == 6 and self.full_from_entities:
            self.received_state = state
            return {'received_state': state}
        if state < self.state or (state >= 3 and state == self.state):
            raise ProbeError('nonadvancing-signon')
        if state > self.state + 1:
            raise ProbeError('skipped-signon-initialization')
        self.state = state
        self.received_state = state
        if state in (3, 5):
            self.initialization_blocked = True
        if state == 7:
            self.closed = True
        return {'received_state': state}

    def finish_new(self):
        # Driver calls only after its actual ClientInfo send, with installed
        # processed callbacks and a real ServerInfo count.
        if self.closed or self.state != 3 or self.spawn_count is None:
            raise ProbeError('new-initialization-order')
        if not self.initialization_blocked:
            raise ProbeError('new-initialization-already-completed')
        self.initialization_blocked = False

    def finish_spawn(self):
        if self.closed or self.state != 5 or self.spawn_count is None:
            raise ProbeError('spawn-initialization-order')
        self.initialization_blocked = False

    def finish_full_snapshot(self):
        # Official 0x180086220 advances SPAWN to FULL after successful decoding
        # of a non-delta entity snapshot; the server need not send state 6 first.
        if (self.closed or self.state != 5 or self.spawn_count is None
            or self.initialization_blocked):
            raise ProbeError('full-snapshot-initialization-order')
        self.state = 6
        self.full_from_entities = True

    def acknowledgement(self):
        if self.closed:
            raise ProbeError('connection-closed')
        # engine2 Connect sends CONNECTED with -1 before ServerInfo exists.
        # The server waits for this acknowledgement before sending that info.
        if self.state == 2 and self.spawn_count is None:
            return 7, signon_payload(2, 0xffffffff)
        if self.spawn_count is None:
            raise ProbeError('serverinfo-missing')
        if self.initialization_blocked:
            raise ProbeError('client-initialization-not-implemented')
        return 7, signon_payload(self.state, self.spawn_count)


def connect_inner_message(payload: bytes):
    """engine2 0x180055a10 -> networksystem vtable+0x28, not raw UDP.

    ff ff ff ff / type 0x6b / varuint32 protobuf byte count / protobuf bytes.
    The observed engine stack writer has a 1,200-byte budget including the prefix.
    An authorized GNS connection must still carry this inner message.
    """
    if not isinstance(payload, bytes) or len(payload) >= 2400:
        raise ProbeError('connect-payload-boundary')
    message = b'\xff\xff\xff\xffk' + encode_varint(len(payload)) + payload
    if len(message) > 1200:
        raise ProbeError('observed-connect-writer-budget')
    return message


def initial_challenge_request(challenge_number=0):
    """Official q context: initial zero, then the last server-provided challenge.

    engine2 057370 uses connect0x%08X and UnreliableNoDelay (flags=5).
    The default cl_resend is 0.5 seconds; the driver owns its bounded scheduler.
    """
    return b'\xff\xff\xff\xffq' + f'connect0x{uint(challenge_number):08X}'.encode('ascii') + b'\0'


def parse_connection_inner(message: bytes):
    """Validated-transport caller supplies plaintext inner S2C_CONNECTION (0x42)."""
    from wire import varint
    if not message.startswith(b'\xff\xff\xff\xffB') or not 16 <= len(message) <= 256:
        raise ProbeError('connection-inner-prefix-or-budget')
    size, pos = varint(message, 5)
    if size > 0x7fffffff or pos > 10 or pos + size > len(message):
        raise ProbeError('connection-inner-length')
    end = pos + size
    # ReplyConnection pads with ASCII '0' until at least 16 bytes, not protobuf data.
    if len(message) != max(16, end) or message[end:] != b'0' * (len(message) - end):
        raise ProbeError('connection-inner-padding')
    decoded = fields(message[pos:end])
    addon = scalar(decoded, 1, 2)
    return {'kind': 'connection-inner', 'addon_name_bytes': None if addon is None else len(addon)}


def signon_message_bits(state, spawn_count):
    """One network message's exact bit count, excluding netchannel/GNS framing.

    ID 7 uses UBitVar's 6-bit short form; VarInt32 length and protobuf bytes
    follow without byte-aligning. Last byte's spare bits are NOT another message.
    """
    payload = signon_payload(state, spawn_count)
    data = encode_varint(len(payload)) + payload
    bit_count = 6 + 8 * len(data)
    packed = (int.from_bytes(data, 'little') << 6) | 7
    return packed.to_bytes((bit_count + 7) // 8, 'little'), bit_count

