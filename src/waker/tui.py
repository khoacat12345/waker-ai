"""Terminal quality status bar for the anti-slop gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityStatus:
    score: int = 100
    grade: str = "A"
    errors: int = 0
    warnings: int = 0
    suppressed: int = 0
    blocking: bool = False
    reverted: tuple[str, ...] = ()

    @property
    def display_grade(self) -> str:
        return "A+" if self.score >= 100 and self.grade == "A" else self.grade

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.display_grade,
            "errors": self.errors,
            "warnings": self.warnings,
            "suppressed": self.suppressed,
            "blocking": self.blocking,
            "reverted": list(self.reverted),
        }


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def quality_from_ledger(ledger: dict[str, Any] | None) -> QualityStatus:
    payload = (ledger or {}).get("quality") or {}
    score = max(0, min(100, _as_int(payload.get("score"), 100)))
    errors = max(0, _as_int(payload.get("errors")))
    warnings = max(0, _as_int(payload.get("warnings")))
    grade = str(payload.get("grade") or "A")
    if score < 90 and grade == "A":
        grade = "B" if score >= 80 else ("C" if score >= 70 else "F")
    return QualityStatus(
        score=score,
        grade=grade,
        errors=errors,
        warnings=warnings,
        suppressed=max(0, _as_int(payload.get("suppressed"))),
        blocking=bool(payload.get("blocking", errors > 0)),
        reverted=tuple(str(path) for path in (payload.get("reverted") or [])),
    )


def quality_line(ledger: dict[str, Any] | None) -> str:
    status = quality_from_ledger(ledger)
    suffix = (
        f" · {status.suppressed} legacy suppressed" if status.suppressed else ""
    )
    return (
        f"Cleanliness: {status.score}/100 · Grade {status.display_grade} · "
        f"{status.errors} errors · {status.warnings} warnings{suffix}"
    )


def quality_color(ledger: dict[str, Any] | None) -> str:
    status = quality_from_ledger(ledger)
    if status.blocking or status.errors:
        return "red"
    if status.warnings:
        return "yellow"
    return "green"


def build_quality_bar(ledger: dict[str, Any] | None):
    """Return a Rich Text status bar (Rich stays an optional import)."""
    from rich.text import Text

    return Text(quality_line(ledger), style=quality_color(ledger))


def build_quality_panel(ledger: dict[str, Any] | None):
    """Return a Rich Panel for dashboards or standalone status displays."""
    from rich.panel import Panel

    return Panel(
        build_quality_bar(ledger),
        title="Anti-Slop Quality",
        border_style=quality_color(ledger),
    )


__all__ = [
    "QualityStatus",
    "build_quality_bar",
    "build_quality_panel",
    "quality_color",
    "quality_from_ledger",
    "quality_line",
]
