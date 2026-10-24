#!/usr/bin/env python3
"""Explicit local ordinary-viewer research driver. Never invoked by import/tests.

Native SDK authentication -> actual first q -> validated challenge -> callback-gated
user ticket -> known-password connect -> channel receive -> live message consumer.
Requests full schema at NEW and initializes the event-only network world before SPAWN.
"""
import argparse
from collections import deque
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import struct
import sys
sys.dont_write_bytecode = True  # Installed component files stay immutable across launches.
import time
from channel import decode_frame, messages, UnreliableOrder, UnreliableFeedback, encode_message, reliable_frame, ReliableMessageFilter, join_messages
from handshake import (SignonSequence, connect_inner_message, connect_payload,
                       initial_challenge_request, parse_challenge_body, parse_connection_inner, uint, number)
from control import ControlDecoder, client_info, int32
from observer_settings import ObserverSettings
from password import transform_password
from wire import ProbeError, fields, scalar
from process_io import PublicRecords, ManagedOwner, OutputWriter, encode_record

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
        self._password = password  # Owned only through connection/retries; wiped on acceptance/close.
        self._challenge = None
        self._last_challenge_request_ms = None
        self._challenge_contexts = set()
        self._challenge_requests = 0
        self.challenge_metadata = None
        self._account_id = None
        self.settings = ObserverSettings()
        self._query_window_ms = now_ms
        self._query_count = 0
        self._new_sent = False
        self.parser, self.emit = parser, PublicRecords(emit)
        self._parser_sequence = 0
        self._prespawn_sent = False
        self._spawn_sent = False
        self._full_snapshot_processed = False
        self._full_sent = False
        self._ever_full = False
        self._recovery_pending = False
        self._request_full_update = False
        self._full_update_outstanding = False
        self._recovery_requests = 0
        self._baseline_ack_count = 0
        self._event_subscription_pending = None
        self._processed_entity_tick = None
        self._ack_tick = None
        self._last_receipt_ms = now_ms
        self.decoder, self.signon = ControlDecoder(), SignonSequence()
        self.order = UnreliableOrder(initial=0)
        self.feedback = UnreliableFeedback()
        self.reliable_filter = ReliableMessageFilter()
        self._last_feedback_ms = now_ms
        self._feedback_sent = 0
        self.capture = capture
        self.phase, self.reason = 'transport', None
        self.start_ms, self.last_ms, self.deadline = now_ms, now_ms, now_ms + 30000
        self.received, self.channel_frames, self.channel_bytes = 0, 0, 0
        self.first_channel_ms = self.last_channel_ms = None
        self.stages = deque([{'stage': 'transport', 'elapsed_ms': 0}], maxlen=512)
        self._drain_deadline = None
        self.drain_completed = False
        self.native_state = None
        self.initialization_deadline = now_ms + 30000

    @property
    def done(self):
        return self.phase in ('blocked', 'closed')

    def step(self, now_ms):
        if self.done:
            return
        if now_ms < self.last_ms:
            raise DriverError('monotonic-clock-regressed')
        self.last_ms = now_ms
        if self._drain_deadline is not None and now_ms >= self._drain_deadline:
            raise DriverError('source-drain-timeout')
        if self._drain_deadline is None and now_ms >= self.deadline:
            raise DriverError('phase-timeout')
        self.port.pump(now_ms)
        if self._drain_deadline is not None and getattr(self.port, 'failure', 7) != 7:
            raise DriverError('source-drain-native-failed')
        if self.port.state != self.native_state:
            self.native_state = self.port.state
            self.stages.append({'stage': 'sdk-state', 'value': self.native_state, 'elapsed_ms': now_ms - self.start_ms})
        if self.port.state == 6 and self._drain_deadline is None:
            if (getattr(self.port, 'remote_end_reason', None) == 1038 and self._full_sent
                    and getattr(self.port, 'failure', 7) == 7):
                self.phase = 'draining'
                self._drain_deadline = now_ms + 5000
            else:
                raise DriverError('native-session-closed')
        if self.phase == 'channel' and not self._full_sent and now_ms >= self.initialization_deadline:
            raise DriverError('initialization-timeout')
        if self.phase == 'transport' and self.port.state == 3:
            if not self.port.remote_id():
                raise DriverError('trusted-peer-missing')
            self._request_challenge(now_ms)
            self.phase, self.deadline = 'challenge', now_ms + 15000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
        if self.phase == 'ticket' and self.port.state == 5:
            self.port.with_auth(self._send_connect)
            self.phase, self.deadline = 'connection', now_ms + 15000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
        if self.parser is not None:
            self.parser.poll(self.emit)
        transport_empty = False
        pumped_bytes = 0
        for _ in range(128):  # Bound work per callback pump; do not starve deadlines.
            if pumped_bytes >= 8 * 1024**2:
                break
            if self.parser is not None:
                processed = self.parser.completed_sequence
                if self._parser_sequence - processed >= 4:
                    break  # Leave transport messages queued while the parser catches up.
            message = self.port.receive()
            if message is None:
                transport_empty = True
                break
            self.received += 1
            pumped_bytes += len(message[0])
            self.receive(*message, now_ms)
            if self.done:
                break
        if self.parser is not None and not self.done:
            self.parser.poll(self.emit)
            if self._drain_deadline is None:
                self._advance_initialization(now_ms)
                self._send_processed_tick(now_ms)
            elif transport_empty and self.parser.completed_sequence >= self._parser_sequence:
                self.drain_completed = True
                self._processed_entity_tick = None
                self.phase, self.reason = 'closed', 'source-hltv-stop'
                self.emit(dict(kind='discontinuity', reason=self.reason, **self.parser.identity))
        if self.phase == 'channel' and now_ms - self._last_feedback_ms >= 100:
            encoded = b''
            if self._full_sent and not self._recovery_pending and self._processed_entity_tick is not None:
                encoded, _ = encode_message(4, number(1, self._processed_entity_tick))
            self._send_channel_feedback(encoded, now_ms)
            if encoded:
                self._ack_tick = self._processed_entity_tick
        if (self.phase in ('challenge', 'ticket', 'connection')
            and self._last_challenge_request_ms is not None
            and now_ms - self._last_challenge_request_ms >= 500):
            self._request_challenge(now_ms)

    def _send_channel_feedback(self, encoded, now_ms):
        self.port.send(self.feedback.frame(encoded), 1)
        self._feedback_sent += 1
        self._last_feedback_ms = now_ms
        self._last_receipt_ms = now_ms

    def _request_challenge(self, now_ms):
        request = initial_challenge_request(self._challenge.number if self._challenge else 0)
        self.port.send(request, 5)
        self._challenge_contexts.add(request[5:-1])
        self._challenge_requests += 1
        self._last_challenge_request_ms = now_ms

    def _send_connect(self, auth):
        # SDK Session prefixes its own authenticated Steam64, not the peer's.
        if self._challenge.auth_protocol == 3:
            self._account_id = int.from_bytes(auth[:8], 'little') & 0xffffffff
        if not self._account_id:
            raise DriverError('local-account-id-missing')
        payload = connect_payload(host_version=self.host_version, challenge=self._challenge,
            auth_steam=auth, player_name='CS2 Headless Observer',
            encrypted_password=transform_password(bytes(self._password), self._challenge.number),
            reservation_cookie=0, low_violence=False)
        self.port.send(connect_inner_message(payload), 5)

    def receive(self, data, reliable, now_ms):
        if (self.phase in ('challenge', 'ticket', 'connection')
            and (self.phase == 'challenge' or data.startswith(b'\xff\xff\xff\xffA'))):
            if reliable or not data.startswith(b'\xff\xff\xff\xffA'):
                raise DriverError('unexpected-challenge-message')
            body = data[5:]
            if 20 <= len(body) <= 2400:
                _, auth, key_size, peer, secure = struct.unpack_from('<IIHQB', body)
                self.challenge_metadata = {'auth_protocol': auth, 'key_size': key_size,
                    'secure_flag': secure, 'server_identity_matches': (peer == self.port.remote_id()) if peer else None,
                    'server_identity_source': 'challenge_and_gns' if peer else 'gns',
                    'context_bytes': len(body) - 19,
                    'context_sha256': hashlib.sha256(body[19:]).hexdigest()}
            challenge = parse_challenge_body(body)
            peer = self.port.remote_id()
            # Fixed engine057cb0 fills a missing challenge ID from the actual
            # authenticated GNS peer for BOTH supported auth protocols. A Steam
            # challenge still waits for its real SDK ticket callback below.
            if not peer or challenge.server_steam_id not in (0, peer):
                raise DriverError('challenge-peer-mismatch')
            if challenge.context not in self._challenge_contexts:
                raise DriverError('challenge-context-mismatch')
            previous = self._challenge
            if previous and (challenge.auth_protocol != previous.auth_protocol or challenge.secure != previous.secure):
                raise DriverError('challenge-auth-changed')
            self._challenge = challenge
            if previous:
                # Reuse the same SDK lease for the same authenticated peer. Never
                # duplicate a pending ticket or reset the absolute phase timeout.
                if self.phase == 'connection':
                    if challenge.auth_protocol == 2:
                        self._send_connect(b'')
                    else:
                        self.port.with_auth(self._send_connect)
                return
            if challenge.auth_protocol == 2:
                # Follow only the protocol selected by the authenticated peer.
                # Never downgrade a Steam-auth challenge or fabricate auth bytes.
                own = self.port.local_id()
                if type(own) is not int or not 0 < own <= 0xffffffffffffffff:
                    raise DriverError('local-account-id-missing')
                self._account_id = own & 0xffffffff
                self.port.accept_server_auth2()
                self._send_connect(b'')
                self.phase, self.deadline = 'connection', now_ms + 15000
                self.stages.append({'stage': 'server-auth2-connect', 'elapsed_ms': now_ms - self.start_ms})
            else:
                self.port.request_ticket()
                self.phase, self.deadline = 'ticket', now_ms + 30000
                self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
            return
        if self.phase == 'connection':
            if reliable:
                raise DriverError('unexpected-connection-reliability')
            response = parse_connection_inner(data)
            self._password[:] = bytes(len(self._password))
            if response['addon_name_bytes']:
                self.phase, self.reason = 'blocked', 'addon-initialization-required'
                return
            # Official Connect queues CONNECTED/-1 before ServerInfo; otherwise
            # both peers wait. A fresh channel's reliable tick context is zero.
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = join_messages([encode_message(6, self.settings.userinfo()),
                                        encode_message(message_id, payload)])
            self.port.send(reliable_frame(encoded, 0), 8)
            self.stages.append({'stage': 'sent-signon', 'value': 2, 'elapsed_ms': now_ms - self.start_ms})
            self.phase, self.deadline = 'channel', now_ms + 15000
            self.stages.append({'stage': self.phase, 'elapsed_ms': now_ms - self.start_ms})
            self._challenge = None
            return
        if self.phase not in ('channel', 'draining'):
            raise DriverError('unexpected-protocol-phase')
        if not reliable and data.startswith((b'\xff\xff\xff\xffA', b'\xff\xff\xff\xffB')):
            return  # Late handshake response on this already-authenticated connection.
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
        self.feedback.observe(frame)
        if not frame.reliable and not self.order.accept(frame)['accepted']:
            return
        received_messages, _ = messages(frame.body)
        decoded, actions = [], []
        context_tick = int32(frame.reliable_tick_hint) if frame.reliable else 0
        if context_tick is None:
            context_tick = 0
        for message in received_messages:
            # network0c00b0 assigns receive metadata before the game-side
            # reliable filter. Positive Tick/PacketEntities values advance it;
            # an unreliable frame starts from zero, not the last frame clock.
            if message.message_id in (4, 55):
                candidate = int32(scalar(fields(message.body, limit=4 * 1024**2), 1 if message.message_id == 4 else 12))
                if candidate is not None and candidate > 0:
                    context_tick = candidate
            if not self.reliable_filter.accept(message.message_id, message.body):
                continue
            decoded.append(message)
            if message.message_id == 58 and self._drain_deadline is None:
                if now_ms - self._query_window_ms >= 1000:
                    self._query_window_ms, self._query_count = now_ms, 0
                self._query_count += 1
                if self._query_count > 32:
                    raise DriverError('observer-cvar-query-rate-budget')
                encoded, _ = encode_message(25, self.settings.query(message.body))
                self.port.send(reliable_frame(encoded, 0), 8)
            if message.message_id == 7:
                state = scalar(fields(message.body), 1)
                if state == 2:
                    self._reset_world_protocol(now_ms)
                    actions.extend([('reset',), ('admit', 0)])
                self.signon.receive(message.body)
                self.stages.append({'stage': 'received-signon', 'value': self.signon.state, 'elapsed_ms': now_ms - self.start_ms})
                actions.append(('message', 7, message.body, context_tick))
                if state == 7:
                    self._reset_world_protocol(now_ms, replace_client=True)
                    actions.extend([('reset',), ('admit', 0)])
                if state in (2, 7) and self._drain_deadline is None:
                    self._send_connected_ack(now_ms)
            else:
                self.decoder.consume(message.message_id, message.body)
                actions.append(('message', message.message_id, message.body, context_tick))
                if message.message_id == 40:
                    self.signon.server_info(self.decoder.server['server_count'])
                elif message.message_id in (8, 11):
                    actions.append(('admit', self.decoder.max_creation_sequence))
                elif message.message_id == 51:
                    self._reset_world_protocol(now_ms)
                    actions.append(('admit', 0))
        if self.parser is not None:
            if getattr(self.parser, 'ordered', False):
                self._parser_sequence = self.parser.submit_batch(actions)
            else:
                raise DriverError('ordered-parser-required')

        if self._drain_deadline is None:
            self._advance_initialization(now_ms)

    def _reset_world_protocol(self, now_ms, replace_client=False):
        # Preserve the actual SDK channel, transport counters and callback loop.
        self.decoder.reset_world()
        self.initialization_deadline = now_ms + 30000
        self.signon = SignonSequence()
        self._new_sent = self._prespawn_sent = self._spawn_sent = False
        self._full_snapshot_processed = self._full_sent = False
        self._recovery_pending = self._request_full_update = self._full_update_outstanding = False
        self._processed_entity_tick = self._ack_tick = None
        self._last_receipt_ms = now_ms
        self._event_subscription_pending = None
        if replace_client:
            self.reliable_filter.replace_client_owner()
        self.stages.append({'stage': 'world-reset', 'replaced_client_owner': replace_client,
                            'elapsed_ms': now_ms - self.start_ms})

    def _send_connected_ack(self, now_ms):
        message_id, payload = self.signon.acknowledgement()
        encoded, _ = join_messages([encode_message(6, self.settings.userinfo()), encode_message(message_id, payload)])
        self.port.send(reliable_frame(encoded, 0), 8)
        self.stages.append({'stage': 'sent-signon', 'value': 2, 'elapsed_ms': now_ms - self.start_ms})

    def _advance_initialization(self, now_ms):
        checkpoint = self.parser.checkpoint if self.parser else None
        if self.parser and self.parser.completed_sequence < self._parser_sequence:
            return
        if getattr(self.parser, 'ordered', False):
            subscriptions = self.parser.pop_subscriptions()
            if subscriptions is not None:
                self._event_subscription_pending = subscriptions
            if self.signon.state > 3 and self._event_subscription_pending is not None and self.decoder.server:
                words = [0] * 16
                for event_id in self._event_subscription_pending['ids']:
                    if type(event_id) is not int or not 0 <= event_id < 512:
                        raise DriverError('event-subscription-id')
                    words[event_id // 32] |= 1 << (event_id % 32)
                slot = self.decoder.server['player_slot']
                payload = number(1, slot & 0xffffffff) + b''.join(number(2, word) for word in words)
                encoded, _ = encode_message(206, payload)
                self.port.send(reliable_frame(encoded, 0), 8)
                self._event_subscription_pending = None
        if self.signon.state == 3 and not self._new_sent:
            if self.decoder.server is None:
                raise DriverError('new-before-serverinfo')
            # Empty-table NEW can request the full schema immediately. Existing
            # tables need their callbacks consumed before this transition.
            if self.parser and not checkpoint:
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
                or not checkpoint.get('classCount')):
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
        self._acknowledge_full(now_ms)

    def _acknowledge_full(self, now_ms):
        if self.signon.state == 6 and not self._full_sent and self._full_snapshot_processed:
            if not self._spawn_sent:
                raise DriverError('full-before-spawn-acknowledgement')
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._full_sent = True
            self._ever_full = True
            self.stages.append({'stage': 'sent-full', 'source': 'processed-full-snapshot', 'elapsed_ms': now_ms - self.start_ms})

    def _send_processed_tick(self, now_ms):
        checkpoint = self.parser.checkpoint if self.parser else None
        if checkpoint is None:
            return
        if not self._full_sent and not self._spawn_sent:
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
                if receipt.get('full') is True:
                    self._full_snapshot_processed = True
                self._recovery_pending = False
                self._full_update_outstanding = False
                self._processed_entity_tick = receipt['tick']
                if receipt['baselineAck'] is not None:
                    baseline_acks.append((receipt['tick'], receipt['baselineAck']))
        if self._full_snapshot_processed and not self._full_sent:
            if self.signon.state == 5:
                self.signon.finish_full_snapshot()
            self._acknowledge_full(now_ms)
        if self._recovery_pending:
            if self._request_full_update and not self._full_update_outstanding:
                encoded, _ = encode_message(4, number(1, 0xffffffff))
                self.port.send(reliable_frame(encoded, 0), 8)
                self._ack_tick = 0xffffffff
                self._full_update_outstanding = True
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
        self._send_channel_feedback(encoded, now_ms)
        self._ack_tick = self._processed_entity_tick
        self._last_receipt_ms = now_ms

    def report(self):
        span = None if self.first_channel_ms is None else self.last_channel_ms - self.first_channel_ms
        return {'phase': self.phase, 'reason': self.reason, 'received_messages': self.received,
                'host_version': self.host_version, 'native_state': self.port.state,
                'native_failure': getattr(self.port, 'failure', None),
                'remote_end_reason': getattr(self.port, 'remote_end_reason', None),
                'world_creation_watermark': self.decoder.max_creation_sequence,
                'world_creation_sequences': sorted(group['creation_sequence'] or 0 for group in self.decoder.spawn_groups.values()),
                'challenge_metadata': self.challenge_metadata, 'challenge_requests': self._challenge_requests,
                'outgoing_channel_feedback_frames': self._feedback_sent,
                'last_received_channel_sequence': self.feedback.received,
                'channel_frames': self.channel_frames, 'channel_bytes': self.channel_bytes,
                'channel_receive_span_ms': span, 'received_signon_state': self.signon.received_state,
                'effective_signon_state': self.signon.state,
                'full_snapshot_processed': self._full_snapshot_processed,
                'stages': list(self.stages), 'reachedFull': self._ever_full,
                'lastProcessedSequence': self.parser.completed_sequence if self.parser else 0,
                'lastOutputSequence': self.emit.sequence, 'drainCompleted': self.drain_completed,
                'parser_checkpoint': self.parser.checkpoint if self.parser else None,
                'parser_failure': getattr(self.parser, 'failure_details', None),
                'parserDiagnostics': list(getattr(self.parser, 'diagnostics', [])),
                'last_processed_entity_tick': self._processed_entity_tick,
                'last_acknowledged_entity_tick': self._ack_tick,
                'full_update_requests': self._recovery_requests, 'baseline_ack_count': self._baseline_ack_count,
                'net_message_counts': self.decoder.counts,
                'initialization_blockers': ([] if self._full_sent else
                    [self.reason or 'signon-in-progress']),
}

    def close(self):
        self._password[:] = bytes(len(self._password))
        self._challenge = None
        self._account_id = None
        self._challenge_contexts.clear()
        self.port.close()


