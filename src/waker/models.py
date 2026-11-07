"""Core data models for waker-ai.

Everything here is a plain dataclass: no I/O, no subprocess, easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Diagnosis(str, Enum):
    """The only verdicts waker is allowed to reach.

    Order of evaluation lives in :mod:`waker.detector`, not here.
    """

    ALIVE = "ALIVE"
    TAMPER = "TAMPER"
    BLOCKED = "BLOCKED"
    FROZEN = "FROZEN"
    DONE = "DONE"
    SUSPECT_TEST = "SUSPECT_TEST"
    FALSE_DONE = "FALSE_DONE"
    THRASH = "THRASH"
    STALL = "STALL"
    BREAKER = "BREAKER"
    PARTIAL = "PARTIAL"


#: Diagnoses that stop the run immediately.
TERMINAL: frozenset[Diagnosis] = frozenset(
    {Diagnosis.DONE, Diagnosis.BLOCKED, Diagnosis.BREAKER, Diagnosis.SUSPECT_TEST}
)

#: Exit code per terminal diagnosis.
EXIT_CODES: dict[Diagnosis, int] = {
    Diagnosis.DONE: 0,
    Diagnosis.BREAKER: 2,
    Diagnosis.BLOCKED: 3,
    Diagnosis.SUSPECT_TEST: 4,
}


@dataclass
class Task:
    """One contract item.

    ``scope`` is how we bind on-disk evidence to this task; ``verify`` is how we
    decide it is actually finished. Constraints are tasks too, but they use
    ``check`` (a command that must exit 0) instead of ``verify``.
    """

    id: str
    desc: str
    scope: list[str] = field(default_factory=list)
    verify: str | None = None
    phase: str | None = None
    kind: str = "work"  # work | constraint
    check: str | None = None
    severity: str = "blocking"
    depends_on: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    test_writer: bool = False

    @property
    def command(self) -> str | None:
        """Command that must exit 0 for this item."""
        return self.verify if self.kind == "work" else (self.check or self.verify)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "desc": self.desc}
        if self.phase:
            out["phase"] = self.phase
        if self.kind != "work":
            out["kind"] = self.kind
        if self.scope:
            out["scope"] = list(self.scope)
        if self.verify:
            out["verify"] = self.verify
        if self.check:
            out["check"] = self.check
        if self.severity != "blocking":
            out["severity"] = self.severity
        if self.depends_on:
            out["depends_on"] = list(self.depends_on)
        if self.source:
            out["source"] = list(self.source)
        if self.test_writer:
            out["test_writer"] = True
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        known = {
            "id",
            "desc",
            "scope",
            "verify",
            "phase",
            "kind",
            "check",
            "severity",
            "depends_on",
            "source",
            "test_writer",
        }
        clean = {k: v for k, v in data.items() if k in known}
        clean.setdefault("id", "T?")
        clean.setdefault("desc", "")
        if isinstance(clean.get("scope"), str):
            clean["scope"] = [clean["scope"]]
        return cls(**clean)


@dataclass
class Question:
    """A question the daemon must ask a human. Never auto-answered when blocking."""

    id: str
    kind: str  # confirm | clarify | credential
    text: str
    options: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "kind": self.kind, "text": self.text}
        if self.options:
            out["options"] = list(self.options)
        if self.blocks:
            out["blocks"] = list(self.blocks)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Question":
        return cls(
            id=str(data.get("id", "Q?")),
            kind=str(data.get("kind", "clarify")),
            text=str(data.get("text", "")),
            options=list(data.get("options") or []),
            blocks=list(data.get("blocks") or []),
        )


@dataclass
class PlanBundle:
    """Result of a deterministic 4-bucket parse."""

    tasks: list[Task] = field(default_factory=list)
    constraints: list[Task] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)

    def all_tasks(self) -> list[Task]:
        return [*self.tasks, *self.constraints]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "constraints": [c.to_dict() for c in self.constraints],
            "preferences": list(self.preferences),
            "questions": [q.to_dict() for q in self.questions],
            "unassigned": list(self.unassigned),
        }


@dataclass
class Failure:
    file: str
    name: str = ""
    line: int | None = None
    message: str = ""

    def label(self) -> str:
        base = self.file
        if self.name:
            base = f"{base}::{self.name}"
        if self.line:
            base = f"{base}:{self.line}"
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "name": self.name,
            "line": self.line,
            "message": self.message,
        }


@dataclass
class TurnResult:
    exit_code: int | None
    output: str = ""
    duration: float = 0.0
    timed_out: bool = False
    frozen: bool = False
    session_id: str | None = None
    cost_usd: float = 0.0
    tokens: int = 0
    events: int = 0


@dataclass
class Observation:
    """Everything the pure detector is allowed to see."""

    turn_state: str = "exited"  # running | idle | exited
    exit_code: int | None = None
    elapsed: float = 0.0
    last_event_age: float = 0.0
    diff_hash: str = ""
    prev_diff_hash: str | None = None
    changed_files: list[str] = field(default_factory=list)
    lines_changed: int = 0
    in_scope_files: dict[str, list[str]] = field(default_factory=dict)
    test_exit: int | None = None
    has_test: bool = False
    test_signature: str = ""
    tamper: bool = False
    claimed_done: bool = False
    blocked_reason: str | None = None
    all_tasks_done: bool = False
    integrity_ok: bool = True
    suspect_test: bool = False
    fingerprint: str = ""
    prev_fingerprint: str | None = None
    same_fingerprint_streak: int = 0
    kicks: int = 0
    max_kicks: int = 5
    elapsed_total: float = 0.0
    max_wall_clock: float = 5400.0
    cost_usd: float = 0.0
    max_cost_usd: float = 0.0
    alive_threshold: float = 120.0
    freeze_after: float = 300.0
    stall_after: float = 240.0
    unanswered_questions: int = 0
    unscoped_changes: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    diagnosis: Diagnosis
    exit_code: int
    report_path: str
    kicks: int
    duration: float
    message: str = ""
