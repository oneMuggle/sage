"""Windows 7-compatible owned Job Object; no pywin32 dependency.

Create the process suspended; attach and resume before sending the worker's start handshake. Nested-job rejection is
an expected fail-closed result on Windows 7, never a reason to break away.
"""
from __future__ import annotations

import ctypes
from typing import Any


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_processes", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32), ("usage", ctypes.c_uint32),
        ("thread_id", ctypes.c_uint32), ("owner_pid", ctypes.c_uint32),
        ("base_priority", ctypes.c_int32), ("delta_priority", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


def _kernel32() -> Any:
    return ctypes.WinDLL("kernel32", use_last_error=True)


class WorkerJob:
    """Owned job containing one worker plus the optional Windows venv redirector."""

    def __init__(self, process_handle: int, memory_bytes: int) -> None:
        api = self._api = _kernel32()
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        api.CreateJobObjectW.restype = ctypes.c_void_p
        api.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32
        ]
        api.SetInformationJobObject.restype = ctypes.c_int
        api.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        api.AssignProcessToJobObject.restype = ctypes.c_int
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        api.CloseHandle.restype = ctypes.c_int
        self._handle = api.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError("CreateJobObjectW failed")
        try:
            limits = _ExtendedLimits()
            # ACTIVE_PROCESS | PROCESS_MEMORY | JOB_MEMORY | KILL_ON_JOB_CLOSE
            limits.basic.flags = 0x8 | 0x100 | 0x200 | 0x2000
            limits.basic.active_processes = 2
            limits.process_memory = memory_bytes
            limits.job_memory = memory_bytes
            if not api.SetInformationJobObject(
                self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise OSError("SetInformationJobObject failed")
            if not api.AssignProcessToJobObject(self._handle, process_handle):
                raise OSError("AssignProcessToJobObject failed (host job restrictions)")
        except BaseException:
            self.close()
            raise

    def resume(self, process_id: int) -> None:
        """Resume the sole thread of our CREATE_SUSPENDED process (Win7 APIs).

        Popen closes its primary thread handle, so locate that thread by our
        owned PID. Suspending before assignment prevents venv redirectors from
        spawning an interpreter outside the job before the stdin handshake.
        """
        api = self._api
        api.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        api.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        for function in (api.Thread32First, api.Thread32Next):
            function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry)]
            function.restype = ctypes.c_int
        api.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        api.OpenThread.restype = ctypes.c_void_p
        api.ResumeThread.argtypes = [ctypes.c_void_p]
        api.ResumeThread.restype = ctypes.c_uint32
        snapshot = api.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            raise OSError("CreateToolhelp32Snapshot failed")
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.owner_pid == process_id:
                    thread = api.OpenThread(0x2, False, entry.thread_id)  # SUSPEND_RESUME
                    if not thread:
                        raise OSError("OpenThread failed")
                    try:
                        if api.ResumeThread(thread) != 1:
                            raise OSError("ResumeThread failed or unexpected suspension count")
                    finally:
                        api.CloseHandle(thread)
                    return
                found = api.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Owned suspended worker thread not found")
        finally:
            api.CloseHandle(snapshot)

    def close(self) -> None:
        if self._handle:
            self._api.CloseHandle(self._handle)
            self._handle = None
