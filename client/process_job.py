"""Owned Windows process trees, with kill-on-close as a parent-exit fence."""

import os
import time
from wire import ProbeError


class ProcessJob:
    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [
                ("processTime", c.c_int64),
                ("jobTime", c.c_int64),
                ("flags", w.DWORD),
                ("minimum", c.c_size_t),
                ("maximum", c.c_size_t),
                ("limit", w.DWORD),
                ("affinity", c.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class Accounting(c.Structure):
            _fields_ = [
                ("times", c.c_int64 * 4),
                ("pageFaults", w.DWORD),
                ("totalProcesses", w.DWORD),
                ("activeProcesses", w.DWORD),
                ("terminatedProcesses", w.DWORD),
            ]

        self.accounting = Accounting

        class Extended(c.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", c.c_uint64 * 6),
                ("processMemory", c.c_size_t),
                ("jobMemory", c.c_size_t),
                ("peakProcess", c.c_size_t),
                ("peakJob", c.c_size_t),
            ]

        self.kernel = k = c.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.QueryInformationJobObject.argtypes = [
            w.HANDLE,
            c.c_int,
            c.c_void_p,
            w.DWORD,
            c.c_void_p,
        ]
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ProbeError("parser-job-create-failed")
        limits = Extended()
        limits.basic.flags = 0x2000
        if not k.SetInformationJobObject(
            self.handle, 9, c.byref(limits), c.sizeof(limits)
        ):
            self.close()
            raise ProbeError("parser-job-limits-failed")

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(
            self.handle, int(process._handle)
        ):
            raise ProbeError("parser-job-assignment-failed")

    def reap(self, timeout=2):
        if not self.handle:
            return
        import ctypes as c

        def active():
            status = self.accounting()
            if not self.kernel.QueryInformationJobObject(
                self.handle, 1, c.byref(status), c.sizeof(status), None
            ):
                raise ProbeError("attempt-job-query-failed")
            return status.activeProcesses

        if not active():
            return
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise ProbeError("attempt-job-termination-failed")
        deadline = time.monotonic() + timeout
        while active():
            if time.monotonic() >= deadline:
                raise ProbeError("attempt-job-reap-timeout")
            time.sleep(0.01)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
