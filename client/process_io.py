"""Bounded process input/output; no SDK work or connection configuration logging."""

from collections import deque
import json
import os
import queue
import threading
import time
from wire import ProbeError

MAX_RECORD_BYTES = 65536  # Includes the terminating LF.
SOFT_AGE_US = 250_000
HARD_AGE_US = 2_000_000
DRAIN_TIMEOUT_MS = 5000
HEALTH_INTERVAL_NS = 1_000_000_000


def source_age_us(row):
    if "submitToObservedUs" not in row:
        return None
    return (
        (row["sdkQueueAgeUs"] or 0)
        + row["dequeueToSubmitUs"]
        + row["submitToObservedUs"]
    )


def private_file(path, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(
        fd, mode, **({"encoding": "utf-8", "newline": "\n"} if "b" not in mode else {})
    )


def encode_record(row):
    data = (
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    if len(data) > MAX_RECORD_BYTES:
        raise ProbeError("output-record-budget")
    return data


class PublicRecords:
    """One public order across messages and world resets, separate from parser ACKs."""

    def __init__(self, sink, *, encoded=False):
        self.sink, self.sequence, self.encoded = sink, 0, encoded

    def __call__(self, row):
        if self.sequence >= 9007199254740991:
            raise ProbeError("output-sequence-budget")
        record = {**row, "sequence": self.sequence + 1}
        data = encode_record(record)
        if self.encoded:
            self.sink(record, data)
        else:
            self.sink(record)
        self.sequence += 1


def cancel_io(thread):
    if os.name != "nt" or not thread or not thread.is_alive() or not thread.native_id:
        return
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenThread.restype = wintypes.HANDLE
    k.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenThread(1, False, thread.native_id)
    if handle:
        try:
            k.CancelSynchronousIo(handle)
        finally:
            k.CloseHandle(handle)


class ManagedOwner:
    """The same reader consumes configuration and stop input, including buffered bytes."""

    def __init__(self, fd=None, *, stream=None, configuration_reader=None):
        self.stopped = threading.Event()
        self.configured = threading.Event()
        self.value = self.error = None
        self.thread = None
        self.stream = stream
        if stream is None and fd is not None:
            self.stream = os.fdopen(fd, "rb", buffering=0, closefd=False)
        if self.stream is not None:
            self.thread = threading.Thread(
                target=self._read, args=(configuration_reader,), daemon=True
            )
            self.thread.start()

    def _read(self, reader):
        try:
            if reader:
                self.value = reader(self.stream)
                self.configured.set()
            if not self.stopped.is_set():
                self.stream.read(1)  # EOF and any extra input both request stop.
        except Exception:
            self.error = "configuration-boundary"
        finally:
            self.configured.set()
            self.stopped.set()

    def configuration(self, timeout=30):
        if not self.configured.wait(timeout) or self.error or self.value is None:
            self.close()
            raise ValueError("configuration-boundary")
        value, self.value = self.value, None
        return value

    def is_set(self):
        return self.stopped.is_set()

    def close(self):
        self.stopped.set()
        deadline = time.monotonic() + 1
        while self.thread and self.thread.is_alive() and time.monotonic() < deadline:
            cancel_io(self.thread)
            self.thread.join(timeout=0.02)
        return not self.thread or not self.thread.is_alive()


class OutputWriter:
    """SDK pump never waits on stdout. Cancel the owned writer on stop/backpressure."""

    def __init__(
        self,
        fd,
        *,
        max_bytes=8 * 1024**2,
        max_records=1024,
        age_limit_us=None,
        progress=None,
    ):
        if os.name == "nt":
            import msvcrt

            # os.write uses the CRT descriptor: preserve UTF-8 bytes and the single LF.
            msvcrt.setmode(fd, os.O_BINARY)
        self.fd, self.max_bytes = fd, max_bytes
        self.queue = queue.Queue(maxsize=max_records)
        self.lock = threading.Lock()
        self.pending_bytes = 0
        self.pending = deque()
        self.peak_records = self.peak_bytes = 0
        self.age_limit_us = age_limit_us
        self.last_cursor = None
        self.last_completed_age_us = None
        self.max_age_us = None
        self.failure = None
        self.progress = progress
        self.last_delivered_sequence = 0
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def emit(self, row):
        self.emit_encoded(encode_record(row))

    def emit_encoded(self, data, *, cursor=None, source_age_us=None, sequence=None):
        self.check()
        enqueued = time.monotonic_ns()
        with self.lock:
            if self.pending_bytes + len(data) > self.max_bytes:
                raise ProbeError("output-backpressure")
            try:
                self.queue.put_nowait((data, enqueued, cursor, source_age_us, sequence))
            except queue.Full:
                raise ProbeError("output-backpressure") from None
            self.pending.append((enqueued, source_age_us))
            self.pending_bytes += len(data)
            self.peak_records = max(self.peak_records, len(self.pending))
            self.peak_bytes = max(self.peak_bytes, self.pending_bytes)

    def _oldest_age_us(self, now):
        return (now - self.pending[0][0]) // 1000 if self.pending else None

    def status(self):
        with self.lock:
            return dict(
                pendingRecords=len(self.pending),
                pendingBytes=self.pending_bytes,
                peakRecords=self.peak_records,
                peakBytes=self.peak_bytes,
                oldestAgeUs=self._oldest_age_us(time.monotonic_ns()),
                maxCompletedAgeUs=self.max_age_us,
                lastWriterResidenceUs=self.last_completed_age_us,
                lastDeliveredCursor=self.last_cursor,
                lastDeliveredSequence=self.last_delivered_sequence,
            )

    def check(self):
        if self.failure:
            raise ProbeError(self.failure)
        if self.age_limit_us is not None:
            with self.lock:
                age = self._oldest_age_us(time.monotonic_ns())
                source_age = self.pending[0][1] if self.pending else None
            if age is not None:
                if age >= self.age_limit_us:
                    raise ProbeError("output-residence-overload")
                if source_age is not None and source_age + age >= self.age_limit_us:
                    raise ProbeError("source-residence-overload")

    def _write(self):
        try:
            while not self.cancelled.is_set():
                record = self.queue.get()
                if record is None or self.cancelled.is_set():
                    return
                data, enqueued, cursor, source_age_us, sequence = record
                view = memoryview(data)
                while view and not self.cancelled.is_set():
                    limit = self.age_limit_us
                    if limit is not None:
                        age = (time.monotonic_ns() - enqueued) // 1000
                        if age >= limit:
                            self.failure = "output-residence-overload"
                            return
                        if source_age_us is not None and source_age_us + age >= limit:
                            self.failure = "source-residence-overload"
                            return
                    if os.name != "nt":
                        import select

                        if not select.select([], [self.fd], [], 0.02)[1]:
                            continue
                    count = os.write(self.fd, view if os.name == "nt" else view[:4096])
                    if not count:
                        raise OSError("output-closed")
                    view = view[count:]
                if self.cancelled.is_set():
                    return
                with self.lock:
                    age = (time.monotonic_ns() - enqueued) // 1000
                    self.last_completed_age_us = age
                    self.max_age_us = max(self.max_age_us or 0, age)
                    if cursor is not None:
                        self.last_cursor = cursor
                    if sequence is not None:
                        self.last_delivered_sequence = sequence
                    self.pending.popleft()
                    self.pending_bytes -= len(data)
                if self.progress:
                    self.progress.set()
        except (OSError, ValueError):
            if not self.cancelled.is_set():
                self.failure = "output-closed"
        finally:
            if self.progress:
                self.progress.set()

    def finish(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self.pending_bytes and not self.failure and time.monotonic() < deadline:
            time.sleep(0.005)
        if self.pending_bytes or self.failure:
            self.abort()
            return False
        self.queue.put_nowait(None)
        self.thread.join(timeout=max(0, deadline - time.monotonic()))
        if self.thread.is_alive():
            self.abort()
            return False
        return True

    def abort(self):
        self.cancelled.set()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        deadline = time.monotonic() + 1
        while self.thread.is_alive() and time.monotonic() < deadline:
            cancel_io(self.thread)
            self.thread.join(timeout=0.02)
        return not self.thread.is_alive()


class CaptureWriter:
    """One optional disk writer. Pressure truncates the capture at a record boundary."""

    def __init__(self, budget):
        self.budget = budget
        self.queue = queue.Queue(maxsize=128)
        self.pending_bytes = 0
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def emit(self, handle, data):
        with self.lock:
            if self.pending_bytes + len(data) > 8 * 1024**2:
                self.budget.truncated = True
                return
            if not self.budget.claim(len(data)):
                return
            try:
                self.queue.put_nowait((handle, data))
            except queue.Full:
                self.budget.truncated = True
                self.budget.written -= len(data)
                return
            self.pending_bytes += len(data)

    def _write(self):
        try:
            while not self.cancelled.is_set():
                record = self.queue.get()
                if record is None or self.cancelled.is_set():
                    return
                handle, data = record
                handle.write(data)
                with self.lock:
                    self.pending_bytes -= len(data)
        except (OSError, ValueError):
            with self.lock:
                self.budget.truncated = True

    def finish(self):
        deadline = time.monotonic() + 1
        try:
            self.queue.put(None, timeout=1)
            self.thread.join(timeout=max(0, deadline - time.monotonic()))
        except queue.Full:
            pass
        if self.thread.is_alive():
            self.cancelled.set()
            cancel_io(self.thread)
            self.thread.join(timeout=0.1)
        with self.lock:
            if self.pending_bytes:
                self.budget.truncated = True
                self.budget.written -= self.pending_bytes
        if self.thread.is_alive():
            raise ProbeError("capture-close-timeout")
