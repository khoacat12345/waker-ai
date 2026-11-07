"""OpenCode adapter (tier 1: native session resume + live JSON stream + cost).

Command:

    opencode run --session <id> --auto --format json [--model <m>] "<prompt>"

The prompt is passed as an **argv element**, never through a shell. On Windows
the npm shim is bypassed in favour of the real ``opencode.exe`` because shell
quoting mangles prompts that contain quotes or backslashes (verified: a prompt
with a Windows verify command made the shell invocation fail with exit 1).

Cost is not in the JSON stream (verified on v2.0.32); it is read from
``opencode session export`` before and after the turn, and the delta is
attributed to this turn.
"""

from __future__ import annotations

import shlex

from ..models import TurnResult
from ..opencode_events import parse_events, read_session_usage, resolve_opencode_binary
from ..process import run_live
from .base import TurnContext
from .generic import quote_arg


class OpenCodeAdapter:
    name = "opencode"

    def __init__(
        self,
        model: str | None = None,
        binary: str = "opencode",
        extra_args: str = "",
    ) -> None:
        self.model = model
        self.extra_args = extra_args
        self.binary = resolve_opencode_binary(binary)
        self._last_total_cost = 0.0
        self._last_total_tokens = 0

    def build_argv(self, prompt: str, ctx: TurnContext) -> list[str]:
        argv = [
            self.binary,
            "run",
            "--session",
            ctx.session_id,
            "--auto",
            "--format",
            "json",
        ]
        if self.model:
            argv.extend(["--model", self.model])
        if self.extra_args:
            argv.extend(shlex.split(self.extra_args))
        argv.append(prompt)
        return argv

    def build_command(self, prompt: str, ctx: TurnContext) -> str:
        """Human-readable form (telemetry / tests). Not used to execute."""
        return " ".join(quote_arg(part) for part in self.build_argv(prompt, ctx))

    def run_turn(self, prompt: str, ctx: TurnContext) -> TurnResult:
        before = read_session_usage(ctx.session_id, ctx.repo, binary=self.binary)
        if not before.ok:
            before.cost_usd = self._last_total_cost
            before.tokens = self._last_total_tokens

        argv = self.build_argv(prompt, ctx)
        freeze = ctx.freeze_after if ctx.use_freeze_probe else 0.0
        result = run_live(
            argv,
            cwd=ctx.repo,
            timeout=ctx.timeout,
            freeze_after=freeze,
            use_job=ctx.use_job,
        )

        after = read_session_usage(ctx.session_id, ctx.repo, binary=self.binary)
        if after.ok:
            cost_delta = max(0.0, after.cost_usd - before.cost_usd)
            token_delta = max(0, after.tokens - before.tokens)
            self._last_total_cost = after.cost_usd
            self._last_total_tokens = after.tokens
        else:
            cost_delta = 0.0
            token_delta = 0

        events = parse_events(result.output)
        return TurnResult(
            exit_code=result.exit_code,
            output=result.output,
            duration=result.duration,
            timed_out=result.timed_out,
            frozen=result.frozen,
            session_id=ctx.session_id,
            cost_usd=cost_delta,
            tokens=token_delta,
            events=len(events),
        )
