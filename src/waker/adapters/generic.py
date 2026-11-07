"""Generic process adapter (tier 2).

The command may contain:

* ``{prompt_file}`` - path to a file containing the prompt (safest)
* ``{prompt}``      - the prompt, shell-quoted
* ``{session}``     - the run session id

With no placeholder the prompt is passed in ``WAKER_PROMPT`` and on stdin is
intentionally **not** used (TUI agents ignore stdin).
"""

from __future__ import annotations

import os
import shlex
import subprocess

from ..models import TurnResult
from ..process import run_live
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

        freeze = ctx.freeze_after if ctx.use_freeze_probe else 0.0
        result = run_live(
            command,
            cwd=ctx.repo,
            timeout=ctx.timeout,
            freeze_after=freeze,
            env=env,
            use_job=ctx.use_job,
        )
        return TurnResult(
            exit_code=result.exit_code,
            output=result.output,
            duration=result.duration,
            timed_out=result.timed_out,
            frozen=result.frozen,
        )
