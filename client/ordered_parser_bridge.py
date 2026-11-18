"""Generation-fenced ordered parser pipe. No Steam/network authority lives here."""

from collections import deque
from dataclasses import dataclass
import base64
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from process_io import cancel_io
from wire import ProbeError


@dataclass(frozen=True)
class Envelope:
    actions: list
    dequeued_ns: int
    sdk_age_us: int | None


@dataclass(frozen=True)
class InputBatch:
    number: int
    first: int
    last: int
    raw_bytes: int
    submitted_ns: int
    world: int
    envelopes: list  # (last parser sequence, dequeue time, SDK age)


class OrderedParserBridge:
    ordered = True
    MAX_QUEUED_BYTES = 32 * 1024**2
    # Reserve a whole legal channel envelope above either high watermark.
    BATCH_TARGET_MESSAGES, BATCH_TARGET_BYTES = 64, 256 * 1024
    HIGH_BATCHES, LOW_BATCHES = 16, 8
    HIGH_MESSAGES, LOW_MESSAGES = 8192, 4096
    HIGH_BYTES, LOW_BYTES = 4 * 1024**2, 2 * 1024**2
    MAX_BODY = 4 * 1024**2
    FORWARDED_EVENTS = frozenset(
        {
            "player_death",
            "player_hurt",
            "weapon_fire",
            "grenade_thrown",
            "bomb_beginplant",
            "bomb_abortplant",
            "bomb_planted",
            "bomb_begindefuse",
            "bomb_abortdefuse",
            "bomb_defused",
            "bomb_exploded",
            "bomb_dropped",
            "bomb_pickup",
            "round_start",
            "round_end",
            "round_prestart",
            "round_poststart",
            "round_freeze_end",
            "round_officially_ended",
            "round_announce_warmup",
            "begin_new_match",
            "round_announce_match_start",
            "cs_win_panel_round",
            "cs_win_panel_match",
        }
    )

    def __init__(self, *, source, channel, world, worker, node="node"):
        if (
            not isinstance(source, str)
            or not source
            or len(source) > 128
            or any(type(x) is not int or x < 0 for x in (channel, world))
        ):
            raise ProbeError("ordered-parser-identity")
        self.identity = dict(source=source, channel=channel, world=world)
        self.sequence = 0
        self.diagnostics = deque(maxlen=32)
        self.completed_sequence = 0
        self.checkpoint = None
        self._pending_controls = deque()
        self._receipts = deque()
        self._subscriptions = None
        self._inflight = deque()
        self._batch = 0
        self._pending_messages = self._pending_bytes = 0
        self.peak_messages = self.peak_bytes = self.peak_batches = 0
        self._throttled = False
        self.processed_messages = self.processed_bytes = self.decode_us = 0
        self._ready = deque()
        self._closed = False
        self._failure = None
        self._queued_bytes = 0
        self._lock = threading.Lock()
        self._input = queue.Queue(maxsize=32)
        self._output = queue.Queue(maxsize=64)
        self._available = threading.Event()
        from process_job import ParserJob

        self._job = ParserJob()
        try:
            self.process = subprocess.Popen(
                [node, str(Path(worker))],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._job.assign(self.process)
            self.process.stdout = io.BufferedReader(self.process.stdout)
        except BaseException:
            if hasattr(self, "process") and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=3)
            self._job.close()
            raise
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer.start()
        self._reader.start()
        try:
            self._enqueue(dict(type="init", **self.identity))
            self.admit_creation_sequence(0)
        except Exception:
            self.close()
            raise

    def _enqueue(self, row):
        self.check()
        data = (
            json.dumps(row, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode()
        if len(data) > 8 * 1024**2:
            raise ProbeError("ordered-parser-record-budget")
        with self._lock:
            if self._queued_bytes + len(data) > self.MAX_QUEUED_BYTES:
                raise ProbeError("ordered-parser-input-backpressure")
            submitted_ns = time.monotonic_ns()
            try:
                self._input.put_nowait(data)
            except queue.Full:
                raise ProbeError("ordered-parser-input-backpressure") from None
            self._queued_bytes += len(data)
            return submitted_ns

    def _write(self):
        try:
            while not self._closed:
                data = self._input.get()
                if data is None:
                    return
                view = memoryview(data)
                while view and not self._closed:
                    count = self.process.stdin.write(view)
                    if not count:
                        raise OSError("parser-pipe-closed")
                    view = view[count:]
                with self._lock:
                    self._queued_bytes -= len(data)
        except Exception as error:
            if not self._closed:
                self._failure = "ordered-parser-input-failed: " + type(error).__name__
                self._available.set()

    def _read(self):
        try:
            while not self._closed:
                line = self.process.stdout.readline(65537)
                if not line:
                    if not self._closed:
                        self._failure = "ordered-parser-exited"
                        self._available.set()
                    return
                if len(line) > 65536 or not line.endswith(b"\n"):
                    raise ValueError("record-size")
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record-shape")
                if row.get("type") == "error":
                    self._failure = (
                        "ordered-parser-error: "
                        + str(row.get("message", "unknown"))[:1024]
                    )
                    self._available.set()
                    return
                rows = row.get("rows")
                if (
                    row.get("type") != "results"
                    or not isinstance(rows, list)
                    or not rows
                ):
                    raise ValueError("result-batch-shape")
                if any(
                    not isinstance(item, dict)
                    or item.get("type")
                    not in {
                        "initialized",
                        "world-reset",
                        "creation-sequence-admitted",
                        "checkpoint",
                        "receipt",
                        "cursor",
                        "raw-event",
                        "gap",
                        "recovery",
                        "blocked",
                        "event-subscriptions",
                        "diagnostic",
                        "batch-complete",
                    }
                    for item in rows
                ):
                    raise ValueError("record-type")
                observed_ns = time.monotonic_ns()
                while not self._closed:
                    try:
                        self._output.put((rows, len(line), observed_ns), timeout=0.02)
                        self._available.set()
                        break
                    except queue.Full:
                        continue
        except Exception as error:
            if not self._closed:
                self._failure = "ordered-parser-output-failed: " + type(error).__name__
                self._available.set()

    def submit_message(self, message_id, body):
        return self.submit_batch([("message", message_id, body)])

    @property
    def caught_up(self):
        return not self._inflight

    def has_credit(self):
        if self._throttled:
            self._throttled = (
                len(self._inflight) > self.LOW_BATCHES
                or self._pending_messages > self.LOW_MESSAGES
                or self._pending_bytes > self.LOW_BYTES
            )
        else:
            self._throttled = (
                len(self._inflight) >= self.HIGH_BATCHES
                or self._pending_messages >= self.HIGH_MESSAGES
                or self._pending_bytes >= self.HIGH_BYTES
            )
        return not self._throttled

    def oldest_age_us(self, now_ns):
        if self._inflight:
            return (now_ns - self._inflight[0].envelopes[0][1]) // 1000
        return None

    def backlog(self, now_ns):
        return dict(
            pendingBatches=len(self._inflight),
            pendingMessages=self._pending_messages,
            pendingBytes=self._pending_bytes,
            peakBatches=self.peak_batches,
            peakMessages=self.peak_messages,
            peakBytes=self.peak_bytes,
            oldestAgeUs=self.oldest_age_us(now_ns),
        )

    def submit_batch(self, actions):
        return self.submit_envelopes([Envelope(actions, time.monotonic_ns(), None)])

    def submit_envelopes(self, envelopes):
        if not self.has_credit():
            raise ProbeError("ordered-parser-input-backpressure")
        identity = self.identity.copy()
        sequence = self.sequence
        rows = []
        raw_bytes = 0
        sources = []
        for envelope in envelopes:
            prior = sequence
            for action in envelope.actions:
                if action[0] == "message":
                    _, message_id, body, *context = action
                    if (
                        type(message_id) is not int
                        or message_id < 0
                        or not isinstance(body, bytes)
                        or len(body) > self.MAX_BODY
                    ):
                        raise ProbeError("ordered-parser-message-budget")
                    sequence += 1
                    raw_bytes += len(body)
                    if len(context) > 1 or (
                        context
                        and (
                            type(context[0]) is not int
                            or not -0x80000000 <= context[0] <= 0x7FFFFFFF
                        )
                    ):
                        raise ProbeError("ordered-parser-message-context")
                    rows.append(
                        dict(
                            type="message",
                            world=identity["world"],
                            sequence=sequence,
                            messageId=message_id,
                            bodyBase64=base64.b64encode(body).decode("ascii"),
                            **({"contextTick": context[0]} if context else {}),
                        )
                    )
                    if message_id == 51:
                        identity = {**identity, "world": identity["world"] + 1}
                elif action[0] == "admit":
                    if type(action[1]) is not int or not 0 <= action[1] <= 0xFFFFFFFF:
                        raise ProbeError("ordered-parser-creation-sequence")
                    rows.append(
                        dict(
                            type="admit-creation-sequence",
                            world=identity["world"],
                            creationSequence=action[1],
                        )
                    )
                elif action[0] == "reset":
                    identity = {**identity, "world": identity["world"] + 1}
                    rows.append(dict(type="reset-world", world=identity["world"]))
                else:
                    raise ProbeError("ordered-parser-batch-action")
            if sequence != prior or not sources:
                sources.append((sequence, envelope.dequeued_ns, envelope.sdk_age_us))
        if rows:
            count = sequence - self.sequence
            # A live group has a short target size plus at most one atomic envelope.
            if (
                count > 16384 + self.BATCH_TARGET_MESSAGES
                or raw_bytes > self.MAX_BODY + self.BATCH_TARGET_BYTES
                or len(rows) > 49152
            ):
                raise ProbeError("ordered-parser-batch-budget")
            submitted_ns = self._enqueue(
                dict(type="batch", **self.identity, batch=self._batch + 1, rows=rows)
            )
            self._batch += 1
            self._inflight.append(
                InputBatch(
                    self._batch,
                    self.sequence + 1,
                    sequence,
                    raw_bytes,
                    submitted_ns,
                    identity["world"],
                    sources,
                )
            )
            self._pending_messages += count
            self._pending_bytes += raw_bytes
            self.peak_messages = max(self.peak_messages, self._pending_messages)
            self.peak_bytes = max(self.peak_bytes, self._pending_bytes)
            self.peak_batches = max(self.peak_batches, len(self._inflight))
        self.sequence = sequence
        if identity != self.identity:
            self.checkpoint = None
            self._pending_controls.clear()
            self._receipts.clear()
            self._subscriptions = None
        self.identity = identity
        return sequence

    def admit_creation_sequence(self, sequence):
        if type(sequence) is not int or not 0 <= sequence <= 0xFFFFFFFF:
            raise ProbeError("ordered-parser-creation-sequence")
        self.submit_batch([("admit", sequence)])

    def reset_world(self):
        self.submit_batch([("reset",)])

    def check(self):
        if self._failure:
            raise ProbeError(self._failure)
        if self._closed or self.process.poll() is not None:
            raise ProbeError("ordered-parser-not-running")

    def wait_for_progress(self, timeout=0.1):
        """Wake on results or worker failure, with a caller-supplied poll deadline."""
        self._available.clear()
        self.check()
        if not self.has_results():
            self._available.wait(timeout)
        self.check()

    def has_results(self):
        return bool(self._ready) or not self._output.empty()

    def poll(self, emit=None, *, deadline_ns=None, limit=256, cancelled=None):
        self.check()
        result = []
        read_bytes = 0
        for index in range(limit):
            if cancelled and cancelled():
                break
            if index and deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                break
            if not self._ready:
                if read_bytes >= 256 * 1024:
                    break
                try:
                    rows = self._output.get_nowait()
                except queue.Empty:
                    break
                rows, size, observed_ns = rows
                read_bytes += size
                self._ready.extend((row, observed_ns) for row in rows)
            row, observed_ns = self._ready.popleft()
            if (
                row.get("source") != self.identity["source"]
                or row.get("channel") != self.identity["channel"]
            ):
                raise ProbeError("ordered-parser-output-owner")
            world = row.get("world")
            if type(world) is not int or world > self.identity["world"]:
                raise ProbeError("ordered-parser-output-world")
            sequence = row.get("sequence")
            if sequence is not None and (
                type(sequence) is not int or not 0 <= sequence <= self.sequence
            ):
                raise ProbeError("ordered-parser-output-sequence")
            if row["type"] == "initialized" and row.get("protocol") != 4:
                raise ProbeError("ordered-parser-protocol-version")
            if row["type"] == "checkpoint":
                if (
                    not self._inflight
                    or sequence is None
                    or not self.completed_sequence < sequence <= self._inflight[0].last
                ):
                    raise ProbeError("ordered-parser-checkpoint-order")
                decode_us = row.get("decodeUs")
                if type(decode_us) is not int or decode_us < 0:
                    raise ProbeError("ordered-parser-checkpoint-duration")
                self.processed_messages += sequence - self.completed_sequence
                self.decode_us += decode_us
                self.completed_sequence = sequence
            if row["type"] == "batch-complete":
                if not self._inflight:
                    raise ProbeError("ordered-parser-unexpected-completion")
                batch = self._inflight[0]
                if (
                    row.get("batch") != batch.number
                    or world != batch.world
                    or sequence != batch.last
                    or self.completed_sequence != batch.last
                ):
                    raise ProbeError("ordered-parser-batch-order")
                self._inflight.popleft()
                self._pending_messages -= batch.last - batch.first + 1
                self._pending_bytes -= batch.raw_bytes
                self.processed_bytes += batch.raw_bytes
            if world != self.identity["world"]:
                continue  # Retired output cannot grant readiness, identities or ACKs.
            if row["type"] == "checkpoint":
                if (
                    type(row.get("schemaReady")) is not bool
                    or type(row.get("stringTables")) is not int
                ):
                    raise ProbeError("ordered-parser-checkpoint-shape")
                self.checkpoint = row
            if row["type"] == "diagnostic":
                self.diagnostics.append(
                    {key: row.get(key) for key in ("reason", "eventId")}
                )
            if row["type"] == "receipt":
                if (
                    type(row.get("tick")) is not int
                    or row["tick"] < 1
                    or type(row.get("epoch")) is not int
                    or row["epoch"] < 0
                    or type(row.get("full")) is not bool
                    or (
                        row.get("baselineAck") is not None
                        and (
                            type(row.get("baselineAck")) is not int
                            or row["baselineAck"] not in (0, 1)
                        )
                    )
                ):
                    raise ProbeError("ordered-parser-receipt-shape")
            if row["type"] in ("receipt", "recovery"):
                if len(self._pending_controls) + len(self._receipts) >= 4096:
                    raise ProbeError("ordered-parser-receipt-budget")
                self._pending_controls.append(row)
            if row["type"] == "checkpoint":
                while (
                    self._pending_controls
                    and self._pending_controls[0]["sequence"] <= sequence
                ):
                    self._receipts.append(self._pending_controls.popleft())
            if row["type"] == "recovery" and row.get("worldReinitialization"):
                raise ProbeError(
                    "ordered-parser-world-reinitialization: "
                    + str(row.get("reason", "unknown"))[:1024]
                )
            if row["type"] == "event-subscriptions":
                self._subscriptions = row
            if emit is not None and row["type"] in ("gap", "recovery", "world-reset"):
                emit(
                    dict(
                        kind="discontinuity",
                        reason=row.get("reason", row["type"]),
                        **{
                            key: row.get(key)
                            for key in (
                                "source",
                                "channel",
                                "world",
                                "sequence",
                                "tick",
                            )
                        },
                    )
                )
            if emit is not None and (
                row["type"] == "cursor"
                or (
                    row["type"] == "raw-event"
                    and row.get("name") in self.FORWARDED_EVENTS
                )
            ):
                timing = self._timing(sequence, observed_ns)
                row = {**row, "contextTick": row["tick"]}
                if row["type"] == "cursor":
                    row["tick"] = row["committedTick"]
                emit(
                    dict(
                        **timing,
                        kind="cursor" if row["type"] == "cursor" else row["name"],
                        **(
                            {"roundClock": row.get("roundClock")}
                            if row["type"] == "cursor" and "roundClock" in row
                            else {}
                        ),
                        **(
                            {
                                key: row.get(key)
                                for key in (
                                    "type",
                                    "name",
                                    "fields",
                                    "players",
                                    "pawns",
                                )
                            }
                            if row["type"] == "raw-event"
                            else {}
                        ),
                        **{
                            key: row.get(key)
                            for key in (
                                "tick",
                                "tickInterval",
                                "contextTick",
                                "committedTick",
                                "map",
                                "warmup",
                                "round",
                                "weapon",
                                "actor",
                                "target",
                                "source",
                                "channel",
                                "world",
                                "sequence",
                                "descriptorGeneration",
                                "eventServerTick",
                                "networkTick",
                                "identityResolved",
                            )
                        },
                    )
                )
            result.append(row)
        return result

    def _timing(self, sequence, observed_ns):
        now = time.monotonic_ns()
        if not self._inflight:
            raise ProbeError("ordered-parser-result-without-input")
        batch = self._inflight[0]
        if batch.first <= sequence <= batch.last:
            for last, dequeued, sdk_age in batch.envelopes:
                if sequence <= last:
                    return dict(
                        sdkQueueAgeUs=sdk_age,
                        dequeueToSubmitUs=(batch.submitted_ns - dequeued) // 1000,
                        submitToObservedUs=(now - batch.submitted_ns) // 1000,
                        resultQueueUs=(now - observed_ns) // 1000,
                    )
        raise ProbeError("ordered-parser-result-without-input")

    def pop_receipts(self):
        result = list(self._receipts)
        self._receipts.clear()
        return result

    def pop_subscriptions(self):
        result = self._subscriptions
        if result is not None and (
            self.checkpoint is None or self.checkpoint["sequence"] < result["sequence"]
        ):
            return None
        self._subscriptions = None
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            try:
                self._input.put_nowait(None)
            except queue.Full:
                pass
            self._writer.join(timeout=1)
            if self._writer.is_alive():
                cancel_io(self._writer)
            if not self._writer.is_alive():
                try:
                    self.process.stdin.close()  # Complete records then EOF; let the worker exit normally.
                except OSError:
                    pass
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            # A descendant can retain a pipe handle after the worker exits. Close
            # the owned Job before touching CRT descriptors held by I/O threads.
            self._job.close()
            for thread in (self._writer, self._reader):
                deadline = time.monotonic() + 1
                while thread.is_alive() and time.monotonic() < deadline:
                    cancel_io(thread)
                    thread.join(timeout=0.02)
                if thread.is_alive():
                    raise ProbeError("ordered-parser-io-close-timeout")
            self.process.stdin.close()
            self.process.stdout.close()
        finally:
            self._job.close()
