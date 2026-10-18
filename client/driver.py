#!/usr/bin/env python3
"""Explicit local ordinary-viewer research driver. Never invoked by import/tests.

Native SDK authentication -> actual first q -> validated challenge -> callback-gated
user ticket -> known-password connect -> channel receive -> live message consumer.
Requests full schema at NEW and initializes the event-only network world before SPAWN.
"""
import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import struct
import sys
import time
from channel import decode_frame, messages, UnreliableOrder, encode_message, reliable_frame
from handshake import (SignonSequence, connect_inner_message, connect_payload,
                       initial_challenge_request, parse_challenge_body, parse_connection_inner, uint, number)
from live import LiveDecoder, client_info
from password import transform_password
from wire import ProbeError

MAGIC = b'MZRCS2\x01\0'


class DriverError(Exception):
    pass


class ObserverDriver:
    """One session/one receiver. Port is sdk.NativePort in the real invocation.

    Tests use a clearly synthetic port. No success flag can be set by either port.
    Configured source version must match the source, not merely this binary sample.
    """
    def __init__(self, port, *, host_version, password, emit, capture=None, now_ms=0, parser=None):
        uint(host_version)
        if not host_version or not isinstance(password, bytearray) or len(password) > 95 or 0 in password:
            raise DriverError('configuration-boundary')
        self.port, self.host_version = port, host_version
        self._password = password  # Ownership transferred; wiped on connect/close.
        self._challenge = None
        self.challenge_metadata = None
        self._account_id = None
        self._new_sent = False
        self.parser, self.emit = parser, emit
        self._parser_sequence = 0
        self._prespawn_sent = False
        self._spawn_sent = False
        self._full_sent = False
        self._recovery_pending = False
        self._request_full_update = False
        self._recovery_requests = 0
        self._baseline_ack_count = 0
        self._processed_entity_tick = None
        self._ack_tick = None
        self._last_receipt_ms = now_ms
        self.decoder, self.signon = LiveDecoder((lambda _: None) if parser else emit), SignonSequence()
        self.order = UnreliableOrder(initial=0)
        self.capture = capture
        self.phase, self.reason = 'transport', None
        self.start_ms, self.last_ms, self.deadline = now_ms, now_ms, now_ms + 30000
        self.received, self.channel_frames, self.channel_bytes = 0, 0, 0
        self.first_channel_ms = self.last_channel_ms = None
        self.stages = [{'stage': 'transport', 'elapsed_ms': 0}]
        self.native_state = None

    @property
    def done(self):
        return self.phase in ('blocked', 'closed')

    def step(self, now_ms):
        if self.done:
            return
        if now_ms < self.last_ms:
            raise DriverError('monotonic-clock-regressed')
        self.last_ms = now_ms
        if now_ms >= self.deadline:
            raise DriverError('phase-timeout')
        self.port.pump(now_ms)
        if self.port.state != self.native_state:
            self.native_state = self.port.state
            self.stages.append({'stage': 'sdk-state', 'value': self.native_state, 'elapsed_ms': now_ms - self.start_ms})
        if self.port.state == 6:
            raise DriverError('native-session-closed')
        if self.phase == 'transport' and self.port.state == 3:
            if not self.port.remote_id():
                raise DriverError('trusted-peer-missing')
            self.port.send(initial_challenge_request(), 5)
            self.phase, self.deadline = 'challenge', now_ms + 15000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
        if self.phase == 'ticket' and self.port.state == 5:
            self.port.with_auth(self._send_connect)
            self.phase, self.deadline = 'connection', now_ms + 15000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
        if self.parser is not None:
            self.parser.poll(self.emit)
        for _ in range(128):  # Bound work per callback pump; do not starve deadlines.
            if self.parser is not None:
                processed = self.parser.checkpoint['sequence'] if self.parser.checkpoint else 0
                if self._parser_sequence - processed >= 4:
                    break  # Leave transport messages queued while the parser catches up.
            message = self.port.receive()
            if message is None:
                break
            self.received += 1
            self.receive(*message, now_ms)
            if self.done:
                break
        if self.parser is not None and not self.done:
            self.parser.poll(self.emit)
            self._advance_initialization(now_ms)
            self._send_processed_tick(now_ms)

    def _send_connect(self, auth):
        try:
            # SDK Session prefixes its own authenticated Steam64, not the peer's.
            self._account_id = int.from_bytes(auth[:8], 'little') & 0xffffffff
            if not self._account_id:
                raise DriverError('local-account-id-missing')
            payload = connect_payload(host_version=self.host_version, challenge=self._challenge,
                auth_steam=auth, player_name='Mizar observer',
                encrypted_password=transform_password(bytes(self._password), self._challenge.number),
                reservation_cookie=0, low_violence=False)
            self.port.send(connect_inner_message(payload), 5)
        finally:
            self._password[:] = bytes(len(self._password))

    def receive(self, data, reliable, now_ms):
        if self.phase == 'challenge':
            if reliable or not data.startswith(b'\xff\xff\xff\xffA'):
                raise DriverError('unexpected-challenge-message')
            body = data[5:]
            if 20 <= len(body) <= 2400:
                _, auth, key_size, peer, secure = struct.unpack_from('<IIHQB', body)
                self.challenge_metadata = {'auth_protocol': auth, 'key_size': key_size,
                    'secure_flag': secure, 'server_identity_matches': peer == self.port.remote_id(),
                    'context_bytes': len(body) - 19,
                    'context_sha256': hashlib.sha256(body[19:]).hexdigest()}
            challenge = parse_challenge_body(body)
            if challenge.server_steam_id != self.port.remote_id() or not challenge.server_steam_id:
                raise DriverError('challenge-peer-mismatch')
            if challenge.context != b'connect0x00000000':
                raise DriverError('challenge-context-mismatch')
            self._challenge = challenge
            self.port.request_ticket()
            self.phase, self.deadline = 'ticket', now_ms + 30000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
            return
        if self.phase == 'connection':
            if reliable:
                raise DriverError('unexpected-connection-reliability')
            response = parse_connection_inner(data)
            if response['addon_name_bytes']:
                self.phase, self.reason = 'blocked', 'addon-initialization-required'
                return
            # Official Connect queues CONNECTED/-1 before ServerInfo; otherwise
            # both peers wait. A fresh channel's reliable tick context is zero.
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self.stages.append({'stage': 'sent-signon', 'value': 2, 'elapsed_ms': now_ms - self.start_ms})
            self.phase, self.deadline = 'channel', now_ms + 15000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
            self._challenge = None
            return
        if self.phase != 'channel':
            raise DriverError('unexpected-protocol-phase')
        frame = decode_frame(data, gns_reliable=reliable)
        # Never save handshake/tickets/passwords. Only validated channel envelopes
        # reach capture, before order filtering, so duplicates can be reproduced.
        if self.capture is not None:
            self.capture(data, reliable, now_ms - self.start_ms)
        self.channel_frames += 1
        self.channel_bytes += len(data)
        if self.first_channel_ms is None:
            self.first_channel_ms = now_ms
        self.last_channel_ms, self.deadline = now_ms, now_ms + 15000
        if not reliable and not self.order.accept(frame)['accepted']:
            return
        decoded, _ = messages(frame.body)
        for message in decoded:
            if message.message_id == 7:
                self.signon.receive(message.body)
                self.stages.append({'stage': 'received-signon', 'value': self.signon.state, 'elapsed_ms': now_ms - self.start_ms})
            else:
                self.decoder.consume(message.message_id, message.body)
                if message.message_id == 40:
                    self.signon.server_info(self.decoder.server['server_count'])
        if self.parser is not None:
            self._parser_sequence = self.parser.submit(frame.body)
            if any(message.message_id == 55 for message in decoded):
                if self.decoder.tick is None:
                    raise DriverError('entity-packet-without-tick')

        self._advance_initialization(now_ms)

    def _advance_initialization(self, now_ms):
        checkpoint = self.parser.checkpoint if self.parser else None
        if self.parser and (not checkpoint or checkpoint['sequence'] < self._parser_sequence):
            return
        if self.signon.state == 3 and not self._new_sent:
            if self.decoder.server is None:
                raise DriverError('new-before-serverinfo')
            # Empty-table NEW can request the full schema immediately. Existing
            # tables need their callbacks consumed before this transition.
            if self.decoder.tables and (not checkpoint or checkpoint['stringTables'] != len(self.decoder.tables)):
                self.phase, self.reason = 'blocked', 'new-string-table-callbacks-required'
                return
            info = client_info(server_count=self.signon.spawn_count,
                               account_id=self._account_id, send_table_crc=0)
            encoded, _ = encode_message(20, info)
            self.port.send(reliable_frame(encoded, 0), 8)
            self.signon.finish_new()
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._new_sent = True
            self.stages.append({'stage': 'sent-client-info-and-new',
                                'elapsed_ms': now_ms - self.start_ms})
        elif self.signon.state == 4 and not self._prespawn_sent:
            if (not checkpoint or not checkpoint['serverInfo'] or checkpoint['schemaFields'] == 0
                or not self.decoder.classes):
                self.phase, self.reason = 'blocked', 'prespawn-initialization-required'
                return
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._prespawn_sent = True
            self.stages.append({'stage': 'sent-prespawn', 'elapsed_ms': now_ms - self.start_ms})
        if self.signon.state in (4, 5, 6) and checkpoint and checkpoint['schemaFields'] > 0:
            for handle in self.decoder.ready_world_groups():
                encoded, _ = encode_message(13, number(1, handle))
                self.port.send(reliable_frame(encoded, 0), 8)
                self.stages.append({'stage': 'sent-world-ready', 'elapsed_ms': now_ms - self.start_ms})
        if self.signon.state == 5 and not self._spawn_sent:
            if not checkpoint or not checkpoint['schemaFields'] or not self._prespawn_sent:
                raise DriverError('spawn-before-parser-initialization')
            if set(self.decoder.spawn_groups) != self.decoder.ready_spawn_groups:
                return
            self.signon.finish_spawn()
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._spawn_sent = True
            self.stages.append({'stage': 'sent-spawn', 'elapsed_ms': now_ms - self.start_ms})
        if self.signon.state == 6 and not self._full_sent:
            if not self._spawn_sent:
                raise DriverError('full-before-spawn-acknowledgement')
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._full_sent = True
            self.stages.append({'stage': 'received-full', 'elapsed_ms': now_ms - self.start_ms})
        if self.signon.state == 7:
            self.phase, self.reason = 'blocked', 'changelevel-new-instance-required'

    def _send_processed_tick(self, now_ms):
        checkpoint = self.parser.checkpoint if self.parser else None
        if checkpoint is None:
            return
        if not self._full_sent:
            return
        baseline_acks = []
        for receipt in self.parser.pop_receipts():
            if receipt['sequence'] > checkpoint['sequence']:
                raise DriverError('receipt-before-parser-checkpoint')
            if receipt['type'] == 'recovery':
                self._recovery_pending = True
                self._request_full_update = receipt.get('request', True)
                self._processed_entity_tick = None
                baseline_acks.clear()
            else:
                self._recovery_pending = False
                self._processed_entity_tick = receipt['tick']
                if receipt['baselineAck'] is not None:
                    baseline_acks.append((receipt['tick'], receipt['baselineAck']))
        if self._recovery_pending:
            if self._request_full_update and self._ack_tick != 0xffffffff:
                encoded, _ = encode_message(4, number(1, 0xffffffff))
                self.port.send(reliable_frame(encoded, 0), 8)
                self._ack_tick = 0xffffffff
                self._recovery_requests += 1
            return
        for tick, bank in baseline_acks:
            encoded, _ = encode_message(23, number(1, tick) + number(2, bank))
            self.port.send(reliable_frame(encoded, 0), 8)
            self._baseline_ack_count += 1
        if (not self._full_sent or self._processed_entity_tick is None
            or self._ack_tick == self._processed_entity_tick
            or now_ms - self._last_receipt_ms < 100):
            return
        # Only acknowledge entity packets consumed by the actual parser. Never
        # echo a raw network tick while the entity parser is still behind.
        encoded, _ = encode_message(4, number(1, self._processed_entity_tick))
        self.port.send(reliable_frame(encoded, 0), 8)
        self._ack_tick = self._processed_entity_tick
        self._last_receipt_ms = now_ms

    def report(self):
        span = None if self.first_channel_ms is None else self.last_channel_ms - self.first_channel_ms
        return {'phase': self.phase, 'reason': self.reason, 'received_messages': self.received,
                'host_version': self.host_version, 'native_state': self.port.state,
                'native_failure': getattr(self.port, 'failure', None),
                'challenge_metadata': self.challenge_metadata,
                'channel_frames': self.channel_frames, 'channel_bytes': self.channel_bytes,
                'channel_receive_span_ms': span, 'received_signon_state': self.signon.state,
                'stages': self.stages,
                'parser_checkpoint': self.parser.checkpoint if self.parser else None,
                'parser_failure': getattr(self.parser, 'failure_details', None),
                'last_processed_entity_tick': self._processed_entity_tick,
                'last_acknowledged_entity_tick': self._ack_tick,
                'full_update_requests': self._recovery_requests, 'baseline_ack_count': self._baseline_ack_count,
                'net_message_counts': self.decoder.counts,
                'initialization_blockers': ([] if self._full_sent else
                    [self.reason or 'signon-in-progress']),
                'ordinary_viewer_handshake': 'INCONCLUSIVE', 'live_continuous_receipt': 'INCONCLUSIVE',
                'online_success': 'INCONCLUSIVE'}

    def close(self):
        self._password[:] = bytes(len(self._password))
        self._challenge = None
        self._account_id = None
        self.port.close()


