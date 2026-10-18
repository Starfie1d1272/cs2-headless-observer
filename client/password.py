"""Normal known-password transform, static-derived; no authentication bypass or socket.

ICE level 1 follows Matthew Kwan's public-domain 1996 algorithm, independently
checked against Valve's published IceKey.cpp; see PASSWORD-EVIDENCE.md.
Only the existing known ordinary password is accepted. Never log returned bytes.
"""
from functools import lru_cache
import struct
from wire import ProbeError

_MOD = ((333, 313, 505, 369), (379, 375, 319, 391), (361, 445, 451, 397), (397, 425, 395, 505))
_XOR = ((0x83, 0x85, 0x9b, 0xcd), (0xcc, 0xa7, 0xad, 0x41), (0x4b, 0x2e, 0xd4, 0x33), (0xea, 0xcb, 0x2e, 0x04))
_PERM = (1, 128, 1024, 8192, 524288, 2097152, 16777216, 1073741824,
         8, 32, 256, 16384, 65536, 8388608, 67108864, 536870912,
         4, 16, 512, 32768, 131072, 4194304, 134217728, 268435456,
         2, 64, 2048, 4096, 262144, 1048576, 33554432, 2147483648)
_ROT = (0, 1, 2, 3, 2, 1, 3, 0, 1, 3, 2, 0, 3, 1, 0, 2)


def _multiply(a, b, modulus):
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        b >>= 1
        if a >= 256:
            a ^= modulus
    return result


@lru_cache(maxsize=1)  # Public constant tables only; never caches keys/passwords.
def _sboxes():
    tables = []
    for box in range(4):
        table = []
        for index in range(1024):
            column, row = (index >> 1) & 255, (index & 1) | ((index & 512) >> 8)
            value, modulus = column ^ _XOR[box][row], _MOD[box][row]
            square = _multiply(value, value, modulus)
            cube = _multiply(value, square, modulus)
            sixth = _multiply(cube, cube, modulus)
            seventh = _multiply(value, sixth, modulus) << (24 - 8 * box)
            table.append(sum(_PERM[bit] for bit in range(32) if seventh & (1 << bit)))
        tables.append(tuple(table))
    return tuple(tables)


def _schedule(key):
    words = list(reversed(struct.unpack('>4H', key)))
    schedule = []
    for rotation in _ROT:  # Two 8-round schedules, same evolving words, ICE level 1.
        subkey = [0, 0, 0]
        for step in range(15):
            slot = step % 3
            for column in range(4):
                index = (rotation + column) & 3
                bit = words[index] & 1
                subkey[slot] = (subkey[slot] << 1) | bit
                words[index] = (words[index] >> 1) | ((bit ^ 1) << 15)
        schedule.append(tuple(subkey))
    return schedule


def _round(value, key, tables):
    left = ((value >> 16) & 1023) | (((value >> 14) | (value << 18)) & 0xffc00)
    right = (value & 1023) | ((value << 2) & 0xffc00)
    salt = key[2] & (left ^ right)
    left ^= salt ^ key[0]
    right ^= salt ^ key[1]
    return tables[0][left >> 10] | tables[1][left & 1023] | tables[2][right >> 10] | tables[3][right & 1023]


def ice1_encrypt(key: bytes, plaintext: bytes):
    """ICE-1, independent 8-byte blocks. Not a replacement for GNS encryption."""
    if not isinstance(key, bytes) or len(key) != 8 or not isinstance(plaintext, bytes) or len(plaintext) % 8:
        raise ProbeError('ice-input-boundary')
    schedule, tables = _schedule(key), _sboxes()
    result = bytearray()
    for offset in range(0, len(plaintext), 8):
        left, right = struct.unpack_from('>II', plaintext, offset)
        for i in range(0, 16, 2):
            left ^= _round(right, schedule[i], tables)
            right ^= _round(left, schedule[i + 1], tables)
        result += struct.pack('>II', right, left)
    return bytes(result)


def transform_password(password: bytes, challenge: int):
    """Caller supplies exact existing password bytes; no guessed text encoding.

    Conservative subset: reject embedded NUL and >95 bytes instead of silently
    applying the official V_strncpy truncation. Empty password omits the field.
    The real platform interoperability and non-ASCII text encoding remain untested.
    Python does not guarantee erasure of all copies; the caller must keep them local.
    """
    if type(challenge) is not int or not 0 <= challenge <= 0xffffffff:
        raise ProbeError('challenge-range')
    if not isinstance(password, bytes) or len(password) > 95 or b'\0' in password:
        raise ProbeError('password-byte-boundary')
    if not password:
        return None
    key = struct.pack('<II', challenge ^ 0x5ef8ce12, challenge ^ 0xaa98e42c)
    return ice1_encrypt(key, password + bytes(96 - len(password)))
