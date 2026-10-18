#!/usr/bin/env python3
"""Offline Source 2/GNS evidence probe. No sockets, login, decryption or credentials output."""
import argparse
import ipaddress
import json
import os
import struct
from pathlib import Path

PIN = '5ab573fa8afb5b8db98869d79ed79399fca6e747'
STATES = ['NONE', 'CHALLENGE', 'CONNECTED', 'NEW', 'PRESPAWN', 'SPAWN', 'FULL', 'CHANGELEVEL']
class ProbeError(ValueError):
    pass


GNS_NAMES = {32: 'challenge_request', 33: 'challenge_reply', 34: 'connect_request',
             35: 'connect_ok', 36: 'connection_closed', 37: 'no_connection'}


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ProbeError('truncated-varint')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise ProbeError('overflow-varint')
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ProbeError('overflow-varint')


def fields(data, *, limit=65535):
    """Bounded protobuf wire inspection; bytes fields stay opaque and are never printed."""
    if type(limit) is not int or not 0 < limit <= 4 * 1024**2 or len(data) > limit:
        raise ProbeError('payload-limit')
    pos, result = 0, {}
    while pos < len(data):
        key, pos = varint(data, pos)
        number, wire = key >> 3, key & 7
        if not 0 < number < (1 << 29):
            raise ProbeError('invalid-field-number')
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = varint(data, pos)
            else:
                size = 8 if wire == 1 else 4
            if size > len(data) - pos:
                raise ProbeError('truncated-field')
            value = data[pos:pos + size]
            pos += size
        else:
            raise ProbeError('unsupported-wire-type')
        result.setdefault(number, []).append((wire, value))
    return result


def scalar(f, number, wire=0):
    values = f.get(number, [])
    if not values:
        return None
    if len(values) != 1 or values[0][0] != wire:
        raise ProbeError('ambiguous-or-wrong-wire-field')
    return values[0][1]


def byte_length(f, number):
    value = scalar(f, number, 2)
    return None if value is None else len(value)


def payload_metadata(kind, data):
    f = fields(data)
    if kind == 'c2s-connect':
        if len(data) > 2400:
            raise ProbeError('connect-size-limit')
        players = f.get(7, [])
        if any(wire != 2 for wire, _ in players):
            raise ProbeError('invalid-splitplayers')
        return {'kind': kind, 'host_version': scalar(f, 1), 'auth_protocol': scalar(f, 2),
                'challenge_present': scalar(f, 3) is not None,
                'reservation_present': scalar(f, 4, 1) is not None,
                'encrypted_password_bytes': byte_length(f, 6),
                'auth_steam_bytes': byte_length(f, 8), 'splitplayers': len(players),
                'challenge_context_bytes': byte_length(f, 9),
                'warning': 'schema-only; not a validated handshake or raw UDP decoder'}
    state = scalar(f, 1)
    if state is None or state >= len(STATES):
        raise ProbeError('unknown-signon-state')
    return {'kind': kind, 'state': STATES[state], 'spawn_count': scalar(f, 2),
            'warning': 'decoded message only; does not authenticate origin or prove live receipt'}


def gns_metadata(data):
    if not data:
        return {'kind': 'empty'}
    tag = data[0]
    if tag not in GNS_NAMES:
        return {'kind': 'data_candidate' if tag & 128 else 'unclassified'}
    if tag in (32, 36):
        if len(data) < 512:
            raise ProbeError('short-padded-control')
        size = int.from_bytes(data[1:3], 'little')
        if size == 0 or size > len(data) - 3:
            raise ProbeError('invalid-padded-control-length')
        body = data[3:3 + size]
    else:
        body = data[1:]
    f = fields(body)
    result = {'kind': GNS_NAMES[tag]}
    # Presence and lengths only. Do not expose certs, identities, challenge, or debug text.
    if tag in (34, 35):
        result['cert_bytes'] = byte_length(f, 4 if tag == 34 else 8)
        result['crypt_bytes'] = byte_length(f, 7)
    if tag in (32, 33):
        result['protocol_version'] = scalar(f, 4)
    if tag == 36:
        result['reason_code'] = scalar(f, 3)
    return result


def pcap_packets(path):
    """Classic PCAP only; Ethernet, raw IP, Linux cooked v1. No live capture privileges."""
    with path.open('rb') as handle:
        header = handle.read(24)
        formats = {b'\xd4\xc3\xb2\xa1': ('<', 1e6), b'\xa1\xb2\xc3\xd4': ('>', 1e6),
                   b'\x4d\x3c\xb2\xa1': ('<', 1e9), b'\xa1\xb2\x3c\x4d': ('>', 1e9)}
        if len(header) != 24 or header[:4] not in formats:
            raise ProbeError('classic-pcap-required; convert pcapng with editcap -F pcap')
        endian, precision = formats[header[:4]]
        major, minor, _, _, snaplen, link = struct.unpack(endian + 'HHIIII', header[4:])
        if (major, minor) != (2, 4) or link not in (1, 101, 113) or snaplen > 262144:
            raise ProbeError('unsupported-pcap-header')
        while chunk := handle.read(16):
            if len(chunk) != 16:
                raise ProbeError('truncated-pcap-record')
            sec, fraction, captured, original = struct.unpack(endian + 'IIII', chunk)
            if captured > snaplen or captured > original or captured > 262144 or fraction >= precision:
                raise ProbeError('invalid-pcap-record')
            data = handle.read(captured)
            if len(data) != captured or captured != original:
                raise ProbeError('truncated-packet')
            yield sec + fraction / precision, link, data


