"""Windows process creation helpers.

Every subprocess waker launches must be invisible: no conhost flash, no focus
steal. Centralising the flag here makes it impossible to forget one call site.

``CREATE_NO_WINDOW`` is 0x08000000. It is 0 on non-Windows platforms, so callers
can pass the flag unconditionally.
"""

from __future__ import annotations

import subprocess
import sys

NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def run(*args, **kwargs):  # type: ignore[no-untyped-def]
    """``subprocess.run`` with the console window suppressed."""
    kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | NO_WINDOW
    return subprocess.run(*args, **kwargs)


def popen(*args, **kwargs):  # type: ignore[no-untyped-def]
    """``subprocess.Popen`` with the console window suppressed."""
    kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | NO_WINDOW
    return subprocess.Popen(*args, **kwargs)
