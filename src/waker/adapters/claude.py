"""Claude Code adapter (tier 1: native session resume).

Command:

    claude -p --output-format stream-json --verbose
           [--permission-mode acceptEdits]
           [--resume <session>]
           "<prompt>"

Claude generates its own session id on the first turn; the adapter captures it
from the stream and the engine stores it in ``RunState.agent_session_id`` so the
next turn can use ``--resume``.

Permission handling: ``-p`` mode has no TTY, so an unanswered permission request
becomes a *false freeze*. The adapter always sets an explicit permission mode
(default ``acceptEdits``) and flags permission-denied results in the output so
the wake prompt can tell the agent what happened.
"""

from __future__ import annotations

import shlex

from ..claude_events import extract_info, parse_events
from ..models import TurnResult
from ..process import run_live
from .base import TurnContext


class ClaudeAdapter:
    name = "claude"

    def __init__(
        self,
        binary: str = "claude",
        permission_mode: str = "acceptEdits",
        extra_args: str = "",
    ) -> None:
        self.binary = binary
        self.permission_mode = permission_mode
        self.extra_args = extra_args
        self._last_total_cost = 0.0

    def build_argv(self, prompt: str, ctx: TurnContext) -> list[str]:
        argv = [self.binary, "-p", "--output-format", "stream-json", "--verbose"]
        if self.permission_mode:
            argv.extend(["--permission-mode", self.permission_mode])
        if ctx.resume_id:
            argv.extend(["--resume", ctx.resume_id])
        if self.extra_args:
            argv.extend(shlex.split(self.extra_args))
        argv.append(prompt)
        return argv

    def run_turn(self, prompt: str, ctx: TurnContext) -> TurnResult:
        freeze = ctx.freeze_after if ctx.use_freeze_probe else 0.0
        result = run_live(
            self.build_argv(prompt, ctx),
            cwd=ctx.repo,
            timeout=ctx.timeout,
            freeze_after=freeze,
            use_job=ctx.use_job,
        )
        events = parse_events(result.output)
        info = extract_info(events)

        cost_delta = max(0.0, info.cost_usd - self._last_total_cost)
        self._last_total_cost = max(self._last_total_cost, info.cost_usd)

        output = result.output
        if info.permission_denied:
            output += (
                "\n[waker] Claude reported a permission denial. "
                "Use --permission-mode bypassPermissions for unattended runs "
                "(only in a sandboxed repo).\n"
            )

        return TurnResult(
            exit_code=result.exit_code,
            output=output,
            duration=result.duration,
            timed_out=result.timed_out,
            frozen=result.frozen,
            session_id=info.session_id,
            cost_usd=cost_delta,
            tokens=info.tokens,
            events=len(events),
        )
