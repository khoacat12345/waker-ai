"""Core models for the read-only anti-slop gate."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

SEVERITIES = ("error", "warning", "info")
FAMILY = "anti_slop"


def make_fingerprint(
    rule: str,
    path: str,
    line: int,
    message: str,
    symbol: str | None = None,
) -> str:
    raw = f"{rule}|{path}|{line}|{symbol or ''}|{message}"
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    line: int
    col: int
    message: str
    suggestion: str = ""
    end_line: int | None = None
    family: str = FAMILY
    confidence: str = "certain"
    symbol: str | None = None
    fingerprint: str = ""
    baseline: bool = False

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            self.severity = "error"
        if not self.fingerprint:
            self.fingerprint = make_fingerprint(
                self.rule, self.path, self.line, self.message, self.symbol
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "family": self.family,
            "severity": self.severity,
            "confidence": self.confidence,
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "message": self.message,
            "suggestion": self.suggestion,
            "symbol": self.symbol,
            "fingerprint": self.fingerprint,
            "baseline": self.baseline,
        }


def score_findings(findings: list[Finding]) -> int:
    """Deterministic 0-100 cleanliness score.

    Errors cost 10, warnings 3, info 1. The score is computed from actionable
    findings only; baseline-suppressed legacy findings are counted separately.
    """
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")
    return max(0, min(100, 100 - 10 * errors - 3 * warnings - infos))


def grade_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def badge_color(score: int) -> str:
    if score >= 90:
        return "brightgreen"
    if score >= 80:
        return "green"
    if score >= 70:
        return "yellow"
    if score >= 60:
        return "orange"
    return "red"


def badge_markdown(score: int) -> str:
    color = badge_color(score)
    return (
        f"![waker anti-slop](https://img.shields.io/badge/"
        f"anti--slop-{score}%2F100-{color})"
    )


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    baseline_suppressed: int = 0
    score: int = 100
    grade: str = "A"
    badge: str = badge_markdown(100)

    @property
    def actionable(self) -> list[Finding]:
        return [f for f in self.findings if not f.baseline]

    @property
    def errors_count(self) -> int:
        return sum(1 for f in self.actionable if f.severity == "error")

    @property
    def warnings_count(self) -> int:
        return sum(1 for f in self.actionable if f.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "score": self.score,
            "grade": self.grade,
            "badge": self.badge,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
            "baseline_suppressed": self.baseline_suppressed,
            "errors": self.errors_count,
            "warnings": self.warnings_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "scan_errors": list(self.errors),
            "duration_ms": self.duration_ms,
        }
