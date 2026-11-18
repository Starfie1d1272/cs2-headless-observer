#!/usr/bin/env python3
"""Explicit local ordinary-viewer research driver. Never invoked by import/tests.

Native SDK authentication -> actual first q -> validated challenge -> callback-gated
user ticket -> known-password connect -> channel receive -> live message consumer.
Requests full schema at NEW and initializes the event-only network world before SPAWN.
"""

import argparse
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
import getpass
import hashlib
import ipaddress
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = (
    True  # Installed component files stay immutable across launches.
)
import time
from channel import (
    decode_frame,
    messages,
    UnreliableOrder,
    UnreliableFeedback,
    encode_message,
    reliable_frame,
    ReliableMessageFilter,
    join_messages,
)
from handshake import (
    SignonSequence,
    connect_inner_message,
    connect_payload,
    initial_challenge_request,
    parse_challenge_body,
    parse_connection_inner,
    uint,
    number,
)
from control import ControlDecoder, client_info, int32
from observer_settings import ObserverSettings
from ordered_parser_bridge import Envelope, OrderedParserBridge
from password import transform_password
from wire import ProbeError, fields, scalar
from process_io import (
    CaptureWriter,
    PublicRecords,
    ManagedOwner,
    OutputWriter,
    DRAIN_TIMEOUT_MS,
    HARD_AGE_US,
    HEALTH_INTERVAL_NS,
    SOFT_AGE_US,
    private_file,
    source_age_us,
)

MAGIC = b"MZRCS2\x01\0"


class DriverError(Exception):
    pass


# Local residence protections, independent of protocol feedback and GOTV delay.
STARTUP_AGE_US = 10_000_000
WORK_NS = 2_000_000
PARSER_NO_PAYLOAD = frozenset({76})  # Fixed-profile CSVCMsg_UserCommands.
PARSER_CONTROL_BARRIERS = frozenset({7, 8, 9, 11, 12, 40, 51, 58, 205})


class Duty(Enum):
    EMPTY = auto()
    BUDGET = auto()
    AWAITING_PARSER = auto()
    STOPPED = auto()


@dataclass(frozen=True)
class StepResult:
    duty: Duty
    received: int = 0
    received_bytes: int = 0
    results: int = 0


def clock_ms():
    return time.monotonic_ns() // 1_000_000