def private_file(path, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, mode, **({'encoding': 'utf-8', 'newline': '\n'} if 'b' not in mode else {}))


class CaptureBudget:
    def __init__(self, maximum=256 * 1024**2):
        self.maximum, self.written, self.truncated = maximum, 0, False

    def claim(self, size):
        if self.truncated or self.written + size > self.maximum:
            self.truncated = True
            return False
        self.written += size
        return True


class SampleWriter:
    """Opt-in bounded channel capture; no endpoint, handshake or authentication bytes."""
    def __init__(self, handle, budget=None):
        self.handle, self.budget = handle, budget or CaptureBudget()
        if self.budget.claim(len(MAGIC)):
            handle.write(MAGIC)

    def __call__(self, data, reliable, elapsed_ms):
        decode_frame(data, gns_reliable=reliable)
        frame = struct.pack('<IQB', len(data), elapsed_ms, int(reliable)) + data
        if self.budget.claim(len(frame)):
            self.handle.write(frame)


def connection_values(endpoint, supplied):
    if not isinstance(endpoint, str) or not isinstance(supplied, str):
        raise ValueError('configuration-boundary')
    address, separator, port_text = endpoint.rpartition(':')
    try:
        ipaddress.ip_address(address.strip('[]'))
        if not separator or not 0 < int(port_text) < 65536:
            raise ValueError()
        password = bytearray(supplied.encode('ascii'))
        if len(password) > 95 or 0 in password:
            password[:] = bytes(len(password))
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError('configuration-boundary') from None
    return endpoint, password


