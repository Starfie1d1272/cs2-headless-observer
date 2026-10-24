"""Synthetic bit/protobuf builders shared by fixtures and tests."""
import struct
from handshake import blob, number

def bits(v, n): return [(v >> i) & 1 for i in range(n)]

def packed(wire):
    result = bytearray((len(wire) + 7) // 8)
    for i, value in enumerate(wire): result[i // 8] |= value << (i % 8)
    return bytes(result)

def info(): return number(1, 14191) + number(2, 7) + number(11, 1) + number(12, 0) + b'\x6d' + struct.pack('<f', 1/64) + blob(15, b'de_test')

def scalar(v): return [0, 1, 0] + bits(v, 8)  # Native verified PlusOne, finish codebook.

def schema():
    serializer = number(1, 0) + number(2, 0) + number(3, 0)
    field = number(1, 2) + number(2, 1) + number(10, 3)
    return blob(1, serializer) + b''.join(blob(2, s) for s in (b'Root', b'value', b'uint32', b'fixed8')) + blob(3, field)

def table():
    base = packed(scalar(5))
    wire = [1, 1, 0] + bits(48, 8) + bits(0, 8) + [1] + bits(len(base), 17)
    for b in base: wire += bits(b, 8)
    return blob(1, b'instancebaseline') + number(2, 1) + blob(7, packed(wire))

def full(tick):
    wire = bits(0, 6) + bits(2, 2) + [0] + bits(1, 17) + bits(0, 8) + scalar(9)
    return number(2, 1) + number(10, 0) + number(12, tick) + blob(7, packed(wire)) + blob(19, b'')
