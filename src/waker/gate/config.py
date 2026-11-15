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
    "tests/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
    "**/migrations/**",
    "**/generated/**",
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

    def included(self, path: str) -> bool:
        normalized = globs.normalize(path)
        return not self.excluded(normalized) and globs.matches_any(
            normalized, self.paths
        )

    def severity_for(self, rule: str) -> str:
        return self.severity.get(rule, "error")


__all__ = ["AntiSlopConfig", "DEFAULT_EXCLUDE", "DEFAULT_SEVERITY"]
