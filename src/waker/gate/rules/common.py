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
) -> Finding | None:
    severity = config.severity_for(rule)
    if severity == "off":
        return None
    return Finding(
        rule=rule,
        severity=severity,
        path=path,
        line=line,
        col=col,
        end_line=end_line,
        message=message,
        suggestion=suggestion,
        confidence=confidence,
        symbol=symbol,
    )
