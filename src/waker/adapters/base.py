"""Adapter contracts.

Tier 1 = native session resume (OpenCode, Claude Code).
Tier 2 = fresh process + context digest (generic).
Tier 3 = PTY keystroke injection (not implemented in Phase 1).
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


class Adapter(Protocol):
    name: str

    def run_turn(self, prompt: str, ctx: TurnContext) -> TurnResult: ...
