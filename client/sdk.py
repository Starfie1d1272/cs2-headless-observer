"""Local in-process SDK C ABI adapter. No login credentials, ticket files or logging.

Loading the provided native library and constructing NativePort starts a real
connection. Only the explicitly invoked local driver should instantiate this.
"""

import ctypes as c
import os
from pathlib import Path
import time
from channel import MAX_BYTES
from wire import ProbeError


class NativeStartError(Exception):
    def __init__(self, boot_code, init_result):
        super().__init__("native-start-failed")
        self.boot_code, self.init_result = boot_code, init_result


class Received(c.Structure):
    _fields_ = [
        ("data", c.c_void_p),
        ("sdk_queue_age_us", c.c_int64),
        ("size", c.c_uint32),
        ("reliable", c.c_int32),
    ]


class NativePort:
    def __init__(self, library, endpoint, now_ms, steam_api=None):
        # Absolute path avoids ambiguous library search for this research host.
        self.directory = None
        if os.name == "nt" and steam_api is not None:
            self.directory = os.add_dll_directory(
                str(Path(steam_api).resolve(strict=True).parent)
            )
        try:
            self.lib = c.CDLL(str(Path(library).resolve(strict=True)))
        except BaseException:
            if self.directory:
                self.directory.close()
            raise
        self.lib.observer_abi_version.argtypes = []
        self.lib.observer_abi_version.restype = c.c_int
        if self.lib.observer_abi_version() != 4:
            if self.directory:
                self.directory.close()
            raise ProbeError("native-abi-version")
        byte = c.POINTER(c.c_ubyte)
        signatures = {
            "abi_version": ([], c.c_int),
            "boot_failure": ([], c.c_int),
            "init_result": ([], c.c_int),
            "create": ([c.c_char_p, c.c_uint64], c.c_void_p),
            "remote_end_reason": ([c.c_void_p], c.c_int),
            "state": ([c.c_void_p], c.c_int),
            "failure": ([c.c_void_p], c.c_int),
            "pump": ([c.c_void_p, c.c_uint64], None),
            "remote_id": ([c.c_void_p], c.c_uint64),
            "local_id": ([c.c_void_p], c.c_uint64),
            "accept_server_auth2": ([c.c_void_p], c.c_int),
            "request_ticket": ([c.c_void_p], c.c_int),
            "auth": ([c.c_void_p, c.POINTER(c.c_uint32)], byte),
            "send": ([c.c_void_p, byte, c.c_uint32, c.c_int], c.c_int),
            "receive_many": ([c.c_void_p, c.POINTER(Received), c.c_int], c.c_int),
            "release_received": ([c.c_void_p], None),
            "close": ([c.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, "observer_" + name)
            function.argtypes, function.restype = args, result
        self.batch = (Received * 8)()
        self.batch_count = self.batch_index = 0
        self.dequeue_ns = None
        self.handle = self.lib.observer_create(endpoint.encode("ascii"), now_ms)
        if not self.handle:
            if self.directory:
                self.directory.close()
            raise NativeStartError(
                self.lib.observer_boot_failure(), self.lib.observer_init_result()
            )

    @property
    def state(self):
        return self.lib.observer_state(self.handle)

    @property
    def failure(self):
        return self.lib.observer_failure(self.handle)

    @property
    def remote_end_reason(self):
        return self.lib.observer_remote_end_reason(self.handle)

    def pump(self, now_ms):
        self.lib.observer_pump(self.handle, now_ms)

    def remote_id(self):
        return self.lib.observer_remote_id(self.handle)

    def local_id(self):
        return self.lib.observer_local_id(self.handle)

    def accept_server_auth2(self):
        if self.lib.observer_accept_server_auth2(self.handle) != 1:
            raise ProbeError("native-auth2-phase-invalid")

    def request_ticket(self):
        if self.lib.observer_request_ticket(self.handle) != 1:
            raise ProbeError("native-ticket-request-failed")

    def with_auth(self, consume):
        size = c.c_uint32()
        pointer = self.lib.observer_auth(self.handle, c.byref(size))
        if not pointer or not 8 < size.value <= 2048:
            raise ProbeError("native-ticket-not-ready")
        # Scope-bounded copy. No JSON/CLI/log path. Python cannot guarantee erasure
        # of immutable temporaries in consume's protobuf/password construction.
        local = c.string_at(pointer, size.value)
        try:
            return consume(local)
        finally:
            del local

    def send(self, data, flags):
        if not data or len(data) > 512 * 1024 or flags not in (1, 5, 8):
            raise ProbeError("native-send-boundary")
        local = (c.c_ubyte * len(data)).from_buffer_copy(data)
        try:
            if self.lib.observer_send(self.handle, local, len(data), flags) != 1:
                raise ProbeError("native-send-failed")
        finally:
            c.memset(local, 0, len(local))

    def pending_receive_age_ns(self, now_ns):
        return now_ns - self.dequeue_ns if self.batch_index < self.batch_count else None

    def receive_backlog(self, now_ns):
        pending = self.batch_count - self.batch_index
        age = self.pending_receive_age_ns(now_ns)
        return dict(
            pendingMessages=pending,
            pendingBytes=sum(
                self.batch[index].size
                for index in range(self.batch_index, self.batch_count)
            ),
            oldestAgeUs=age // 1000 if age is not None else None,
        )

    def receive(self):
        if self.batch_index == self.batch_count:
            self.batch_count = self.lib.observer_receive_many(
                self.handle, self.batch, len(self.batch)
            )
            self.dequeue_ns = time.monotonic_ns()
            self.batch_index = 0
            if not 0 <= self.batch_count <= len(self.batch):
                raise ProbeError("native-receive-failed")
            if not self.batch_count:
                return None
        item = self.batch[self.batch_index]
        if (
            not item.data
            or not 0 < item.size <= MAX_BYTES
            or item.reliable not in (0, 1)
        ):
            raise ProbeError("native-receive-failed")
        data = c.string_at(item.data, item.size)
        self.batch_index += 1
        if self.batch_index == self.batch_count:
            self.lib.observer_release_received(self.handle)
        return (
            data,
            bool(item.reliable),
            self.dequeue_ns,
            None if item.sdk_queue_age_us < 0 else item.sdk_queue_age_us,
        )

    def close(self):
        if self.handle:
            self.lib.observer_close(self.handle)
            self.handle = None
            if self.directory:
                self.directory.close()
                self.directory = None