def private_file(path, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, mode)


class SampleWriter:
    """Private local channel sample, no endpoint/handshake/auth or packet printouts."""
    def __init__(self, handle):
        self.handle = handle
        handle.write(MAGIC)

    def __call__(self, data, reliable, elapsed_ms):
        decode_frame(data, gns_reliable=reliable)  # Reject all connectionless/auth inputs.
        self.handle.write(struct.pack('<IQB', len(data), elapsed_ms, int(reliable)) + data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--native', type=Path, required=True)
    ap.add_argument('--steam-api', type=Path)
    ap.add_argument('--node', default='node', help='Node runtime for the existing entity parser')
    ap.add_argument('--host-version', type=int, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--seconds', type=int, default=300, choices=range(1, 14401), metavar='1..14400')
    ap.add_argument('--offset', type=int, default=120, choices=range(0, 3601), metavar='0..3600')
    args = ap.parse_args()
    # Source and known password are local prompts, not process arguments/log files.
    endpoint = getpass.getpass('Authorized GOTV numeric IP:port (hidden): ')
    address, separator, port_text = endpoint.rpartition(':')
    try:
        ipaddress.ip_address(address.strip('[]'))
        if not separator or not 0 < int(port_text) < 65536:
            raise ValueError()
    except ValueError:
        raise SystemExit('invalid-numeric-endpoint') from None
    supplied = getpass.getpass('Existing ordinary spectator password (ASCII subset, hidden): ')
    try:
        password = bytearray(supplied.encode('ascii'))
    except UnicodeError:
        raise SystemExit('non-ascii-password-requires-verified-source-encoding') from None
    del supplied
    if not 0 < args.host_version <= 0xffffffff or len(password) > 95 or 0 in password:
        password[:] = bytes(len(password))
        raise SystemExit('configuration-boundary')
    args.output.mkdir(mode=0o700)
    driver = native = events = samples = parser = None
    report, failure = {'online_success': 'INCONCLUSIVE', 'offset_seconds': args.offset}, None
    finalization = []
    def clock(): return time.monotonic_ns() // 1000000
    try:
        from sdk import NativePort, NativeStartError
        events = private_file(args.output / 'events.jsonl', 'w')
        samples = private_file(args.output / 'channel.frames', 'wb')
        from parser_bridge import ParserBridge
        parser = ParserBridge(args.node)
        native = NativePort(args.native, endpoint, clock(), steam_api=args.steam_api)
        del endpoint
        driver = ObserverDriver(native, host_version=args.host_version, password=password,
            emit=lambda event: events.write(json.dumps(event) + '\n'), capture=SampleWriter(samples), now_ms=clock(), parser=parser)
        stop = clock() + args.seconds * 1000
        while not driver.done and clock() < stop:
            driver.step(clock())
            time.sleep(.01)
        if not driver.done:
            driver.reason = 'duration-limit-incomplete'
        report.update(driver.report())
    except BaseException as error:
        # Never print exception text/tracebacks: SDK/source/password data may be present.
        failure = str(error) if isinstance(error, (DriverError, ProbeError)) else 'interrupted' if isinstance(error, KeyboardInterrupt) else 'operation-failed-details-omitted'
        if type(error).__name__ == 'NativeStartError':
            failure = 'native-start-failed'
            report['native_boot_code'], report['steam_init_result'] = error.boot_code, error.init_result
        if driver is not None:
            report.update(driver.report())
        report.update(outcome='failed', reason=failure)
    finally:
        password[:] = bytes(len(password))
        for stage, action in [('close-session', driver.close if driver else native.close if native else None),
                              ('close-parser', parser.close if parser else None),
                              ('close-events', events.close if events else None),
                              ('close-samples', samples.close if samples else None)]:
            if action:
                try: action()
                except BaseException: finalization.append(stage)
        report['finalization_failures'] = finalization
        report['outcome'] = 'failed' if failure or finalization else 'incomplete'
        report['report_written'] = False
        try:
            with private_file(args.output / 'report.json', 'w') as handle:
                # stdout is the final authority for report-written status after close.
                json.dump(report, handle, indent=2); handle.write('\n')
            report['report_written'] = True
        except BaseException:
            report['finalization_failures'].append('write-report')
            report['outcome'] = 'failed'
        print(json.dumps(report), file=sys.stderr if report['outcome'] == 'failed' else sys.stdout)
    return 1 if report['outcome'] == 'failed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
