#!/usr/bin/env python3
"""Compile a pinned public-domain ICE oracle and compare synthetic bytes only."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
from password import ice1_encrypt, transform_password, _MOD, _XOR, _PERM, _ROT

PIN = 'be57e3d01ac7d7aa6a2cacbfef187c0b46616db0'
HASHES = {'IceKey.cpp': '22870272504b2a7db72f4138401f68717c2b273d1b514a7e81e97d4581cf8e00',
          'IceKey.H': '9da3c9be04f71ea50467411b21bc0ecd978b9efa02dd0d2ab754937335416f3a'}
ENGINE_HASH = '6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21'


def check_tables(binary):
    data = binary.read_bytes()
    if hashlib.sha256(data).hexdigest() != ENGINE_HASH:
        raise ValueError('engine-hash-mismatch')
    pe = struct.unpack_from('<I', data, 60)[0]
    count, optional = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    base = struct.unpack_from('<Q', data, pe + 48)[0]
    sections = [struct.unpack_from('<IIII', data, pe + 24 + optional + i * 40 + 8) for i in range(count)]
    result = []
    for address, expected in [(0x1804a8110, _PERM), (0x1804a8190, _ROT),
        (0x1804a81d0, sum(_MOD, ())), (0x1804a8210, sum(_XOR, ()))]:
        rva = address - base
        section = next((s for s in sections if s[1] <= rva and rva + len(expected) * 4 <= s[1] + s[2]), None)
        if section is None:
            raise ValueError('table-not-file-backed')
        actual = struct.unpack_from('<' + 'I' * len(expected), data, section[3] + rva - section[1])
        if actual != expected:
            raise ValueError('ice-constant-mismatch')
        result.append({'address': hex(address), 'uint32_count': len(expected), 'matched': True})
    return {'binary_sha256': ENGINE_HASH, 'tables': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ice-source', type=Path, required=True, help='Directory containing pinned IceKey.cpp and IceKey.H')
    parser.add_argument('--engine2', type=Path, help='Optional locally held exact official binary, only read for constant comparison')
    parser.add_argument('--output', type=Path, required=True, help='New result JSON; contains synthetic cases only')
    args = parser.parse_args()
    for name, digest in HASHES.items():
        if hashlib.sha256((args.ice_source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('public-oracle-source-hash-mismatch')
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'mathlib').mkdir()
        (root / 'tier0').mkdir()
        shutil.copyfile(args.ice_source / 'IceKey.H', root / 'mathlib/IceKey.H')
        (root / 'tier0/memdbgon.h').write_text('// No memory-debug macros are used by IceKey.\n')
        command = ['g++', '-std=c++20', '-Wall', '-Wextra', '-Wno-unknown-pragmas', '-I', str(root),
            str(args.ice_source / 'IceKey.cpp'), str(Path(__file__).parent / 'native/ice_oracle.cpp'), '-o', str(root / 'oracle')]
        subprocess.run(command, check=True, capture_output=True)
        rng = random.Random(408410)
        cases = [(bytes(rng.randrange(256) for _ in range(8)),
                  bytes(rng.randrange(256) for _ in range(8 * ((i % 12) + 1)))) for i in range(256)]
        passwords = [(0, b'unit-password'), (0xffffffff, b'unit-password'), (0x12345678, bytes(range(1, 96)))]
        cases += [(struct.pack('<II', c ^ 0x5ef8ce12, c ^ 0xaa98e42c), p + bytes(96 - len(p))) for c, p in passwords]
        execution = subprocess.run([str(root / 'oracle')], input=''.join(k.hex() + ' ' + p.hex() + '\n' for k, p in cases),
            check=True, text=True, capture_output=True)
        answers = execution.stdout.splitlines()
        if len(answers) != len(cases):
            raise ValueError('oracle-result-count')
        for (key, plain), answer in zip(cases, answers):
            if ice1_encrypt(key, plain).hex() != answer:
                raise ValueError('independent-oracle-mismatch')
        known = []
        for (challenge, password), answer in zip(passwords, answers[256:]):
            if transform_password(password, challenge).hex() != answer:
                raise ValueError('password-wrapper-mismatch')
            known.append({'challenge': challenge, 'synthetic_password_hex': password.hex(), 'expected_hex': answer})
    report = {'scope': 'SYNTHETIC_ORACLE_AND_STATIC_CONSTANTS_NOT_ONLINE', 'source_sdk_commit': PIN,
        'oracle_source_sha256': HASHES, 'independent_cpp_vectors': 256, 'matches': 256,
        'known_answers': known, 'binary_constants': check_tables(args.engine2) if args.engine2 else None}
    with args.output.open('x') as destination:
        json.dump(report, destination, indent=2)
        destination.write('\n')
    print('256 independent ICE vectors + 3 password cases matched; no game session was used.')


if __name__ == '__main__':
    main()
