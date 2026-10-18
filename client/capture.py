#!/usr/bin/env python3
"""Read-only local evidence collector. Does not launch/login/connect/capture/decrypt CS2."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import uuid

CLOUD_ENGINE_SHA = '6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21'


def binary_identity(path):
    # Read bounded existing official files; no binary bytes are copied to the output.
    if path.stat().st_size > 64 * 1024**2:
        raise ValueError('binary-size-limit')
    data = path.read_bytes()
    if data[:2] != b'MZ' or len(data) < 64:
        raise ValueError('not-pe')
    off = struct.unpack_from('<I', data, 60)[0]
    if off + 24 > len(data) or data[off:off + 4] != b'PE\0\0':
        raise ValueError('invalid-pe-header')
    digest = hashlib.sha256(data).hexdigest()
    machine, _, timestamp = struct.unpack_from('<HHI', data, off + 4)
    # RSDS byte signature candidates, not a claim that debug symbols are available.
    pdb = []
    for match in re.finditer(b'RSDS', data):
        pos = match.start()
        if pos + 24 <= len(data):
            pdb.append({'guid': str(uuid.UUID(bytes_le=data[pos + 4:pos + 20])),
                        'age': struct.unpack_from('<I', data, pos + 20)[0]})
    return {'file': path.name, 'bytes': len(data), 'sha256': digest,
            'coff_timestamp': timestamp, 'machine': hex(machine),
            'rsds_candidates': pdb[:8], 'authenticode_verified': False,
            'matches_cloud_engine': digest == CLOUD_ENGINE_SHA if path.name == 'engine2.dll' else None}


def safe_console_lines(path):
    """Strict projections only: never copy source lines, addresses, identities or context strings."""
    patterns = [
        ('challenge', r'Received S2C_CHALLENGE \[\d+ auth (\d{1,3})\]', ['auth_protocol']),
        # The value labelled "protocol" in this log is passed from challenge;
        # omit it instead of exporting it or treating it as a protocol version.
        ('connect', r'Sending C2S_CONNECT \[(\d{1,10}) protocol \d{1,10} auth (\d{1,3})\]',
         ['host_version', 'auth_protocol']),
        ('disconnect', r'\b(NETWORK_DISCONNECT_[A-Z_]{1,80})\b', ['reason']),
        ('signon', r'SignonState (NONE|CHALLENGE|CONNECTED|NEW|PRESPAWN|SPAWN|FULL|CHANGELEVEL) -> (NONE|CHALLENGE|CONNECTED|NEW|PRESPAWN|SPAWN|FULL|CHANGELEVEL)', ['before', 'after']),
    ]
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError('console-size-limit')
    result = []
    for number, line in enumerate(path.read_text(encoding='utf8', errors='replace').splitlines(), 1):
        for kind, pattern, keys in patterns:
            match = re.search(pattern, line)
            if match:
                result.append({'line': number, 'kind': kind, **dict(zip(keys, match.groups()))})
        if 'CSteam3Client::GetAuthSessionTicket to ' in line:
            kind = next((k for k in ['SteamID', 'IP', 'localhost'] if ' to ' + k in line), 'unknown')
            result.append({'line': number, 'kind': 'ticket-request-log', 'target_kind': kind})
        if 'GetAuthSessionTicket failed' in line:
            result.append({'line': number, 'kind': 'ticket-failed-log'})
    return result[:4096]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True, help='Selected Counter-Strike Global Offensive installation root')
    parser.add_argument('--output', type=Path, required=True, help='New private directory')
    parser.add_argument('--demo', type=Path, help='Existing authorized recording to observe')
    parser.add_argument('--console-log', type=Path, help='Optional existing private official console log')
    parser.add_argument('--seconds', type=int, default=90)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('seconds must be 1..300')
    args.output.mkdir(mode=0o700)
    result = {'scope': 'LOCAL_READ_ONLY_EVIDENCE', 'began_utc': datetime.now(timezone.utc).isoformat(),
              'binary_identity': [], 'steam_inf': {}, 'demo_samples': [],
              'ordinary_client_connected': 'USER_OBSERVATION_REQUIRED',
              'custom_viewer_handshake': 'NOT_IMPLEMENTED', 'live_game_data': 'INCONCLUSIVE'}
    try:
        for name in ['engine2.dll', 'networksystem.dll', 'cs2.exe']:
            result['binary_identity'].append(binary_identity(args.game_dir / 'game/bin/win64' / name))
        inf = args.game_dir / 'game/csgo/steam.inf'
        if inf.exists():
            if inf.stat().st_size > 4096:
                raise ValueError('steam-inf-size-limit')
            for line in inf.read_text().splitlines():
                key, _, value = line.partition('=')
                if key in ['ClientVersion', 'ServerVersion', 'SourceRevision'] and re.fullmatch(r'\d{1,12}', value):
                    result['steam_inf'][key] = value
                if key == 'PatchVersion' and re.fullmatch(r'\d{1,4}(\.\d{1,4}){1,4}', value):
                    result['steam_inf'][key] = value
        if args.console_log:
            result['console_projection'] = safe_console_lines(args.console_log)
        began = time.monotonic()
        while args.demo:
            stat = args.demo.stat()
            result['demo_samples'].append({'elapsed_seconds': time.monotonic() - began,
                'utc': datetime.now(timezone.utc).isoformat(), 'bytes': stat.st_size,
                'file_id': [stat.st_dev, stat.st_ino]})
            if time.monotonic() - began >= args.seconds:
                break
            time.sleep(max(0, min(5, args.seconds - (time.monotonic() - began))))
    except (OSError, ValueError, struct.error) as error:
        # Unknown exception text may contain private paths or arbitrary file content.
        result['failure'] = {'category': type(error).__name__, 'errno': getattr(error, 'errno', None)}
        code = 1
    else:
        code = 0
    (args.output / 'capture.json').write_text(json.dumps(result, indent=2) + '\n')
    print('capture.json written; inspect the report. No game connection was attempted.')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
