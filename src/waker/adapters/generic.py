"""Generic process adapter (tier 2).

The command may contain:

* ``{prompt_file}`` - path to a file containing the prompt (safest)
* ``{prompt}``      - the prompt, shell-quoted
* ``{session}``     - the run session id

With no placeholder the prompt is passed on stdin and in ``WAKER_PROMPT``.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time

from ..models import TurnResult
from .base import TurnContext


def quote_arg(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


class GenericProcessAdapter:
    name = "generic"

    def __init__(self, command: str) -> None:
        self.command = command

    def _build(self, prompt: str, ctx: TurnContext) -> str:
        command = self.command
        if "{prompt_file}" in command and ctx.prompt_file:
            command = command.replace("{prompt_file}", quote_arg(ctx.prompt_file))
        if "{prompt}" in command:
            command = command.replace("{prompt}", quote_arg(prompt))
        if "{session}" in command:
            command = command.replace("{session}", quote_arg(ctx.session_id))
        return command

    def run_turn(self, prompt: str, ctx: TurnContext) -> TurnResult:
        command = self._build(prompt, ctx)
        env = os.environ.copy()
        env["WAKER_PROMPT"] = prompt
        env["WAKER_SESSION"] = ctx.session_id
        env["WAKER_RUN_ID"] = ctx.run_id
        env["WAKER_KICK"] = str(ctx.kick)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        started = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=ctx.repo,
                shell=True,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=ctx.timeout,
                env=env,
                check=False,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            return TurnResult(proc.returncode, output, time.time() - started)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            return TurnResult(
                None, stdout + stderr, time.time() - started, timed_out=True
            )
