"""PTY tier-3 adapter: drive any text-mode CLI like a human would.

Windows: ConPTY through ``pywinpty``; screen parsing through ``pyte``.
The process is kept alive across turns, so the agent keeps its own context even
without a native session id.
"""

from __future__ import annotations

import os
import re
import shlex
import threading
import time

from ..models import TurnResult
from ..process import kill_tree
from .base import TurnContext

try:  # optional extra: pip install "waker-ai[pty]"
    import pyte  # type: ignore
    import winpty  # type: ignore

    AVAILABLE = os.name == "nt"
    IMPORT_ERROR = "" if AVAILABLE else "PTY tier-3 is Windows-only in v0.3"
except ImportError as exc:  # pragma: no cover - depends on environment
    pyte = None
    winpty = None
    AVAILABLE = False
    IMPORT_ERROR = f"missing dependency: {exc}. Install with: pip install 'waker-ai[pty]'"

DEFAULT_PROMPT = re.compile(r"[>\u276f$#]\s*$")
APPROVAL = re.compile(
    r"(do you want to proceed|allow|approve|\[y/n\]|\(y/n\)|yes/no|continue\?)",
    re.IGNORECASE,
)


class PtyAdapter:
    name = "pty"

    def __init__(
        self,
        command: str | list[str],
        idle_seconds: float = 1.2,
        rows: int = 40,
        cols: int = 120,
        prompt_pattern: str | None = None,
        auto_approve: bool = True,
        bracketed_paste: bool = False,
    ) -> None:
        if not AVAILABLE:
            raise RuntimeError(IMPORT_ERROR)
        self.argv = shlex.split(command) if isinstance(command, str) else list(command)
        self.idle_seconds = idle_seconds
        self.rows = rows
        self.cols = cols
        self.prompt_pattern = re.compile(prompt_pattern) if prompt_pattern else DEFAULT_PROMPT
        self.auto_approve = auto_approve
        self.bracketed_paste = bracketed_paste

        self._proc = None
        self._screen = None
        self._stream = None
        self._lock = threading.Lock()
        self._last_text = ""
        self._last_change = 0.0
        self._last_approve = 0.0

    # ------------------------------------------------------------------ process

    def _ensure(self, ctx: TurnContext) -> None:
        if self._proc is not None and self._proc.isalive():
            return
        self._screen = pyte.Screen(self.cols, self.rows)
        self._stream = pyte.Stream(self._screen)
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("TERM", "xterm-256color")
        self._proc = winpty.PtyProcess.spawn(
            self.argv, cwd=ctx.repo, env=env, dimensions=(self.rows, self.cols)
        )
        self._last_text = ""
        self._last_change = time.time()
        thread = threading.Thread(target=self._reader, args=(self._proc,), daemon=True)
        thread.start()

    def _reader(self, process) -> None:
        while True:
            try:
                data = process.read(4096)
            except (EOFError, OSError, ValueError):
                return
            if not data:
                return
            with self._lock:
                try:
                    self._stream.feed(data)
                except (TypeError, ValueError):
                    return

    def _text(self) -> str:
        with self._lock:
            if self._screen is None:
                return ""
            return "\n".join(self._screen.display).rstrip()

    def _write(self, data: str) -> None:
        if self._proc is None or not self._proc.isalive():
            return
        if self.bracketed_paste and len(data) > 1:
            self._proc.write("\x1b[200~" + data + "\x1b[201~")
        else:
            self._proc.write(data)

    # ------------------------------------------------------------------- waiting

    def _wait(
        self, timeout: float, freeze_after: float = 0.0
    ) -> tuple[bool, bool, str]:
        started = time.time()
        frozen = False
        while True:
            now = time.time()
            text = self._text()
            if text != self._last_text:
                self._last_text = text
                self._last_change = now

            if self.auto_approve and now - self._last_approve > 1.0:
                tail = text[-500:]
                if APPROVAL.search(tail):
                    self._last_approve = now
                    self._write("y\r")

            stable = now - self._last_change >= self.idle_seconds
            if stable and self.prompt_pattern.search(text[-400:]):
                return True, False, text

            if freeze_after and now - self._last_change >= freeze_after:
                frozen = True
                break
            if timeout and now - started >= timeout:
                break
            if self._proc is not None and not self._proc.isalive():
                if stable:
                    return True, False, text
                break
            time.sleep(0.1)
        return False, frozen, self._text()

    # ---------------------------------------------------------------------- api

    def run_turn(self, prompt: str, ctx: TurnContext) -> TurnResult:
        self._ensure(ctx)
        # Wait for the initial prompt (banner screens can take a while).
        self._wait(min(ctx.timeout, 60.0), freeze_after=0.0)

        payload = prompt.replace("\r", "")
        if not self.bracketed_paste:
            payload = payload.replace("\n", " ")
        self._last_text = self._text()
        self._last_change = time.time()
        self._write(payload + "\r")

        started = time.time()
        ok, frozen, text = self._wait(
            timeout=ctx.timeout,
            freeze_after=ctx.freeze_after if ctx.use_freeze_probe else 0.0,
        )
        duration = time.time() - started

        if frozen:
            self._kill()
            return TurnResult(
                exit_code=None,
                output=text[-20000:],
                duration=duration,
                timed_out=False,
                frozen=True,
                session_id=ctx.session_id,
            )
        return TurnResult(
            exit_code=0 if ok else None,
            output=text[-20000:],
            duration=duration,
            timed_out=not ok,
            frozen=False,
            session_id=ctx.session_id,
        )

    def _kill(self) -> None:
        if self._proc is None:
            return
        pid = getattr(self._proc, "pid", None)
        try:
            if self._proc.isalive():
                self._proc.terminate(force=True)
        except (OSError, ValueError):
            if pid:
                kill_tree(pid)
        self._proc = None

    def close(self) -> None:
        self._kill()
