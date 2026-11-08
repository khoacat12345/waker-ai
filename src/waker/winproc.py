"""Windows process creation helpers.

Every subprocess waker launches must be invisible: no conhost flash, no focus
steal. Centralising the flag here makes it impossible to forget one call site.

``CREATE_NO_WINDOW`` is 0x08000000. It is 0 on non-Windows platforms, so callers
can pass the flag unconditionally.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def pid_alive(pid: int) -> bool:
    """True if *pid* is a live process (used for stale run locks)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run(*args, **kwargs):  # type: ignore[no-untyped-def]
    """``subprocess.run`` with the console window suppressed."""
    kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | NO_WINDOW
    return subprocess.run(*args, **kwargs)


def popen(*args, **kwargs):  # type: ignore[no-untyped-def]
    """``subprocess.Popen`` with the console window suppressed."""
    kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | NO_WINDOW
    return subprocess.Popen(*args, **kwargs)
