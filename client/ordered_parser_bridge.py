"""Generation-fenced ordered parser pipe. No Steam/network authority lives here."""

from collections import deque
import base64
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from ipc_contract import (
    CreditLedger,
    Envelope,
    FORWARDED_EVENTS,
    GenerationCommitTracker,
    InputBatch,
    WORKER_RECORD_TYPES,
    format_public_record,
    validate_worker_record,
)
from process_io import cancel_io
from wire import ProbeError

__all__ = ["Envelope", "InputBatch", "OrderedParserBridge"]


class OrderedParserBridge:
    ordered = True
    MAX_QUEUED_BYTES = 32 * 1024**2
    # Reserve a whole legal channel envelope above either high watermark.
    BATCH_TARGET_MESSAGES, BATCH_TARGET_BYTES = 64, 256 * 1024
    HIGH_BATCHES, LOW_BATCHES = CreditLedger.HIGH_BATCHES, CreditLedger.LOW_BATCHES
    HIGH_MESSAGES, LOW_MESSAGES = (
        CreditLedger.HIGH_MESSAGES,
        CreditLedger.LOW_MESSAGES,
    )
    HIGH_BYTES, LOW_BYTES = CreditLedger.HIGH_BYTES, CreditLedger.LOW_BYTES
    MAX_BODY = 4 * 1024**2
    FORWARDED_EVENTS = FORWARDED_EVENTS

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
        self._ledger = CreditLedger()
        self._commits = GenerationCommitTracker()
        self._batch = 0
        self._ready = deque()
        self._closed = False
        self._failure = None
        self._queued_bytes = 0
        self._lock = threading.Lock()
        self._input = queue.Queue(maxsize=32)
        self._output = queue.Queue(maxsize=64)
        self._available = threading.Event()
        from process_job import ProcessJob

        self._job = ProcessJob()
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

    @property
    def checkpoint(self):
        return self._commits.checkpoint

    @property
    def completed_sequence(self):
        return self._commits.completed_sequence

    @property
    def processed_messages(self):
        return self._commits.processed_messages

    @property
    def decode_us(self):
        return self._commits.decode_us

    @property
    def processed_bytes(self):
        return self._ledger.processed_bytes

    @property
    def peak_messages(self):
        return self._ledger.peak_messages

    @property
    def peak_bytes(self):
        return self._ledger.peak_bytes

    @property
    def peak_batches(self):
        return self._ledger.peak_batches

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
                    or item.get("type") not in WORKER_RECORD_TYPES
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
        return self._ledger.caught_up

    def has_credit(self):
        return self._ledger.has_credit()

    def oldest_age_us(self, now_ns):
        return self._ledger.oldest_age_us(now_ns)

    def backlog(self, now_ns):
        return self._ledger.backlog(now_ns)

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
            self._ledger.record_batch(
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
        self.sequence = sequence
        if identity != self.identity:
            self._commits.reset_generation()
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
            world, sequence = validate_worker_record(
                row,
                source=self.identity["source"],
                channel=self.identity["channel"],
                max_world=self.identity["world"],
                max_sequence=self.sequence,
            )
            if row["type"] == "checkpoint":
                self._commits.advance_processed(
                    sequence, row.get("decodeUs"), self._ledger
                )
            if row["type"] == "batch-complete":
                self._ledger.complete_batch(
                    row.get("batch"), world, sequence, self._commits.completed_sequence
                )
            if world != self.identity["world"]:
                continue  # Retired output cannot grant readiness, identities or ACKs.
            self._commits.accept_current_world(row, sequence, self.diagnostics)
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
                timing = self._ledger.timing_for(sequence, observed_ns)
                emit(format_public_record(row, timing))
            result.append(row)
        return result

    def pop_receipts(self):
        return self._commits.pop_receipts()

    def pop_subscriptions(self):
        return self._commits.pop_subscriptions()

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
