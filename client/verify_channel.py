#!/usr/bin/env python3
"""Independent liblz4 oracle for synthetic Source 2 channel bodies. No network."""
import argparse
import ctypes
import ctypes.util
import json
from pathlib import Path
import random
from channel import lz4_block, decode_frame
from handshake import encode_varint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    name = ctypes.util.find_library('lz4')
    if not name:
        raise SystemExit('liblz4 required for independent offline oracle')
    lib = ctypes.CDLL(name)
    lib.LZ4_compressBound.argtypes, lib.LZ4_compressBound.restype = [ctypes.c_int], ctypes.c_int
    lib.LZ4_compress_default.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.LZ4_compress_default.restype = ctypes.c_int
    lib.LZ4_versionString.restype = ctypes.c_char_p
    rng = random.Random(410)
    matched, compressed_cases, envelopes = 0, 0, 0
    for i in range(256):
        size = (i * 37) % 8192
        data = (bytes(rng.randrange(256) for _ in range(size)) if i % 3 == 0 else
                (b'unit-only-channel-literals\0' * 400)[:size] if i % 3 == 1 else b'x' * size)
        capacity = lib.LZ4_compressBound(len(data))
        buffer = ctypes.create_string_buffer(capacity)
        n = lib.LZ4_compress_default(data, buffer, len(data), capacity)
        if n <= 0:
            raise ValueError('oracle-compression-failed')
        compressed = buffer.raw[:n]
        if lz4_block(compressed, len(data)) != data:
            raise ValueError('lz4-independent-mismatch')
        if data:  # Engine receive path rejects decompressor result <=0.
            reliable = b'\x03\x11' + encode_varint(len(data)) + compressed
            unreliable = b'\x04\x11\x10' + bytes(6) + encode_varint(len(data)) + compressed
            if decode_frame(reliable, gns_reliable=True).body != data or decode_frame(unreliable, gns_reliable=False).body != data:
                raise ValueError('channel-compression-mismatch')
            envelopes += 2
        matched += 1
        compressed_cases += n < len(data)
    report = {'scope': 'SYNTHETIC_LIBLZ4_ORACLE_NOT_LIVE_TRAFFIC',
        'library': name, 'version': lib.LZ4_versionString().decode('ascii'),
        'matched': matched, 'smaller_than_input': compressed_cases,
        'reliable_and_unreliable_envelopes_verified': envelopes}
    with args.output.open('x') as destination:
        json.dump(report, destination, indent=2)
        destination.write('\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
