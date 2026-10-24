#!/usr/bin/env python3
"""Offline oracle: real CS2 Demo packet bodies into the live net-message consumer.

Does NOT turn a Demo into online transport evidence. Needs system libsnappy and the
public fixture used by verify.py. No packet/event bodies are saved in the report.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'client'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'diagnostics'))
import argparse
import collections
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
from channel import messages
from live_probe import LiveDecoder
from wire import fields, scalar, varint

PIN = '143eb78444727c7a8afa29d807272076d14044fc9d7c233035d0b9a176e70f60'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixture', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--oracle-dir', type=Path, required=True)
    args = ap.parse_args()
    data = args.fixture.read_bytes()
    assert hashlib.sha256(data).hexdigest() == PIN
    assert data[:8] == b'PBDEMS2\0'
    lib = ctypes.CDLL(ctypes.util.find_library('snappy'))
    lib.snappy_uncompressed_length.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    lib.snappy_uncompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    def decompress(raw):
        n = ctypes.c_size_t()
        assert lib.snappy_uncompressed_length(raw, len(raw), ctypes.byref(n)) == 0 and n.value <= 64 * 1024**2
        out = ctypes.create_string_buffer(n.value)
        assert lib.snappy_uncompress(raw, len(raw), out, ctypes.byref(n)) == 0
        return out.raw[:n.value]
    counts, weapons, ticks, packet_counts = (collections.Counter() for _ in range(4))
    projected = {name: [] for name in ('weapon_fire', 'player_death', 'round_start', 'round_end')}
    net_projected = {name: [] for name in projected}
    frame_projected = {name: [] for name in projected}
    event_net_deltas = collections.Counter()
    event_frame_deltas, net_frame_deltas = collections.Counter(), collections.Counter()
    demo_tick = None
    def emit(event):
        counts[event['kind']] += 1
        if event['kind'] == 'weapon_fire': weapons[event['weapon']] += 1
        ticks[str(event['tick_source'])] += 1
        projected[event['kind']].append((event['tick'], event['weapon']))
        net_projected[event['kind']].append((event['net_tick'], event['weapon']))
        frame_projected[event['kind']].append((demo_tick, event['weapon']))
        if event['net_tick'] is not None and event['event_server_tick'] is not None:
            event_net_deltas[event['event_server_tick'] - event['net_tick']] += 1
        if event['event_server_tick'] is not None:
            event_frame_deltas[event['event_server_tick'] - demo_tick] += 1
        if event['net_tick'] is not None:
            net_frame_deltas[event['net_tick'] - demo_tick] += 1
    decoder, pos, packets = LiveDecoder(emit), 16, 0
    while pos < len(data):
        command, pos = varint(data, pos)
        demo_tick, pos = varint(data, pos)
        length, pos = varint(data, pos)
        assert pos + length <= len(data)
        raw, pos = data[pos:pos + length], pos + length
        kind = command & ~64
        if kind == 0: break
        if kind not in (7, 8): continue
        if command & 64: raw = decompress(raw)
        packet = scalar(fields(raw, limit=4 * 1024**2), 3, 2)
        if not packet: continue
        packets += 1
        decoded, _ = messages(packet)
        for message in decoded:
            packet_counts[message.message_id] += 1
            decoder.consume(message.message_id, message.body)
    expected, comparison = {}, {}
    for name in projected:
        oracle = json.loads((args.oracle_dir / ('oracle-' + name + '.json')).read_text())
        expected[name] = len(oracle)
        comparison[name] = {'count': len(projected[name]), 'oracle_count': len(oracle),
                            'ticks_match': sorted(tick for tick, _ in projected[name]) == sorted(row['tick'] for row in oracle)}
        if name in ('weapon_fire', 'player_death'):
            comparison[name]['tick_weapon_match'] = sorted(projected[name]) == sorted((row['tick'], row['weapon']) for row in oracle)
            comparison[name]['net_tick_weapon_match'] = sorted(net_projected[name]) == sorted((row['tick'], row['weapon']) for row in oracle)
            comparison[name]['demo_frame_tick_weapon_match'] = sorted(frame_projected[name]) == sorted((row['tick'], row['weapon']) for row in oracle)
    supported_match = all(comparison[name]['demo_frame_tick_weapon_match'] for name in ('weapon_fire', 'player_death'))
    result = {'evidence': 'REAL_DEMO_PACKET_BODIES_OFFLINE_NOT_GNS', 'fixture_sha256': PIN,
              'packets': packets, 'net_message_counts': dict(packet_counts), 'events': dict(counts),
              'expected_from_independent_demoparser2': expected, 'counts_match': dict(counts) == expected,
              'comparison': comparison, 'supported_projection_match': supported_match,
              'event_minus_net_tick_histogram': dict(event_net_deltas),
              'event_minus_demo_frame_tick_histogram': dict(event_frame_deltas),
              'net_minus_demo_frame_tick_histogram': dict(net_frame_deltas),
              'clock_note': 'Demo oracle uses file frame ticks. Live event.server_tick and net_Tick remain separate; no offset is applied.',
              'full_event_coverage': False,
              'round_event_gap': 'fixture round events are derived from game-rules entities; entity reconstruction is not implemented',
              'weapon_fire_awp': weapons['weapon_awp'], 'weapon_fire_taser': weapons['weapon_taser'],
              'tick_sources': dict(ticks), 'unresolved_events': decoder.unresolved_events,
              'initialization_blockers': decoder.blockers(), 'online_success': 'INCONCLUSIVE'}
    with args.output.open('x') as f: json.dump(result, f, indent=2); f.write('\n')
    print(json.dumps(result))
    # Exit 2 explicitly means the full target has known missing event coverage.
    return 2 if supported_match else 1


if __name__ == '__main__':
    raise SystemExit(main())