class ObserverDriver:
    """One session/one receiver. Port is sdk.NativePort in the real invocation.

    Tests use a clearly synthetic port. No success flag can be set by either port.
    Configured source version must match the source, not merely this binary sample.
    """

    def __init__(
        self,
        port,
        *,
        host_version,
        password,
        emit,
        capture=None,
        now_ms=0,
        parser=None,
        encoded_output=False,
        supervised=False,
    ):
        uint(host_version)
        if (
            not host_version
            or not isinstance(password, bytearray)
            or len(password) > 95
            or 0 in password
        ):
            raise DriverError("configuration-boundary")
        self.port, self.host_version = port, host_version
        self.supervised = supervised
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
        self.parser, self.emit = parser, PublicRecords(emit, encoded=encoded_output)
        self._parser_sequence = 0
        self._last_sdk_age_us = self._max_sdk_age_us = None
        self._sdk_sample_ns = None
        self._receive_budget_exhausted = self._result_budget_exhausted = 0
        self._health_reason = None
        self.health = None
        self._last_cursor = None
        self._cursor_rate = None
        self._gap = False
        self._max_parser_age_us = None
        self._window_sdk_age_us = None
        self._last_health_totals = (0, 0, 0, 0, 0)
        self._last_health_ns = 0
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
        self.phase, self.reason = "transport", None
        self.start_ms, self.last_ms, self.deadline = now_ms, now_ms, now_ms + 30000
        self.received = self._received_bytes = self.channel_frames = (
            self.channel_bytes
        ) = 0
        self.first_channel_ms = self.last_channel_ms = None
        self.stages = deque([{"stage": "transport", "elapsed_ms": 0}], maxlen=512)
        self._drain_deadline = None
        self.drain_completed = False
        self.native_state = None
        self.initialization_deadline = now_ms + 30000

    @property
    def done(self):
        return self.phase in ("blocked", "closed")

    def step(self, now_ms, *, clock=None, cancelled=None):
        if self.done or (cancelled and cancelled()):
            return StepResult(Duty.STOPPED)
        if now_ms < self.last_ms:
            raise DriverError("monotonic-clock-regressed")
        self.last_ms = now_ms
        if self._drain_deadline is not None and now_ms >= self._drain_deadline:
            raise DriverError("source-drain-timeout")
        if self._drain_deadline is None and now_ms >= self.deadline:
            raise DriverError("phase-timeout")
        self.port.pump(now_ms)
        if self._drain_deadline is not None and getattr(self.port, "failure", 7) != 7:
            raise DriverError("source-drain-native-failed")
        if self.port.state != self.native_state:
            self.native_state = self.port.state
            self.stages.append(
                {
                    "stage": "sdk-state",
                    "value": self.native_state,
                    "elapsed_ms": now_ms - self.start_ms,
                }
            )
        if self.port.state == 6 and self._drain_deadline is None:
            if (
                getattr(self.port, "remote_end_reason", None) == 1038
                and self._full_sent
                and getattr(self.port, "failure", 7) == 7
            ):
                self.phase = "draining"
                self._drain_deadline = now_ms + DRAIN_TIMEOUT_MS
            else:
                raise DriverError("native-session-closed")
        if (
            self.phase == "channel"
            and not self._full_sent
            and now_ms >= self.initialization_deadline
        ):
            raise DriverError("initialization-timeout")
        if self.phase == "transport" and self.port.state == 3:
            if not self.port.remote_id():
                raise DriverError("trusted-peer-missing")
            self._request_challenge(now_ms)
            self.phase, self.deadline = "challenge", now_ms + 15000
            self.stages.append(
                {"stage": self.phase, "elapsed_ms": now_ms - self.start_ms}
            )
        if self.phase == "ticket" and self.port.state == 5:
            self.port.with_auth(self._send_connect)
            self.phase, self.deadline = "connection", now_ms + 15000
            self.stages.append(
                {"stage": self.phase, "elapsed_ms": now_ms - self.start_ms}
            )
        self._check_residence()
        results = self._poll_parser(cancelled)
        if cancelled and cancelled():
            return StepResult(Duty.STOPPED, results=results)
        now_ms = clock() if clock else now_ms
        if self.parser is not None and self._drain_deadline is None:
            self._advance_initialization(now_ms)
            self._send_processed_tick(now_ms)
        status = Duty.BUDGET
        received = pumped_bytes = 0
        work_deadline = time.monotonic_ns() + WORK_NS
        envelopes = [] if self.parser and self._full_sent else None
        staged_messages = staged_bytes = 0
        while received < 128 and pumped_bytes < 8 * 1024**2:
            if self.done or (cancelled and cancelled()):
                return StepResult(Duty.STOPPED, received, pumped_bytes, results)
            if received and time.monotonic_ns() >= work_deadline:
                break
            if self.parser is not None and not self.parser.has_credit():
                status = Duty.AWAITING_PARSER
                break
            message = self.port.receive()
            if message is None:
                status = Duty.EMPTY
                break
            received += 1
            self.received += 1
            pumped_bytes += len(message[0])
            self._received_bytes += len(message[0])
            now_ms = clock() if clock else now_ms
            if self._drain_deadline is not None and now_ms >= self._drain_deadline:
                raise DriverError("source-drain-timeout")
            if len(message) == 4:
                data, reliable, dequeued, sdk_age = message
                self._sdk_sample_ns = dequeued
                self._last_sdk_age_us = sdk_age
                if sdk_age is not None:
                    self._max_sdk_age_us = max(self._max_sdk_age_us or 0, sdk_age)
                    self._window_sdk_age_us = max(self._window_sdk_age_us or 0, sdk_age)
                if self._drain_deadline is None:
                    limit = HARD_AGE_US if self._full_sent else STARTUP_AGE_US
                    if sdk_age is not None and sdk_age >= limit:
                        raise DriverError("sdk-receive-overload")
                    if (time.monotonic_ns() - dequeued) // 1000 >= limit:
                        raise DriverError("receive-staging-overload")
                staged = self.receive(
                    data,
                    reliable,
                    now_ms,
                    dequeue_ns=dequeued,
                    sdk_age_us=sdk_age,
                    envelopes=envelopes,
                )
            else:
                staged = self.receive(*message, now_ms, envelopes=envelopes)
            if staged:
                count, size, barrier = staged
                staged_messages += count
                staged_bytes += size
                if (
                    barrier
                    or staged_messages >= self.parser.BATCH_TARGET_MESSAGES
                    or staged_bytes >= self.parser.BATCH_TARGET_BYTES
                ):
                    break
        if envelopes and not (cancelled and cancelled()):
            self._parser_sequence = self.parser.submit_envelopes(envelopes)
        if status is Duty.BUDGET:
            self._receive_budget_exhausted += 1
        if cancelled and cancelled():
            return StepResult(Duty.STOPPED, received, pumped_bytes, results)
        self._check_residence()
        if self.parser is not None and not self.done:
            results += self._poll_parser(cancelled)
            if cancelled and cancelled():
                return StepResult(Duty.STOPPED, received, pumped_bytes, results)
            now_ms = clock() if clock else now_ms
            if self._drain_deadline is None:
                self._advance_initialization(now_ms)
                self._send_processed_tick(now_ms)
            elif (
                status is Duty.EMPTY
                and self.parser.caught_up
                and not self.parser.has_results()
            ):
                self.drain_completed = True
                self._processed_entity_tick = None
                self.phase, self.reason = "closed", "source-hltv-stop"
                self._emit_parser(
                    dict(
                        kind="discontinuity", reason=self.reason, **self.parser.identity
                    )
                )
            if self.parser.has_results() or (
                status is Duty.AWAITING_PARSER and self.parser.has_credit()
            ):
                status = Duty.BUDGET
        if self.phase == "channel" and now_ms - self._last_feedback_ms >= 100:
            encoded = b""
            if (
                self._full_sent
                and not self._recovery_pending
                and self._processed_entity_tick is not None
            ):
                encoded, _ = encode_message(4, number(1, self._processed_entity_tick))
            self._send_channel_feedback(encoded, now_ms)
            if encoded:
                self._ack_tick = self._processed_entity_tick
        if (
            self.phase in ("challenge", "ticket", "connection")
            and self._last_challenge_request_ms is not None
            and now_ms - self._last_challenge_request_ms >= 500
        ):
            self._request_challenge(now_ms)

        return StepResult(
            Duty.STOPPED if self.done else status, received, pumped_bytes, results
        )

    def wait_timeout(self, now_ms, idle_ms, stop_ms):
        deadlines = [now_ms + idle_ms]
        for deadline in (stop_ms, self._drain_deadline):
            if deadline is not None:
                deadlines.append(deadline)
        if self._drain_deadline is None:
            deadlines.append(self.deadline)
            if self.phase == "channel":
                deadlines.append(self._last_feedback_ms + 100)
                if not self._full_sent:
                    deadlines.append(self.initialization_deadline)
            elif self._last_challenge_request_ms is not None:
                deadlines.append(self._last_challenge_request_ms + 500)
        return max(0, min(deadlines) - now_ms) / 1000

    def _check_residence(self):
        now_ns = time.monotonic_ns()
        oldest = self.parser.oldest_age_us(now_ns) if self.parser else None
        if oldest is not None:
            self._max_parser_age_us = max(self._max_parser_age_us or 0, oldest)
        if self._drain_deadline is not None:
            return
        limit = HARD_AGE_US if self._full_sent else STARTUP_AGE_US
        pending = getattr(self.port, "pending_receive_age_ns", None)
        if pending and (pending(now_ns) or 0) // 1000 >= limit:
            raise DriverError("receive-staging-overload")
        if oldest is not None and oldest >= limit:
            raise DriverError("parser-residence-overload")

    def _poll_parser(self, cancelled):
        if self.parser is None:
            return 0
        rows = self.parser.poll(
            self._emit_parser,
            deadline_ns=time.monotonic_ns() + WORK_NS,
            cancelled=cancelled,
        )
        if self.parser.has_results():
            self._result_budget_exhausted += 1
        return len(rows)

    def _emit_parser(self, row):
        if row["kind"] == "discontinuity":
            self._last_cursor = self._cursor_rate = None
            self._gap = True
        if "submitToObservedUs" in row:
            age = row["dequeueToSubmitUs"] + row["submitToObservedUs"]
            sdk_age = row["sdkQueueAgeUs"]
            if self._drain_deadline is None:
                if age >= HARD_AGE_US:
                    raise DriverError("parser-residence-overload")
                if sdk_age is not None and sdk_age + age >= HARD_AGE_US:
                    raise DriverError("source-residence-overload")
            row["observedAt"] = time.time_ns() // 1_000_000
        if row["kind"] == "cursor":
            now = time.monotonic_ns()
            tick = row["committedTick"]
            world = row["world"]
            paused = (row.get("roundClock") or {}).get("pause", {}).get("active")
            self._cursor_rate = None
            if self._last_cursor and not paused:
                last_world, last_tick, last_ns, last_paused, _ = self._last_cursor
                elapsed = now - last_ns
                if (
                    world == last_world
                    and tick > last_tick
                    and 0 < elapsed <= 3_000_000_000
                    and not last_paused
                ):
                    self._cursor_rate = (tick - last_tick) * 1_000_000_000 / elapsed
            self._last_cursor = world, tick, now, paused, self.emit.sequence + 1
            self._gap = False
        if self.supervised:
            row["_attemptEmittedNs"] = time.monotonic_ns()
            row["_attemptDraining"] = self._drain_deadline is not None
        self.emit(row)

    def _send_channel_feedback(self, encoded, now_ms):
        self.port.send(self.feedback.frame(encoded), 1)
        self._feedback_sent += 1
        self._last_feedback_ms = now_ms
        self._last_receipt_ms = now_ms

    def _request_challenge(self, now_ms):
        request = initial_challenge_request(
            self._challenge.number if self._challenge else 0
        )
        self.port.send(request, 5)
        self._challenge_contexts.add(request[5:-1])
        self._challenge_requests += 1
        self._last_challenge_request_ms = now_ms

    def _send_connect(self, auth):
        # SDK Session prefixes its own authenticated Steam64, not the peer's.
        if self._challenge.auth_protocol == 3:
            self._account_id = int.from_bytes(auth[:8], "little") & 0xFFFFFFFF
        if not self._account_id:
            raise DriverError("local-account-id-missing")
        payload = connect_payload(
            host_version=self.host_version,
            challenge=self._challenge,
            auth_steam=auth,
            player_name="CS2 Headless Observer",
            encrypted_password=transform_password(
                bytes(self._password), self._challenge.number
            ),
            reservation_cookie=0,
            low_violence=False,
        )
        self.port.send(connect_inner_message(payload), 5)

    def receive(
        self,
        data,
        reliable,
        now_ms,
        *,
        dequeue_ns=None,
        sdk_age_us=None,
        envelopes=None,
    ):
        if self.phase in ("challenge", "ticket", "connection") and (
            self.phase == "challenge" or data.startswith(b"\xff\xff\xff\xffA")
        ):
            if reliable or not data.startswith(b"\xff\xff\xff\xffA"):
                raise DriverError("unexpected-challenge-message")
            body = data[5:]
            if 20 <= len(body) <= 2400:
                _, auth, key_size, peer, secure = struct.unpack_from("<IIHQB", body)
                self.challenge_metadata = {
                    "auth_protocol": auth,
                    "key_size": key_size,
                    "secure_flag": secure,
                    "server_identity_matches": (peer == self.port.remote_id())
                    if peer
                    else None,
                    "server_identity_source": "challenge_and_gns" if peer else "gns",
                    "context_bytes": len(body) - 19,
                    "context_sha256": hashlib.sha256(body[19:]).hexdigest(),
                }
            challenge = parse_challenge_body(body)
            peer = self.port.remote_id()
            # Fixed engine057cb0 fills a missing challenge ID from the actual
            # authenticated GNS peer for BOTH supported auth protocols. A Steam
            # challenge still waits for its real SDK ticket callback below.
            if not peer or challenge.server_steam_id not in (0, peer):
                raise DriverError("challenge-peer-mismatch")
            if challenge.context not in self._challenge_contexts:
                raise DriverError("challenge-context-mismatch")
            previous = self._challenge
            if previous and (
                challenge.auth_protocol != previous.auth_protocol
                or challenge.secure != previous.secure
            ):
                raise DriverError("challenge-auth-changed")
            self._challenge = challenge
            if previous:
                # Reuse the same SDK lease for the same authenticated peer. Never
                # duplicate a pending ticket or reset the absolute phase timeout.
                if self.phase == "connection":
                    if challenge.auth_protocol == 2:
                        self._send_connect(b"")
                    else:
                        self.port.with_auth(self._send_connect)
                return
            if challenge.auth_protocol == 2:
                # Follow only the protocol selected by the authenticated peer.
                # Never downgrade a Steam-auth challenge or fabricate auth bytes.
                own = self.port.local_id()
                if type(own) is not int or not 0 < own <= 0xFFFFFFFFFFFFFFFF:
                    raise DriverError("local-account-id-missing")
                self._account_id = own & 0xFFFFFFFF
                self.port.accept_server_auth2()
                self._send_connect(b"")
                self.phase, self.deadline = "connection", now_ms + 15000
                self.stages.append(
                    {
                        "stage": "server-auth2-connect",
                        "elapsed_ms": now_ms - self.start_ms,
                    }
                )
            else:
                self.port.request_ticket()
                self.phase, self.deadline = "ticket", now_ms + 30000
                self.stages.append(
                    {"stage": self.phase, "elapsed_ms": now_ms - self.start_ms}
                )
            return
        if self.phase == "connection":
            if reliable:
                raise DriverError("unexpected-connection-reliability")
            response = parse_connection_inner(data)
            self._password[:] = bytes(len(self._password))
            if response["addon_name_bytes"]:
                self.phase, self.reason = "blocked", "addon-initialization-required"
                return
            # Official Connect queues CONNECTED/-1 before ServerInfo; otherwise
            # both peers wait. A fresh channel's reliable tick context is zero.
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = join_messages(
                [
                    encode_message(6, self.settings.userinfo()),
                    encode_message(message_id, payload),
                ]
            )
            self.port.send(reliable_frame(encoded, 0), 8)
            self.stages.append(
                {
                    "stage": "sent-signon",
                    "value": 2,
                    "elapsed_ms": now_ms - self.start_ms,
                }
            )
            self.phase, self.deadline = "channel", now_ms + 15000
            self.stages.append(
                {"stage": self.phase, "elapsed_ms": now_ms - self.start_ms}
            )
            self._challenge = None
            return
        if self.phase not in ("channel", "draining"):
            raise DriverError("unexpected-protocol-phase")
        if not reliable and data.startswith(
            (b"\xff\xff\xff\xffA", b"\xff\xff\xff\xffB")
        ):
            return  # Late handshake response on this already-authenticated connection.
        if dequeue_ns is None:
            dequeue_ns = time.monotonic_ns()
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
        if not frame.reliable:
            order = self.order.accept(frame)
            if not order["accepted"]:
                return
            if order["gap"]:
                self._last_cursor = self._cursor_rate = None
                self._gap = True
        received_messages, _ = messages(frame.body, discard_bodies=PARSER_NO_PAYLOAD)
        actions = []
        context_tick = int32(frame.reliable_tick_hint) if frame.reliable else 0
        if context_tick is None:
            context_tick = 0
        for message in received_messages:
            # network0c00b0 assigns receive metadata before the game-side
            # reliable filter. Positive Tick/PacketEntities values advance it;
            # an unreliable frame starts from zero, not the last frame clock.
            values = None
            if message.message_id in (4, 55):
                values = fields(message.body, limit=4 * 1024**2)
                candidate = int32(
                    scalar(
                        values,
                        1 if message.message_id == 4 else 12,
                    )
                )
                if candidate is not None and candidate > 0:
                    context_tick = candidate
            if not self.reliable_filter.accept(message.message_id, message.body):
                continue
            if message.message_id == 58 and self._drain_deadline is None:
                if now_ms - self._query_window_ms >= 1000:
                    self._query_window_ms, self._query_count = now_ms, 0
                self._query_count += 1
                if self._query_count > 32:
                    raise DriverError("observer-cvar-query-rate-budget")
                encoded, _ = encode_message(25, self.settings.query(message.body))
                self.port.send(reliable_frame(encoded, 0), 8)
            if message.message_id == 7:
                state = scalar(fields(message.body), 1)
                if state == 2:
                    self._reset_world_protocol(now_ms)
                    actions.extend([("reset",), ("admit", 0)])
                self.signon.receive(message.body)
                self.stages.append(
                    {
                        "stage": "received-signon",
                        "value": self.signon.state,
                        "elapsed_ms": now_ms - self.start_ms,
                    }
                )
                actions.append(("message", 7, message.body, context_tick))
                if state == 7:
                    self._reset_world_protocol(now_ms, replace_client=True)
                    actions.extend([("reset",), ("admit", 0)])
                if state in (2, 7) and self._drain_deadline is None:
                    self._send_connected_ack(now_ms)
            else:
                self.decoder.consume(message.message_id, message.body, values=values)
                if message.message_id not in PARSER_NO_PAYLOAD:
                    actions.append(
                        ("message", message.message_id, message.body, context_tick)
                    )
                if message.message_id == 40:
                    self.signon.server_info(self.decoder.server["server_count"])
                elif message.message_id in (8, 11):
                    actions.append(("admit", self.decoder.max_creation_sequence))
                elif message.message_id == 51:
                    self._reset_world_protocol(now_ms)
                    actions.append(("admit", 0))
        if self.parser is not None and actions:
            if not self.parser.ordered:
                raise DriverError("ordered-parser-required")
            envelope = Envelope(actions, dequeue_ns, sdk_age_us)
            if envelopes is not None:
                envelopes.append(envelope)
                count = size = 0
                barrier = False
                for action in actions:
                    if action[0] == "message":
                        count += 1
                        size += len(action[2])
                        barrier |= action[1] in PARSER_CONTROL_BARRIERS
                return count, size, barrier
            self._parser_sequence = self.parser.submit_envelopes([envelope])

        if envelopes is None and self._drain_deadline is None:
            self._advance_initialization(now_ms)

    def _reset_world_protocol(self, now_ms, replace_client=False):
        # Preserve the actual SDK channel, transport counters and callback loop.
        self.decoder.reset_world()
        self._last_cursor = self._cursor_rate = None
        self._gap = True
        self.initialization_deadline = now_ms + 30000
        self.signon = SignonSequence()
        self._new_sent = self._prespawn_sent = self._spawn_sent = False
        self._full_snapshot_processed = self._full_sent = False
        self._recovery_pending = self._request_full_update = (
            self._full_update_outstanding
        ) = False
        self._processed_entity_tick = self._ack_tick = None
        self._last_receipt_ms = now_ms
        self._event_subscription_pending = None
        if replace_client:
            self.reliable_filter.replace_client_owner()
        self.stages.append(
            {
                "stage": "world-reset",
                "replaced_client_owner": replace_client,
                "elapsed_ms": now_ms - self.start_ms,
            }
        )

    def _send_connected_ack(self, now_ms):
        message_id, payload = self.signon.acknowledgement()
        encoded, _ = join_messages(
            [
                encode_message(6, self.settings.userinfo()),
                encode_message(message_id, payload),
            ]
        )
        self.port.send(reliable_frame(encoded, 0), 8)
        self.stages.append(
            {"stage": "sent-signon", "value": 2, "elapsed_ms": now_ms - self.start_ms}
        )

    def _advance_initialization(self, now_ms):
        checkpoint = self.parser.checkpoint if self.parser else None
        if (
            self.parser
            and not self._full_sent
            and (
                self.parser.completed_sequence < self._parser_sequence
                or not getattr(self.parser, "caught_up", True)
            )
        ):
            return
        if getattr(self.parser, "ordered", False):
            subscriptions = self.parser.pop_subscriptions()
            if subscriptions is not None:
                self._event_subscription_pending = subscriptions
            if (
                self.signon.state > 3
                and self._event_subscription_pending is not None
                and self.decoder.server
            ):
                words = [0] * 16
                for event_id in self._event_subscription_pending["ids"]:
                    if type(event_id) is not int or not 0 <= event_id < 512:
                        raise DriverError("event-subscription-id")
                    words[event_id // 32] |= 1 << (event_id % 32)
                slot = self.decoder.server["player_slot"]
                payload = number(1, slot & 0xFFFFFFFF) + b"".join(
                    number(2, word) for word in words
                )
                encoded, _ = encode_message(206, payload)
                self.port.send(reliable_frame(encoded, 0), 8)
                self._event_subscription_pending = None
        if self.signon.state == 3 and not self._new_sent:
            if self.decoder.server is None:
                raise DriverError("new-before-serverinfo")
            # Empty-table NEW can request the full schema immediately. Existing
            # tables need their callbacks consumed before this transition.
            if self.parser and not checkpoint:
                self.phase, self.reason = (
                    "blocked",
                    "new-string-table-callbacks-required",
                )
                return
            info = client_info(
                server_count=self.signon.spawn_count,
                account_id=self._account_id,
                send_table_crc=0,
            )
            encoded, _ = encode_message(20, info)
            self.port.send(reliable_frame(encoded, 0), 8)
            self.signon.finish_new()
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._new_sent = True
            self.stages.append(
                {
                    "stage": "sent-client-info-and-new",
                    "elapsed_ms": now_ms - self.start_ms,
                }
            )
        elif self.signon.state == 4 and not self._prespawn_sent:
            if (
                not checkpoint
                or not checkpoint["serverInfo"]
                or checkpoint["schemaFields"] == 0
                or not checkpoint.get("classCount")
            ):
                self.phase, self.reason = "blocked", "prespawn-initialization-required"
                return
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._prespawn_sent = True
            self.stages.append(
                {"stage": "sent-prespawn", "elapsed_ms": now_ms - self.start_ms}
            )
        if (
            self.signon.state in (4, 5, 6)
            and checkpoint
            and checkpoint["schemaFields"] > 0
        ):
            for handle in self.decoder.ready_world_groups():
                encoded, _ = encode_message(13, number(1, handle))
                self.port.send(reliable_frame(encoded, 0), 8)
                self.stages.append(
                    {"stage": "sent-world-ready", "elapsed_ms": now_ms - self.start_ms}
                )
        if self.signon.state == 5 and not self._spawn_sent:
            if (
                not checkpoint
                or not checkpoint["schemaFields"]
                or not self._prespawn_sent
            ):
                raise DriverError("spawn-before-parser-initialization")
            if set(self.decoder.spawn_groups) != self.decoder.ready_spawn_groups:
                return
            self.signon.finish_spawn()
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._spawn_sent = True
            self.stages.append(
                {"stage": "sent-spawn", "elapsed_ms": now_ms - self.start_ms}
            )
        self._acknowledge_full(now_ms)

    def _acknowledge_full(self, now_ms):
        if (
            self.signon.state == 6
            and not self._full_sent
            and self._full_snapshot_processed
        ):
            if not self._spawn_sent:
                raise DriverError("full-before-spawn-acknowledgement")
            message_id, payload = self.signon.acknowledgement()
            encoded, _ = encode_message(message_id, payload)
            self.port.send(reliable_frame(encoded, 0), 8)
            self._full_sent = True
            self._ever_full = True
            self.stages.append(
                {
                    "stage": "sent-full",
                    "source": "processed-full-snapshot",
                    "elapsed_ms": now_ms - self.start_ms,
                }
            )

    def _send_processed_tick(self, now_ms):
        checkpoint = self.parser.checkpoint if self.parser else None
        if checkpoint is None:
            return
        if not self._full_sent and not self._spawn_sent:
            return
        baseline_acks = []
        for receipt in self.parser.pop_receipts():
            if receipt["sequence"] > checkpoint["sequence"]:
                raise DriverError("receipt-before-parser-checkpoint")
            if receipt["type"] == "recovery":
                self._recovery_pending = True
                self._request_full_update = receipt.get("request", True)
                self._processed_entity_tick = None
                baseline_acks.clear()
            else:
                if receipt.get("full") is True:
                    self._full_snapshot_processed = True
                self._recovery_pending = False
                self._full_update_outstanding = False
                self._processed_entity_tick = receipt["tick"]
                if receipt["baselineAck"] is not None:
                    baseline_acks.append((receipt["tick"], receipt["baselineAck"]))
        if self._full_snapshot_processed and not self._full_sent:
            if self.signon.state == 5:
                self.signon.finish_full_snapshot()
            self._acknowledge_full(now_ms)
        if self._recovery_pending:
            if self._request_full_update and not self._full_update_outstanding:
                encoded, _ = encode_message(4, number(1, 0xFFFFFFFF))
                self.port.send(reliable_frame(encoded, 0), 8)
                self._ack_tick = 0xFFFFFFFF
                self._full_update_outstanding = True
                self._recovery_requests += 1
            return
        for tick, bank in baseline_acks:
            encoded, _ = encode_message(23, number(1, tick) + number(2, bank))
            self.port.send(reliable_frame(encoded, 0), 8)
            self._baseline_ack_count += 1
        if (
            not self._full_sent
            or self._processed_entity_tick is None
            or self._ack_tick == self._processed_entity_tick
            or now_ms - self._last_receipt_ms < 100
        ):
            return
        # Only acknowledge entity packets consumed by the actual parser. Never
        # echo a raw network tick while the entity parser is still behind.
        encoded, _ = encode_message(4, number(1, self._processed_entity_tick))
        self._send_channel_feedback(encoded, now_ms)
        self._ack_tick = self._processed_entity_tick
        self._last_receipt_ms = now_ms

    def update_health(self, writer, *, force=False):
        now = time.monotonic_ns()
        elapsed = now - self._last_health_ns
        if not force and elapsed < HEALTH_INTERVAL_NS:
            return None
        parser = self.parser
        output = writer.status()
        backlog = parser.backlog(now)
        checkpoint = parser.checkpoint or {}
        delivered = output["lastDeliveredCursor"]
        if delivered and delivered["world"] != parser.identity["world"]:
            delivered = None
        output["lastDeliveredCursor"] = delivered
        sdk_recent = (
            self._sdk_sample_ns is not None
            and now - self._sdk_sample_ns < HEALTH_INTERVAL_NS
        )
        receive_backlog = getattr(self.port, "receive_backlog", None)
        staging = receive_backlog(now) if receive_backlog else {"oldestAgeUs": None}
        ages = (
            self._window_sdk_age_us,
            staging["oldestAgeUs"],
            backlog["oldestAgeUs"],
            output["oldestAgeUs"],
        )
        state, reason = "unknown", "awaiting-continuous-cursor"
        if self._health_reason:
            state, reason = "overloaded", self._health_reason
        elif self.done or self.reason or self._gap or self._recovery_pending:
            state, reason = "discontinuity", self.reason or "world-or-snapshot-gap"
        elif self._drain_deadline is not None:
            reason = "source-draining"
        elif not self._full_sent:
            reason = "initializing"
        elif (
            any(age is not None and age >= SOFT_AGE_US for age in ages)
            or not parser.has_credit()
        ):
            state, reason = "catching-up", "local-backlog"
        elif not sdk_recent or self._last_sdk_age_us is None:
            reason = "sdk-receive-age-unavailable"
        elif (
            delivered
            and self._last_cursor
            and delivered["sequence"] == self._last_cursor[4]
            and self._cursor_rate is not None
            and now - self._last_cursor[2] <= 2_500_000_000
        ):
            state, reason = "live", "local-ordered-progress"
        totals = (
            self.received,
            self._received_bytes,
            parser.processed_messages,
            parser.processed_bytes,
            parser.decode_us,
        )
        window = dict(
            zip(
                (
                    "receivedMessages",
                    "receivedBytes",
                    "processedMessages",
                    "processedBytes",
                    "workerDecodeUs",
                ),
                (new - old for new, old in zip(totals, self._last_health_totals)),
            )
        )
        window["durationUs"] = elapsed // 1000 if self._last_health_ns else None
        self.health = dict(
            type="cs2-observer-health/1",
            **parser.identity,
            state=state,
            reason=reason,
            upstreamFreshness="unknown",
            window=window,
            sdkQueueAgeUs=self._last_sdk_age_us if sdk_recent else None,
            sdkWindowMaxAgeUs=self._window_sdk_age_us,
            sdkMaxAgeUs=self._max_sdk_age_us,
            receiveStaging=staging,
            parser={**backlog, "maxAgeUs": self._max_parser_age_us},
            output=output,
            receiveBudgetExhausted=self._receive_budget_exhausted,
            resultBudgetExhausted=self._result_budget_exhausted,
            contextTick=checkpoint.get("tick"),
            networkTick=checkpoint.get("networkTick"),
            committedTick=checkpoint.get("committedTick"),
            committedTicksPerSecond=self._cursor_rate if state == "live" else None,
        )
        if not force:
            self._last_health_totals = totals
            self._last_health_ns = now
            self._window_sdk_age_us = None
        return self.health

    def report(self):
        span = (
            None
            if self.first_channel_ms is None
            else self.last_channel_ms - self.first_channel_ms
        )
        return {
            "phase": self.phase,
            "reason": self.reason,
            "received_messages": self.received,
            "host_version": self.host_version,
            "native_state": self.port.state,
            "native_failure": getattr(self.port, "failure", None),
            "remote_end_reason": getattr(self.port, "remote_end_reason", None),
            "world_creation_watermark": self.decoder.max_creation_sequence,
            "world_creation_sequences": sorted(
                group["creation_sequence"] or 0
                for group in self.decoder.spawn_groups.values()
            ),
            "challenge_metadata": self.challenge_metadata,
            "challenge_requests": self._challenge_requests,
            "outgoing_channel_feedback_frames": self._feedback_sent,
            "last_received_channel_sequence": self.feedback.received,
            "channel_frames": self.channel_frames,
            "channel_bytes": self.channel_bytes,
            "channel_receive_span_ms": span,
            "received_signon_state": self.signon.received_state,
            "effective_signon_state": self.signon.state,
            "full_snapshot_processed": self._full_snapshot_processed,
            "stages": list(self.stages),
            "reachedFull": self._ever_full,
            "lastProcessedSequence": self.parser.completed_sequence
            if self.parser
            else 0,
            "lastOutputSequence": self.emit.sequence,
            "drainCompleted": self.drain_completed,
            "health": self.health,
            "parser_checkpoint": self.parser.checkpoint if self.parser else None,
            "parser_failure": getattr(self.parser, "failure_details", None),
            "parserDiagnostics": list(getattr(self.parser, "diagnostics", [])),
            "last_processed_entity_tick": self._processed_entity_tick,
            "last_acknowledged_entity_tick": self._ack_tick,
            "full_update_requests": self._recovery_requests,
            "baseline_ack_count": self._baseline_ack_count,
            "net_message_counts": self.decoder.counts,
            "initialization_blockers": (
                [] if self._full_sent else [self.reason or "signon-in-progress"]
            ),
        }

    def close(self):
        self._password[:] = bytes(len(self._password))
        self._challenge = None
        self._account_id = None
        self._challenge_contexts.clear()
        self.port.close()


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
        frame = struct.pack("<IQB", len(data), elapsed_ms, int(reliable)) + data
        if self.budget.claim(len(frame)):
            self.handle.write(frame)


def connection_values(endpoint, supplied):
    if not isinstance(endpoint, str) or not isinstance(supplied, str):
        raise ValueError("configuration-boundary")
    address, separator, port_text = endpoint.rpartition(":")
    try:
        ipaddress.ip_address(address.strip("[]"))
        if not separator or not 0 < int(port_text) < 65536:
            raise ValueError()
        password = bytearray(supplied.encode("ascii"))
        if len(password) > 95 or 0 in password:
            password[:] = bytes(len(password))
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError("configuration-boundary") from None
    return endpoint, password


def read_managed_connection(stream):
    """One bounded private stdin record; no credentials in argv, logs or saved config."""
    try:
        raw = stream.readline(4097)
        if len(raw) > 4096:
            raise ValueError()
        record = json.loads(raw)
        if not isinstance(record, dict) or set(record) != {"endpoint", "password"}:
            raise ValueError()
        return connection_values(record["endpoint"], record["password"])
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("configuration-boundary") from None


def main():
    from host_version import host_version, discover_host

    def positive(value):
        result = int(value)
        if result < 1:
            raise ValueError("positive-integer-required")
        return result

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native", type=Path, required=True)
    ap.add_argument("--steam-api", type=Path)
    ap.add_argument("--node", default="node")
    ap.add_argument(
        "--parser-worker",
        type=Path,
        default=Path(__file__).with_name("parser_worker.mjs"),
    )
    ap.add_argument("--source-role", choices=("ahead", "delayed"), default="ahead")
    from uuid import UUID, uuid4

    ap.add_argument("--source-id", type=lambda value: UUID(value).hex)
    ap.add_argument("--managed", action="store_true")
    ap.add_argument("--managed-protocol", choices=("1", "2"), default="1")
    ap.add_argument("--session-attempt", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--host-version",
        type=host_version,
        help="Actual source host; otherwise suggest from local steam.inf",
    )
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--seconds",
        type=positive,
        help="Explicit diagnostic duration; default runs until stop/source end",
    )
    ap.add_argument(
        "--capture",
        action="store_true",
        help="Opt in to private raw/event capture; unavailable in managed mode",
    )
    ap.add_argument("--capture-budget-mib", type=positive, default=256)
    args = ap.parse_args()
    if not args.managed and (args.managed_protocol == "2" or args.session_attempt):
        ap.error("Managed protocol selection requires --managed")
    if args.session_attempt and args.managed_protocol != "1":
        ap.error("Invalid internal session attempt")
    if args.managed and args.capture:
        ap.error("Managed mode never captures raw traffic or event files")
    if args.host_version is None:
        try:
            args.host_version = discover_host(
                args.steam_api.resolve().parents[2] / "csgo/steam.inf"
            )
        except (ValueError, OSError, AttributeError, IndexError):
            ap.error(
                "Supply the actual source --host-version; local version discovery unavailable"
            )
    from node_runtime import inspect_node

    inspect_node(args.node)
    owner = (
        ManagedOwner(
            stream=sys.stdin.buffer, configuration_reader=read_managed_connection
        )
        if args.managed
        else ManagedOwner()
    )
    password = bytearray()
    try:
        if args.managed:
            endpoint, password = owner.configuration()
        else:
            endpoint, password = connection_values(
                getpass.getpass("Authorized GOTV numeric IP:port: "),
                getpass.getpass("Ordinary spectator password: "),
            )
    except ValueError:
        owner.close()
        raise SystemExit("configuration-boundary") from None
    try:
        args.output.mkdir(mode=0o700)
    except OSError:
        password[:] = bytes(len(password))
        owner.close()
        raise SystemExit("output-directory-unavailable") from None
    try:
        if args.managed_protocol == "2":
            from session_supervisor import run

            args.source_id = args.source_id or uuid4().hex
            return run(args, owner, endpoint, password)
        return run_attempt(args, owner, endpoint, password)
    finally:
        password[:] = bytes(len(password))
        owner.close()


