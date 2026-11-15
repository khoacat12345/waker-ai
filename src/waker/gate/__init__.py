"""Read-only anti-slop gate."""

from .baseline import baseline_path, load_baseline, write_baseline
from .config import AntiSlopConfig
from .model import Finding, ScanResult, badge_markdown, grade_for, score_findings
from .scanner import scan_diff, scan_paths

__all__ = [
    "AntiSlopConfig",
    "Finding",
    "ScanResult",
    "badge_markdown",
    "baseline_path",
    "grade_for",
    "load_baseline",
    "scan_diff",
    "scan_paths",
    "score_findings",
    "write_baseline",
]