def read_managed_connection(stream):
    """One bounded private stdin record; no credentials in argv, logs or saved config."""
    try:
        raw = stream.readline(4097)
        if len(raw) > 4096:
            raise ValueError()
        record = json.loads(raw)
        if not isinstance(record, dict) or set(record) != {'endpoint', 'password'}:
            raise ValueError()
        return connection_values(record['endpoint'], record['password'])
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('configuration-boundary') from None



def main():
    from host_version import host_version, discover_host
    def positive(value):
        result = int(value)
        if result < 1:
            raise ValueError('positive-integer-required')
        return result
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--native', type=Path, required=True)
    ap.add_argument('--steam-api', type=Path)
    ap.add_argument('--node', default='node')
    ap.add_argument('--parser-worker', type=Path, default=Path(__file__).with_name('parser_worker.mjs'))
    ap.add_argument('--source-role', choices=('ahead', 'delayed'), default='ahead')
    from uuid import UUID, uuid4
    ap.add_argument('--source-id', type=lambda value: UUID(value).hex)
    ap.add_argument('--managed', action='store_true')
    ap.add_argument('--host-version', type=host_version, help='Actual source host; otherwise suggest from local steam.inf')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--seconds', type=positive, help='Explicit diagnostic duration; default runs until stop/source end')
    ap.add_argument('--capture', action='store_true', help='Opt in to private raw/event capture; unavailable in managed mode')
    ap.add_argument('--capture-budget-mib', type=positive, default=256)
    args = ap.parse_args()
    if args.managed and args.capture:
        ap.error('Managed mode never captures raw traffic or event files')
    if args.host_version is None:
        try:
            args.host_version = discover_host(args.steam_api.resolve().parents[2] / 'csgo/steam.inf')
        except (ValueError, OSError, AttributeError, IndexError):
            ap.error('Supply the actual source --host-version; local version discovery unavailable')
    from node_runtime import inspect_node
    inspect_node(args.node)
    owner = ManagedOwner(stream=sys.stdin.buffer, configuration_reader=read_managed_connection) if args.managed else ManagedOwner()
    password = bytearray()
    try:
        if args.managed:
            endpoint, password = owner.configuration()
        else:
            endpoint, password = connection_values(getpass.getpass('Authorized GOTV numeric IP:port: '),
                getpass.getpass('Ordinary spectator password: '))
    except ValueError:
        owner.close()
        raise SystemExit('configuration-boundary') from None
    try:
        args.output.mkdir(mode=0o700)
    except OSError:
        password[:] = bytes(len(password))
        owner.close()
        raise SystemExit('output-directory-unavailable') from None
    driver = native = parser = samples = events = writer = None
    budget = CaptureBudget(args.capture_budget_mib * 1024**2)
    report, failure, finalization = {'schema': 'cs2-observer-report/1', 'reachedFull': False, 'drainCompleted': False, 'lastProcessedSequence': 0}, None, []
    def clock(): return time.monotonic_ns() // 1000000
    try:
        from sdk import NativePort
        from ordered_parser_bridge import OrderedParserBridge
        writer = OutputWriter(sys.stdout.fileno())
        if args.capture:
            events = private_file(args.output / 'events.jsonl', 'wb')
            samples = private_file(args.output / 'channel.frames', 'wb')
        parser = OrderedParserBridge(source=args.source_role + ':' + (args.source_id or uuid4().hex),
            channel=1, world=1, node=args.node, worker=args.parser_worker)
        if owner.is_set():
            raise KeyboardInterrupt()
        native = NativePort(args.native, endpoint, clock(), steam_api=args.steam_api)
        del endpoint
        def emit_event(event):
            writer.emit(event)
            if events:
                data = encode_record(event)
                if budget.claim(len(data)):
                    events.write(data)
        driver = ObserverDriver(native, host_version=args.host_version, password=password, emit=emit_event,
            capture=SampleWriter(samples, budget) if samples else None, now_ms=clock(), parser=parser)
        stop = clock() + args.seconds * 1000 if args.seconds else None
        while not driver.done and (stop is None or clock() < stop) and not owner.is_set():
            writer.check()
            driver.step(clock())
            time.sleep(.01)
        if not driver.done:
            driver.reason = 'owner-stopped' if owner.is_set() else 'duration-limit-incomplete'
        report.update(driver.report())
    except BaseException as error:
        if driver is not None:
            report.update(driver.report())
        if isinstance(error, KeyboardInterrupt):
            owner.stopped.set()
            report['reason'] = 'owner-stopped'
        else:
            failure = str(error) if isinstance(error, (DriverError, ProbeError)) else 'interrupted' if isinstance(error, KeyboardInterrupt) else 'operation-failed-details-omitted'
            if type(error).__name__ == 'NativeStartError':
                failure = 'native-start-failed'
                report['native_boot_code'], report['steam_init_result'] = error.boot_code, error.init_result
            report['reason'] = failure
    finally:
        password[:] = bytes(len(password))
        for stage, action in [('close-session', driver.close if driver else native.close if native else None),
                ('close-parser', parser.close if parser else None), ('close-events', events.close if events else None),
                ('close-samples', samples.close if samples else None)]:
            if action:
                try: action()
                except BaseException: finalization.append(stage)
        if writer:
            completed = writer.abort() if failure or owner.is_set() else writer.finish()
            if not completed:
                finalization.append('close-output')
        if not owner.close():
            finalization.append('close-input')
        report.update(finalization_failures=finalization, cleanupCompleted=not finalization,
            capture={'enabled': args.capture, 'bytes': budget.written, 'budget': budget.maximum, 'truncated': budget.truncated})
        report['outcome'] = 'failed' if failure or finalization else 'closed' if report.get('reason') == 'source-hltv-stop' else 'incomplete'
        if len(json.dumps(report).encode()) > 30000:
            report['stages'] = report.get('stages', [])[-32:]
            report['net_message_counts'] = dict(list(report.get('net_message_counts', {}).items())[:128])
            report['diagnosticTruncated'] = True
        report['reportWritten'] = True
        temporary = args.output / 'report.json.tmp'
        try:
            with private_file(temporary, 'w') as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
                handle.write('\n')
            temporary.replace(args.output / 'report.json')
        except BaseException:
            report['reportWritten'] = False
            finalization.append('write-report')
            report.update(outcome='failed', cleanupCompleted=False)
        # A consumer may also abandon stderr; never block process exit on the report pipe.
        try:
            terminal = OutputWriter(sys.stderr.fileno())
            terminal.emit(report)
            terminal.finish(timeout=1)
        except (OSError, ProbeError, ValueError):
            pass
    return 1 if report['outcome'] == 'failed' else 0 if report['outcome'] == 'closed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