def run_attempt(args, owner, endpoint, password):
    from uuid import uuid4

    driver = native = parser = samples = events = writer = diagnostics = capture = None
    budget = CaptureBudget(args.capture_budget_mib * 1024**2)
    report, failure, finalization = (
        {
            "schema": "cs2-observer-report/1",
            "reachedFull": False,
            "drainCompleted": False,
            "lastProcessedSequence": 0,
        },
        None,
        [],
    )

    try:
        from sdk import NativePort

        writer = OutputWriter(sys.stdout.fileno(), age_limit_us=HARD_AGE_US)
        diagnostics = OutputWriter(sys.stderr.fileno(), max_records=1, max_bytes=65536)
        if args.capture:
            events = private_file(args.output / "events.jsonl", "wb")
            samples = private_file(args.output / "channel.frames", "wb")
            capture = CaptureWriter(budget)
            capture.emit(samples, MAGIC)
        parser = OrderedParserBridge(
            source=args.source_role + ":" + (args.source_id or uuid4().hex),
            channel=1,
            world=1,
            node=args.node,
            worker=args.parser_worker,
        )
        if owner.is_set():
            raise KeyboardInterrupt()
        native = NativePort(args.native, endpoint, clock_ms(), steam_api=args.steam_api)
        del endpoint

        def emit_event(event, data):
            cursor = (
                {key: event[key] for key in ("world", "committedTick", "sequence")}
                if event["kind"] == "cursor"
                else None
            )
            if driver._drain_deadline is not None:
                writer.age_limit_us = DRAIN_TIMEOUT_MS * 1000
            age = source_age_us(event) if driver._drain_deadline is None else None
            writer.emit_encoded(
                data, cursor=cursor, source_age_us=age, sequence=event["sequence"]
            )
            if capture:
                capture.emit(events, data)

        def capture_sample(data, reliable, elapsed_ms):
            if not budget.truncated:
                capture.emit(
                    samples,
                    struct.pack("<IQB", len(data), elapsed_ms, int(reliable)) + data,
                )

        driver = ObserverDriver(
            native,
            host_version=args.host_version,
            password=password,
            emit=emit_event,
            encoded_output=True,
            supervised=args.session_attempt,
            capture=capture_sample if capture else None,
            now_ms=clock_ms(),
            parser=parser,
        )
        stop = clock_ms() + args.seconds * 1000 if args.seconds else None
        idle_ms = 1
        while (
            not driver.done
            and (stop is None or clock_ms() < stop)
            and not owner.is_set()
        ):
            writer.check()
            result = driver.step(clock_ms(), clock=clock_ms, cancelled=owner.is_set)
            health = driver.update_health(writer)
            if health is not None:
                try:
                    diagnostics.emit(health)
                except ProbeError:
                    pass  # A stalled diagnostics reader never gates game records.
            if result.received or result.results:
                idle_ms = 1
            if result.duty is Duty.BUDGET:
                continue
            if result.duty is Duty.STOPPED:
                break
            parser.wait_for_progress(driver.wait_timeout(clock_ms(), idle_ms, stop))
            idle_ms = min(8, idle_ms * 2)
        if not driver.done:
            driver.reason = (
                "owner-stopped" if owner.is_set() else "duration-limit-incomplete"
            )
        driver.update_health(writer, force=True)
        report.update(driver.report())
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            owner.stopped.set()
            report["reason"] = "owner-stopped"
        else:
            failure = (
                str(error)
                if isinstance(error, (DriverError, ProbeError))
                else "operation-failed-details-omitted"
            )
            if type(error).__name__ == "NativeStartError":
                failure = "native-start-failed"
                report["native_boot_code"], report["steam_init_result"] = (
                    error.boot_code,
                    error.init_result,
                )
            report["reason"] = failure
        if driver is not None:
            driver.reason = report["reason"]
            if failure and (
                failure.endswith("-overload")
                or failure
                in (
                    "output-backpressure",
                    "output-closed",
                    "ordered-parser-input-backpressure",
                )
            ):
                driver._health_reason = failure
            driver.update_health(writer, force=True)
            report.update(driver.report())
    finally:
        password[:] = bytes(len(password))
        # Retire public delivery before joining parser pipes on owner cancellation.
        # Normal source completion still flushes the accepted final records below.
        output_closed = (
            writer.abort() if writer and (failure or owner.is_set()) else None
        )
        for stage, action in [
            (
                "close-session",
                driver.close if driver else native.close if native else None,
            ),
            ("close-parser", parser.close if parser else None),
            ("close-capture", capture.finish if capture else None),
        ]:
            if action:
                try:
                    action()
                except BaseException:
                    finalization.append(stage)
        if not capture or not capture.thread.is_alive():
            for handle in (events, samples):
                if handle:
                    try:
                        handle.close()
                    except OSError:
                        budget.truncated = True
                        finalization.append("close-capture-file")
        if writer:
            completed = output_closed if output_closed is not None else writer.finish()
            if not completed:
                finalization.append("close-output")
                if driver and not failure and not owner.is_set():
                    failure = writer.failure or "output-drain-timeout"
                    driver.reason = driver._health_reason = failure
            if driver:
                driver.update_health(writer, force=True)
                report["health"] = driver.health
                report["reason"] = driver.reason
        if not owner.close():
            finalization.append("close-input")
        report.update(
            finalization_failures=finalization,
            cleanupCompleted=not finalization,
            capture={
                "enabled": args.capture,
                "bytes": budget.written,
                "budget": budget.maximum,
                "truncated": budget.truncated,
            },
        )
        report["outcome"] = (
            "failed"
            if failure or finalization
            else "closed"
            if report.get("reason") == "source-hltv-stop"
            else "incomplete"
        )
        if len(json.dumps(report).encode()) > 30000:
            report["stages"] = report.get("stages", [])[-32:]
            report["net_message_counts"] = dict(
                list(report.get("net_message_counts", {}).items())[:128]
            )
            report["diagnosticTruncated"] = True
        report["reportWritten"] = True
        temporary = args.output / "report.json.tmp"
        try:
            with private_file(temporary, "w") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            temporary.replace(args.output / "report.json")
        except BaseException:
            report["reportWritten"] = False
            finalization.append("write-report")
            report.update(outcome="failed", cleanupCompleted=False)
        # A consumer may also abandon stderr; never block process exit on the report pipe.
        try:
            terminal = diagnostics or OutputWriter(sys.stderr.fileno())
            try:
                terminal.emit(report)
                terminal.finish(timeout=1)
            except ProbeError:
                # The persisted report is authoritative when diagnostics cannot drain.
                terminal.abort()
        except (OSError, ProbeError, ValueError):
            pass
    return (
        1
        if report["outcome"] == "failed"
        else 0
        if report["outcome"] == "closed"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
