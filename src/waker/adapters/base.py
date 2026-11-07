"""Adapter contracts.

Tier 1 = native session resume (OpenCode, Claude Code).
Tier 2 = fresh process + context digest (generic).
Tier 3 = PTY keystroke injection (Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import TurnResult


@dataclass
class TurnContext:
    repo: str
    run_id: str
    session_id: str
    kick: int
    timeout: float
    prompt_file: str = ""
    resume_id: str | None = None
    freeze_after: float = 0.0
    use_freeze_probe: bool = True
    use_job: bool = True


class Adapter(Protocol):
    name: str

    def run_turn(self, prompt: str, ctx: TurnContext) -> TurnResult: ...
