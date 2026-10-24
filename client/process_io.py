"""Bounded process input/output; no SDK work or connection configuration logging."""
import json
import os
import queue
import threading
import time
from wire import ProbeError

MAX_RECORD_BYTES = 65536  # Includes the terminating LF.


def encode_record(row):
    data = (json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if len(data) > MAX_RECORD_BYTES:
        raise ProbeError('output-record-budget')
    return data


class PublicRecords:
    """One public order across messages and world resets, separate from parser ACKs."""
    def __init__(self, sink):
        self.sink, self.sequence = sink, 0

    def __call__(self, row):
        if self.sequence >= 9007199254740991:
            raise ProbeError('output-sequence-budget')
        record = {**row, 'sequence': self.sequence + 1}
        encode_record(record)
        self.sink(record)
        self.sequence += 1


def cancel_io(thread):
    if os.name != 'nt' or not thread or not thread.is_alive() or not thread.native_id:
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
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
            self.stream = os.fdopen(fd, 'rb', buffering=0, closefd=False)
        if self.stream is not None:
            self.thread = threading.Thread(target=self._read, args=(configuration_reader,), daemon=True)
            self.thread.start()

    def _read(self, reader):
        try:
            if reader:
                self.value = reader(self.stream)
                self.configured.set()
            if not self.stopped.is_set():
                self.stream.read(1)  # EOF and any extra input both request stop.
        except Exception:
            self.error = 'configuration-boundary'
        finally:
            self.configured.set()
            self.stopped.set()

    def configuration(self, timeout=30):
        if not self.configured.wait(timeout) or self.error or self.value is None:
            self.close()
            raise ValueError('configuration-boundary')
        value, self.value = self.value, None
        return value

    def is_set(self):
        # Let a just-closed pipe publish EOF without waiting on a blocking read.
        return self.stopped.wait(.001) if self.thread else self.stopped.is_set()

    def close(self):
        self.stopped.set()
        deadline = time.monotonic() + 1
        while self.thread and self.thread.is_alive() and time.monotonic() < deadline:
            cancel_io(self.thread)
            self.thread.join(timeout=.02)
        return not self.thread or not self.thread.is_alive()


class OutputWriter:
    """SDK pump never waits on stdout. Cancel the owned writer on stop/backpressure."""
    def __init__(self, fd, *, max_bytes=8 * 1024**2, max_records=1024):
        if os.name == 'nt':
            import msvcrt
            # os.write uses the CRT descriptor: preserve UTF-8 bytes and the single LF.
            msvcrt.setmode(fd, os.O_BINARY)
        self.fd, self.max_bytes = fd, max_bytes
        self.queue = queue.Queue(maxsize=max_records)
        self.lock = threading.Lock()
        self.pending_bytes = 0
        self.failure = None
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def emit(self, row):
        self.check()
        data = encode_record(row)
        with self.lock:
            if self.pending_bytes + len(data) > self.max_bytes:
                raise ProbeError('output-backpressure')
            try:
                self.queue.put_nowait(data)
            except queue.Full:
                raise ProbeError('output-backpressure') from None
            self.pending_bytes += len(data)

    def check(self):
        if self.failure:
            raise ProbeError(self.failure)

    def _write(self):
        try:
            while not self.cancelled.is_set():
                data = self.queue.get()
                if data is None:
                    return
                view = memoryview(data)
                while view and not self.cancelled.is_set():
                    if os.name != 'nt':
                        import select
                        if not select.select([], [self.fd], [], .02)[1]:
                            continue
                    count = os.write(self.fd, view[:4096])
                    if not count:
                        raise OSError('output-closed')
                    view = view[count:]
                with self.lock:
                    self.pending_bytes -= len(data)
        except (OSError, ValueError):
            if not self.cancelled.is_set():
                self.failure = 'output-closed'

    def finish(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self.pending_bytes and not self.failure and time.monotonic() < deadline:
            time.sleep(.005)
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
            self.thread.join(timeout=.02)
        return not self.thread.is_alive()
