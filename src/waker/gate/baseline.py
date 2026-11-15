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
        values = payload.get("fingerprints", [])
    elif isinstance(payload, list):
        values = payload
    else:
        raise ValueError("baseline must be a JSON object or list")
    return {str(value) for value in values}


def write_baseline(path: Path, findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(findings),
        "fingerprints": sorted({finding.fingerprint for finding in findings}),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
