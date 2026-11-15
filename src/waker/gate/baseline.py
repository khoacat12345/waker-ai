"""Baseline fingerprints for legacy anti-slop debt."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import AntiSlopConfig
from .model import Finding


def baseline_path(repo: str | Path, config: AntiSlopConfig) -> Path | None:
    if config.baseline == "off":
        return None
    if config.baseline == "auto":
        return Path(repo) / ".waker" / "anti-slop-baseline.json"
    path = Path(config.baseline)
    return path if path.is_absolute() else Path(repo) / path


def load_baseline(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        values = [*payload.get("fingerprints", []), *payload.get("keys", [])]
    elif isinstance(payload, list):
        values = payload
    else:
        raise ValueError("baseline must be a JSON object or list")
    return {str(value) for value in values}


def baseline_key(finding: Finding) -> str:
    """Stable identity that survives line-number shifts in a legacy file."""
    return (
        f"{finding.rule}|{finding.path}|{finding.symbol or ''}|"
        f"{finding.message}"
    )


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda finding: (
            finding.path,
            finding.line,
            finding.col,
            finding.rule,
            finding.message,
            finding.symbol or "",
        ),
    )


def _ordinal_keys(findings: list[Finding]) -> dict[int, str]:
    counts: dict[str, int] = {}
    result: dict[int, str] = {}
    for finding in _ordered(findings):
        base = baseline_key(finding)
        ordinal = counts.get(base, 0)
        counts[base] = ordinal + 1
        result[id(finding)] = f"{base}|{ordinal}"
    return result


def baseline_keys(findings: list[Finding]) -> set[str]:
    return set(_ordinal_keys(findings).values())


def fingerprint_set(findings: list[Finding]) -> set[str]:
    """Return stable fingerprints for a set of findings."""
    return {finding.fingerprint for finding in findings}


def suppress_known(findings: list[Finding], known: set[str]) -> int:
    """Mark known legacy findings as baseline; return how many were marked."""
    ordinals = _ordinal_keys(findings)
    marked = 0
    for finding in findings:
        if finding.baseline:
            continue
        if (
            finding.fingerprint not in known
            and ordinals[id(finding)] not in known
        ):
            continue
        finding.baseline = True
        marked += 1
    return marked


def write_baseline(path: Path, findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(findings),
        "fingerprints": sorted({finding.fingerprint for finding in findings}),
        "keys": sorted(baseline_keys(findings)),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
