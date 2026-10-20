"""Read-only fixed-build PE evidence. Does not execute or copy native code."""
import hashlib
import json
import struct
import sys
from pathlib import Path


def module(path, expected):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('fixed-module-sha-mismatch')
    pe = struct.unpack_from('<I', data, 60)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    optional = struct.unpack_from('<H', data, pe + 20)[0]
    sections = []
    for i in range(count):
        virtual_size, rva, raw_size, raw = struct.unpack_from(
            '<IIII', data, pe + 24 + optional + 40 * i + 8)
        sections.append((rva, raw_size, raw))

    def read(address, length):
        for rva, size, raw in sections:
            offset = address - 0x180000000 - rva
            if 0 <= offset and offset + length <= size:
                return data[raw + offset:raw + offset + length]
        raise ValueError('unmapped-read')
    return read


engine = module(sys.argv[1], '6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21')
client = module(sys.argv[2], '659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0')
readq = lambda read, address: struct.unpack('<Q', read(address, 8))[0]
thunk = readq(engine, 0x180540bc8 + 0x480)
assert thunk == 0x18006bd20
jump = engine(thunk, 5)
assert jump[0] == 0xe9
target = thunk + 5 + struct.unpack('<i', jump[1:])[0]
assert target == 0x1800610c0
assert readq(client, 0x181c630f0 + 0x410) == 0x180b6de20
assert readq(client, 0x182226d60) == 0x182228dd8
assert readq(client, 0x182228dd8) == 0x181c2bb78
assert readq(client, 0x181c2bb78) == 0x1809b0170
print(json.dumps({
    'manifest': '8766757721818354077',
    'engine_clear_dispatch': {
        'vtable': '0x180540bc8', 'slot': '0x480',
        'thunk': hex(thunk), 'direct_jump_target': hex(target)},
    'game_table_callback': {
        'source2client_slot': '0x410', 'thunk': '0x180b6de20',
        'object': '0x182228dd8', 'vtable': '0x181c2bb78',
        'target': '0x1809b0170'},
    'method': 'hash-verified static PE pointers and direct jump; no native execution',
}, indent=2))
