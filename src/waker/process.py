"""Live process execution: stream output, probe for freezes, kill the whole tree."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .winjob import WinJob

SKIP_DIRS = {
    ".git",
    ".waker",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    ".idea",
    ".vscode",
}


@dataclass
class LiveResult:
    exit_code: int | None
    output: str
    duration: float
    timed_out: bool
    frozen: bool
    lines: int
    last_activity_age: float


def repo_activity(root: str | Path, limit: int = 20000) -> tuple[int, int, int]:
    """Cheap-ish activity marker: (file count, total bytes, newest mtime_ns)."""
    count = 0
    total = 0
    newest = 0
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            try:
                stat = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            count += 1
            total += stat.st_size
            if stat.st_mtime_ns > newest:
                newest = stat.st_mtime_ns
            if count >= limit:
                return count, total, newest
    return count, total, newest


def kill_tree(pid: int, job: WinJob | None = None) -> None:
    """Terminate *pid* and all descendants. Never raises."""
    if job is not None:
        job.terminate()
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _popen_flags() -> int:
    if os.name == "nt":
        return subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return 0


def run_live(
    command: str | list[str],
    cwd: str | Path,
    timeout: float,
    freeze_after: float = 0.0,
    probe_interval: float = 0.5,
    on_line: Callable[[str], None] | None = None,
    use_job: bool = True,
    env: dict[str, str] | None = None,
) -> LiveResult:
    """Run a command (shell string or argv list), stream it, and enforce limits.

    ``freeze_after`` enables the live probe: if there is no stdout **and** no
    file activity for that many seconds, the tree is killed and ``frozen=True``.
    """
    job = WinJob() if (use_job and os.name == "nt") else None
    started = time.time()

    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        shell=isinstance(command, str),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_popen_flags(),
        env=env,
    )
    if job is not None and job.ok:
        job.assign(proc.pid)

    chunks: list[str] = []
    lock = threading.Lock()
    last_activity = [time.time()]

    def reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                with lock:
                    chunks.append(line)
                last_activity[0] = time.time()
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:  # noqa: BLE001 - a listener must never kill the run
                        pass
        except (ValueError, OSError):
            return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    baseline = repo_activity(cwd) if freeze_after > 0 else None
    last_probe = 0.0
    frozen = False
    timed_out = False

    try:
        while proc.poll() is None:
            now = time.time()
            if timeout and now - started >= timeout:
                timed_out = True
                break
            if (
                freeze_after > 0
                and now - last_activity[0] >= freeze_after
                and now - last_probe >= probe_interval
            ):
                current = repo_activity(cwd)
                last_probe = now
                if current == baseline:
                    frozen = True
                    break
                baseline = current
            time.sleep(0.1)
    finally:
        if (timed_out or frozen) and proc.poll() is None:
            kill_tree(proc.pid, job)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid, job)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
                pass
        thread.join(timeout=3)
        if job is not None:
            job.close()

    with lock:
        output = "".join(chunks)
    return LiveResult(
        exit_code=proc.returncode,
        output=output,
        duration=time.time() - started,
        timed_out=timed_out,
        frozen=frozen,
        lines=len(chunks),
        last_activity_age=time.time() - last_activity[0],
    )
