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


client = module(sys.argv[1], '659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0')
assert struct.unpack('<Q', client(0x181c630f0 + 0x518, 8))[0] == 0x180b6fcb0
values = list(struct.unpack('<4I', client(0x181c33ed0, 16)))
values += [struct.unpack('<I', client(address, 4))[0] for address in (0x1809f6ea3, 0x1809f6eab)]
assert values == [14, 5, 11, 3, 11, 20]
print(json.dumps({'manifest':'8766757721818354077', 'client_interface_slot':'0x518', 'client_callback':'0x180b6fcb0', 'legacy_profile_writer':'0x1809f6e90', 'legacy_profile_values':values, 'field_order':['coord_integer_bits','coord_fractional_bits','coord_integer_bits_mp','coord_fractional_bits_mp','normal_fractional_bits','angle_bits'], 'method':'fixed-hash static pointers/constants; no native module execution'}, indent=2))
