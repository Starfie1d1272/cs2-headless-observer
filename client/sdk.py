"""Local in-process SDK C ABI adapter. No login credentials, ticket files or logging.

Loading the provided native library and constructing NativePort starts a real
connection. Only the explicitly invoked local driver should instantiate this.
"""
import ctypes as c
import os
from pathlib import Path
from channel import MAX_BYTES
from wire import ProbeError


class NativeStartError(Exception):
    def __init__(self, boot_code, init_result):
        super().__init__('native-start-failed')
        self.boot_code, self.init_result = boot_code, init_result


class NativePort:
    def __init__(self, library, endpoint, now_ms, steam_api=None):
        # Absolute path avoids ambiguous library search for this research host.
        self.directory = None
        if os.name == 'nt' and steam_api is not None:
            self.directory = os.add_dll_directory(str(Path(steam_api).resolve(strict=True).parent))
        try:
            self.lib = c.CDLL(str(Path(library).resolve(strict=True)))
        except BaseException:
            if self.directory: self.directory.close()
            raise
        self.lib.observer_abi_version.argtypes = []
        self.lib.observer_abi_version.restype = c.c_int
        if self.lib.observer_abi_version() != 2:
            if self.directory: self.directory.close()
            raise ProbeError('native-abi-version')
        byte = c.POINTER(c.c_ubyte)
        signatures = {
            'abi_version': ([], c.c_int),
            'boot_failure': ([], c.c_int), 'init_result': ([], c.c_int),
            'create': ([c.c_char_p, c.c_uint64], c.c_void_p),
            'state': ([c.c_void_p], c.c_int), 'failure': ([c.c_void_p], c.c_int),
            'pump': ([c.c_void_p, c.c_uint64], None),
            'remote_id': ([c.c_void_p], c.c_uint64),
            'local_id': ([c.c_void_p], c.c_uint64),
            'accept_server_auth2': ([c.c_void_p], c.c_int),
            'request_ticket': ([c.c_void_p], c.c_int),
            'auth': ([c.c_void_p, c.POINTER(c.c_uint32)], byte),
            'send': ([c.c_void_p, byte, c.c_uint32, c.c_int], c.c_int),
            'receive': ([c.c_void_p, byte, c.c_uint32, c.POINTER(c.c_int)], c.c_int),
            'close': ([c.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, 'observer_' + name)
            function.argtypes, function.restype = args, result
        self.buffer = (c.c_ubyte * MAX_BYTES)()
        self.handle = self.lib.observer_create(endpoint.encode('ascii'), now_ms)
        if not self.handle:
            if self.directory: self.directory.close()
            raise NativeStartError(self.lib.observer_boot_failure(), self.lib.observer_init_result())

    @property
    def state(self):
        return self.lib.observer_state(self.handle)

    @property
    def failure(self):
        return self.lib.observer_failure(self.handle)

    def pump(self, now_ms):
        self.lib.observer_pump(self.handle, now_ms)

    def remote_id(self):
        return self.lib.observer_remote_id(self.handle)

    def local_id(self):
        return self.lib.observer_local_id(self.handle)

    def accept_server_auth2(self):
        if self.lib.observer_accept_server_auth2(self.handle) != 1:
            raise ProbeError('native-auth2-phase-invalid')

    def request_ticket(self):
        if self.lib.observer_request_ticket(self.handle) != 1:
            raise ProbeError('native-ticket-request-failed')

    def with_auth(self, consume):
        size = c.c_uint32()
        pointer = self.lib.observer_auth(self.handle, c.byref(size))
        if not pointer or not 8 < size.value <= 2048:
            raise ProbeError('native-ticket-not-ready')
        # Scope-bounded copy. No JSON/CLI/log path. Python cannot guarantee erasure
        # of immutable temporaries in consume's protobuf/password construction.
        local = c.string_at(pointer, size.value)
        try:
            return consume(local)
        finally:
            del local

    def send(self, data, flags):
        if not data or len(data) > 512 * 1024 or flags not in (5, 8):
            raise ProbeError('native-send-boundary')
        local = (c.c_ubyte * len(data)).from_buffer_copy(data)
        try:
            if self.lib.observer_send(self.handle, local, len(data), flags) != 1:
                raise ProbeError('native-send-failed')
        finally:
            c.memset(local, 0, len(local))

    def receive(self):
        reliable = c.c_int()
        size = self.lib.observer_receive(self.handle, self.buffer, len(self.buffer), c.byref(reliable))
        if size < 0 or size > len(self.buffer) or (size and reliable.value not in (0, 1)):
            raise ProbeError('native-receive-failed')
        if not size:
            return None
        return bytes(self.buffer[:size]), bool(reliable.value)

    def close(self):
        if self.handle:
            self.lib.observer_close(self.handle)
            self.handle = None
            c.memset(self.buffer, 0, len(self.buffer))
            if self.directory: self.directory.close(); self.directory = None

