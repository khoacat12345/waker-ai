"""Configuration for the anti-slop gate."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .. import globs

DEFAULT_EXCLUDE = (
    ".git/**",
    ".venv/**",
    "venv/**",
    "build/**",
    "dist/**",
    "**/__pycache__/**",
    "**/node_modules/**",
    "**/migrations/**",
    "**/generated/**",
)

TEST_PATHS = (
    "tests/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
)

DEFAULT_SEVERITY = {
    "SLOP000": "error",
    "SLOP001": "error",
    "SLOP002": "error",
    "SLOP003": "error",
    "SLOP004": "error",
    "SLOP005": "error",
    "SLOP006": "error",
    "SLOP007": "warning",
    "SLOP008": "warning",
    "TEST001": "error",
    "TEST002": "error",
    "TEST003": "error",
    "TEST004": "error",
    "TEST005": "error",
    "TEST006": "warning",
    "TEST007": "warning",
    "TEST008": "warning",
    "TYPE001": "error",
    "TYPE002": "error",
    "TYPE003": "error",
    "TYPE004": "error",
    "TYPE005": "error",
    "TYPE006": "error",
    "TYPE007": "error",
    "TYPE008": "error",
    "TYPE009": "error",
    "TYPE010": "error",
    "TYPE011": "error",
    "TYPE012": "error",
    "COMMENT001": "warning",
    "COMMENT002": "warning",
    "COMMENT003": "error",
    "COMMENT004": "warning",
    "SUPPRESS001": "error",
    "SUPPRESS002": "error",
    "STUB001": "error",
}


@dataclass
class AntiSlopConfig:
    enabled: bool = True
    max_function_lines: int = 100
    max_module_lines: int = 1000
    max_cyclomatic_complexity: int = 15
    max_nesting_depth: int = 5
    max_parameters: int = 8
    ban_broad_except: bool = True
    ban_silent_except: bool = True
    ban_duplicate_symbols: bool = True
    duplicate_block_min_lines: int = 20
    duplicate_block_min_statements: int = 8
    track_file_growth: float = 0.15
    growth_min_lines: int = 30
    paths: tuple[str, ...] = ("**/*.py",)
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    on_violation: str = "kick"  # kick | revert | abort
    baseline: str = "auto"  # auto | off | path
    changed_only: bool = True
    severity: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SEVERITY))

    # Phase 2 family switches (engine default-on is wired in Phase 4)
    enable_core: bool = True
    enable_tests: bool = False
    enable_types: bool = False
    enable_comments: bool = False
    is_test_paths: tuple[str, ...] = TEST_PATHS

    # Test integrity
    min_assertions_per_test: int = 1
    ban_trivial_assertions: bool = True
    ban_mock_of_sut: bool = True
    ban_uncalled_mock_assertions: bool = True
    ban_swallowed_assertions: bool = True
    ban_unconditional_skip: bool = True
    max_mock_ratio: float = 0.70

    # Type evidence
    ban_any_parameters: bool = True
    ban_any_returns: bool = True
    ban_any_aliases: bool = True
    ban_chained_casts: bool = True
    ban_widen_then_cast: bool = True
    ban_adhoc_isinstance: bool = True
    require_safety_comment: bool = True
    ban_unexplained_type_ignore: bool = True
    ban_string_attribute_access: bool = True
    unsafe_dict_values: bool = True
    ban_known_value_widening: bool = True
    max_isinstance_checks: int = 3

    # Comment / suppression
    ban_obvious_comments: bool = True
    ban_step_comments: bool = True
    ban_placeholder_comments: bool = True
    require_suppression_reason: bool = True
    require_suppression_code: bool = True
    stub_policy: str = "error"  # error | warning | off

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AntiSlopConfig":
        data = dict(data or {})
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown anti_slop keys: {', '.join(unknown)}")
        if "paths" in data:
            data["paths"] = tuple(data["paths"])
        if "exclude" in data:
            data["exclude"] = tuple(data["exclude"])
        if "is_test_paths" in data:
            data["is_test_paths"] = tuple(data["is_test_paths"])
        if "severity" in data:
            merged = dict(DEFAULT_SEVERITY)
            merged.update(dict(data["severity"] or {}))
            data["severity"] = merged
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.max_function_lines < 1:
            raise ValueError("max_function_lines must be >= 1")
        if self.max_module_lines < 1:
            raise ValueError("max_module_lines must be >= 1")
        if self.max_cyclomatic_complexity < 1:
            raise ValueError("max_cyclomatic_complexity must be >= 1")
        if not (0 <= self.track_file_growth < 1):
            raise ValueError("track_file_growth must be in [0, 1)")
        if not (0 <= self.max_mock_ratio <= 1):
            raise ValueError("max_mock_ratio must be in [0, 1]")
        if self.max_isinstance_checks < 1:
            raise ValueError("max_isinstance_checks must be >= 1")
        if self.stub_policy not in {"error", "warning", "off"}:
            raise ValueError("stub_policy must be error|warning|off")
        if self.on_violation not in {"kick", "revert", "abort"}:
            raise ValueError("on_violation must be kick|revert|abort")
        for rule, level in self.severity.items():
            if level not in {"error", "warning", "info", "off"}:
                raise ValueError(f"invalid severity for {rule}: {level}")

    def with_overrides(self, **kwargs: Any) -> "AntiSlopConfig":
        clean = {key: value for key, value in kwargs.items() if value is not None}
        cfg = replace(self, **clean)
        cfg.validate()
        return cfg

    def excluded(self, path: str) -> bool:
        return globs.matches_any(globs.normalize(path), self.exclude)

    def is_test_path(self, path: str) -> bool:
        return globs.matches_any(globs.normalize(path), self.is_test_paths)

    def included(self, path: str) -> bool:
        normalized = globs.normalize(path)
        return not self.excluded(normalized) and globs.matches_any(
            normalized, self.paths
        )

    def severity_for(self, rule: str) -> str:
        return self.severity.get(rule, "error")


__all__ = ["AntiSlopConfig", "DEFAULT_EXCLUDE", "DEFAULT_SEVERITY"]
