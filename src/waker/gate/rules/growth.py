"""File growth relative to a git baseline."""

from __future__ import annotations

from pathlib import Path

from ... import winproc
from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding
from .complexity import _code_lines


def _baseline_source(repo: Path, path: str, ref: str) -> str | None:
    if not ref:
        return None
    result = winproc.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8-sig", errors="replace")


def growth_findings(
    repo: str | Path,
    path: str,
    source: str,
    baseline_ref: str,
    config: AntiSlopConfig,
) -> list[Finding]:
    if config.track_file_growth <= 0 or not baseline_ref:
        return []
    old_source = _baseline_source(Path(repo), path, baseline_ref)
    if old_source is None:
        return []
    old_lines = len(_code_lines(old_source))
    new_lines = len(_code_lines(source))
    delta = new_lines - old_lines
    if delta < config.growth_min_lines:
        return []
    ratio = delta / max(old_lines, 1)
    if ratio <= config.track_file_growth:
        return []
    finding = make_finding(
        "SLOP007",
        config,
        path,
        1,
        1,
        f"File grew from {old_lines} to {new_lines} logical lines "
        f"(+{delta}, +{round(ratio * 100)}%; limit {round(config.track_file_growth * 100)}%).",
        "Move the new code into a focused module or split the file.",
        confidence="likely",
    )
    return [finding] if finding else []
