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
from .autofix import (
    FixResult,
    apply_fixes,
    apply_safe_fixes,
    auto_fix,
    fix_file,
    fix_paths,
    fix_source,
)
from .config import AntiSlopConfig
from .external import (
    ESLintAdapter,
    EslintAdapter,
    ExternalAdapter,
    ExternalAdapterError,
    ExternalResult,
    OxlintAdapter,
    run_external_linters,
)
from .model import Finding, ScanResult, badge_markdown, grade_for, score_findings
from .scanner import scan_diff, scan_paths

__all__ = [
    "AntiSlopConfig",
    "ESLintAdapter",
    "EslintAdapter",
    "ExternalAdapter",
    "ExternalAdapterError",
    "ExternalResult",
    "Finding",
    "FixResult",
    "OxlintAdapter",
    "ScanResult",
    "apply_fixes",
    "apply_safe_fixes",
    "auto_fix",
    "badge_markdown",
    "baseline_key",
    "baseline_keys",
    "baseline_path",
    "fingerprint_set",
    "fix_file",
    "fix_paths",
    "fix_source",
    "grade_for",
    "load_baseline",
    "run_external_linters",
    "scan_diff",
    "scan_paths",
    "score_findings",
    "suppress_known",
    "write_baseline",
]
