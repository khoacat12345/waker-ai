"""Shared helpers for gate rules."""

from __future__ import annotations

from ..config import AntiSlopConfig
from ..model import Finding


def make_finding(
    rule: str,
    config: AntiSlopConfig,
    path: str,
    line: int,
    col: int,
    message: str,
    suggestion: str = "",
    *,
    end_line: int | None = None,
    confidence: str = "certain",
    symbol: str | None = None,
    severity: str | None = None,
) -> Finding | None:
    level = severity or config.severity_for(rule)
    if level == "off":
        return None
    return Finding(
        rule=rule,
        severity=level,
        path=path,
        line=line,
        col=col,
        end_line=end_line,
        message=message,
        suggestion=suggestion,
        confidence=confidence,
        symbol=symbol,
    )