def udp_ipv4(link, data):
    pos = {1: 14, 101: 0, 113: 16}[link]
    if len(data) < pos + 20:
        return None
    if link == 1:
        ethertype = int.from_bytes(data[12:14], 'big')
        while ethertype in (0x8100, 0x88a8):
            if len(data) < pos + 4:
                raise ProbeError('truncated-vlan')
            ethertype = int.from_bytes(data[pos + 2:pos + 4], 'big')
            pos += 4
        if ethertype != 0x800:
            return None
    if link == 113 and data[14:16] != b'\x08\x00':
        return None
    ip = data[pos:]
    if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 17:
        return None
    ihl, length = (ip[0] & 15) * 4, int.from_bytes(ip[2:4], 'big')
    if ihl < 20 or length < ihl + 8 or len(ip) < length:
        raise ProbeError('invalid-ipv4-length')
    if int.from_bytes(ip[6:8], 'big') & 0x3fff:
        raise ProbeError('fragmented-ipv4-not-supported')
    udp = ip[ihl:length]
    sport, dport, size = struct.unpack('!HHH', udp[:6])
    if size < 8 or size != len(udp):
        raise ProbeError('invalid-udp-length')
    return ((str(ipaddress.ip_address(ip[12:16])), sport),
            (str(ipaddress.ip_address(ip[16:20])), dport), udp[8:])


def inspect_pcap(path, server, write):
    flows, skipped, packets = {}, 0, 0
    for timestamp, link, packet in pcap_packets(path):
        decoded = udp_ipv4(link, packet)
        if decoded is None:
            skipped += 1
            continue
        src, dst, data = decoded
        if server not in (src, dst):
            skipped += 1
            continue
        peer = dst if src == server else src
        if peer not in flows:
            if len(flows) >= 64:
                raise ProbeError('flow-limit')
            flows[peer] = {'id': len(flows) + 1, 'first': timestamp, 'last': timestamp,
                           'packets': 0, 'bytes': 0, 'data_candidates': 0, 'connect_ok': 0,
                           'closed': 0}
        flow = flows[peer]
        metadata = gns_metadata(data)
        flow['last'] = timestamp
        flow['packets'] += 1
        flow['bytes'] += len(data)
        flow['data_candidates'] += metadata['kind'] == 'data_candidate'
        flow['connect_ok'] += metadata['kind'] == 'connect_ok'
        flow['closed'] += metadata['kind'] in ('connection_closed', 'no_connection')
        packets += 1
        write({'kind': 'packet', 'sequence': packets, 'capture_unix_seconds': timestamp,
               'flow': flow['id'], 'direction': 'in' if src == server else 'out',
               'udp_bytes': len(data), 'transport': metadata})
    if not packets:
        raise ProbeError('no-matching-udp-packets')
    return {'kind': 'summary', 'flows': list(flows.values()), 'skipped_packets': skipped,
            'matched_packets': packets, 'ordinary_viewer_signon': 'INCONCLUSIVE',
            'continuous_game_data': 'INCONCLUSIVE', 'match_events': 'NOT_DECODED',
            'warning': 'GNS-shaped packets are candidates, not authenticated game messages; no decryption'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['pcap', 'c2s-connect', 'signon'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--server', help='Exact authorized IPv4:UDP-port; never written to output')
    args = parser.parse_args()
    try:
        server = None
        if args.mode == 'pcap':
            if not args.server:
                raise ProbeError('server-required')
            host, port = args.server.rsplit(':', 1)
            server = (str(ipaddress.IPv4Address(host)), int(port))
            if not 0 < server[1] < 65536:
                raise ProbeError('invalid-port')
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf8') as output:
            def write(row):
                output.write(json.dumps(row, separators=(',', ':')) + '\n')
            write({'kind': 'metadata', 'schema': 'mizar.viewer.wire.v1', 'protocol_snapshot': PIN,
                   'configured_offset_seconds': 120, 'offset_verified': False})
            if args.mode == 'pcap':
                write(inspect_pcap(args.input, server, write))
            else:
                with args.input.open('rb') as source:
                    data = source.read(65536)
                write(payload_metadata(args.mode, data))
        return 0
    except (OSError, ValueError) as error:
        # Input and exception text may contain endpoints, paths, or arbitrary credentials.
        print(json.dumps({'result': 'FAIL', 'reason': str(error) if isinstance(error, ProbeError) else type(error).__name__,
                          'detail': 'Inspect input locally; partial output is not success.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
