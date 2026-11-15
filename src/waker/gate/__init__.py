"""Read-only anti-slop gate."""

from .baseline import (
    baseline_key,
    baseline_keys,
    baseline_path,
    fingerprint_set,
    load_baseline,
    suppress_known,
    write_baseline,
)
from .config import AntiSlopConfig
from .model import Finding, ScanResult, badge_markdown, grade_for, score_findings
from .scanner import scan_diff, scan_paths

__all__ = [
    "AntiSlopConfig",
    "Finding",
    "ScanResult",
    "badge_markdown",
    "baseline_key",
    "baseline_keys",
    "baseline_path",
    "fingerprint_set",
    "grade_for",
    "load_baseline",
    "scan_diff",
    "scan_paths",
    "score_findings",
    "suppress_known",
    "write_baseline",
]
