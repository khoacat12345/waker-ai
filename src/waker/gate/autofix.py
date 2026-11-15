"""Conservative, opt-in auto-fixes for the anti-slop gate.

Only two mechanical fixes are attempted:

* ``TYPE007``: add a ``# SAFETY:`` note beside a ``cast()`` that has none.
* ``DEAD002``: delete a whole-line, single-name unused import.

Anything ambiguous (multi-name imports, nested/multiline expressions, existing
comments) is skipped.  The resulting source is parsed again before it is
written; no execution, network access, or dependency is involved.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .model import Finding

AUTOFIX_RULES = frozenset({"TYPE007", "DEAD002"})
_SAFETY = "  # SAFETY: review this cast before keeping"


def _same_path(left: str, right: str) -> bool:
    a = str(left).replace("\\", "/").strip("/")
    b = str(right).replace("\\", "/").strip("/")
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


@dataclass
class FixResult:
    path: str
    changed: bool
    source: str
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "changed": self.changed,
            "applied": list(self.applied),
            "skipped": list(self.skipped),
        }


def _import_line_is_safe(value: str) -> bool:
    stripped = value.strip()
    if not stripped.startswith(("import ", "from ")):
        return False
    if ";" in stripped or "#" in stripped:
        return False
    if stripped.startswith("import "):
        return "," not in stripped
    if " import " not in stripped:
        return False
    imported = stripped.split(" import ", 1)[1]
    return "," not in imported and "*" not in imported


def _replacement(
    source_lines: list[str], finding: Finding
) -> tuple[int, str, str] | None:
    """Return (line index, replacement, applied label) or None if unsafe."""
    line_number = finding.line
    if line_number < 1 or line_number > len(source_lines):
        return None
    line = source_lines[line_number - 1]
    if finding.rule == "TYPE007":
        if "safety:" in line.lower() or "cast(" not in line:
            return None
        if "#" in line or not line.strip():
            return None
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        return line_number - 1, body + _SAFETY + ending, "TYPE007"
    if finding.rule == "DEAD002":
        if not _import_line_is_safe(line):
            return None
        return line_number - 1, "", "DEAD002"
    return None


def fix_source(
    source: str,
    path: str,
    findings: Iterable[Finding],
) -> FixResult:
    """Apply safe fixes to one source string and return the proposed result."""
    result = FixResult(path=path, changed=False, source=source)
    selected = [
        finding
        for finding in findings
        if _same_path(finding.path, path) and finding.rule in AUTOFIX_RULES
    ]
    if not selected:
        return result
    try:
        ast.parse(source, filename=path)
    except SyntaxError:
        result.skipped.extend(
            f"{finding.rule} at {finding.path}:{finding.line}: source does not parse"
            for finding in selected
        )
        return result

    lines = source.splitlines(keepends=True)
    edits: dict[int, tuple[str, str]] = {}
    for finding in selected:
        change = _replacement(lines, finding)
        if change is None:
            result.skipped.append(
                f"{finding.rule} at {finding.path}:{finding.line}: skipped unsafe edit"
            )
            continue
        index, replacement, label = change
        if index in edits:
            result.skipped.append(
                f"{finding.rule} at {finding.path}:{finding.line}: line already edited"
            )
            continue
        edits[index] = (replacement, label)

    if not edits:
        return result

    for index in sorted(edits, reverse=True):
        replacement, _ = edits[index]
        lines[index] = replacement
    candidate = "".join(lines)
    try:
        ast.parse(candidate, filename=path)
    except SyntaxError:
        result.skipped.append("post-fix source does not parse; no changes applied")
        return result

    result.source = candidate
    result.changed = candidate != source
    result.applied = [label for _, label in sorted(edits.values())]
    return result


def fix_file(
    path: str | Path,
    findings: Iterable[Finding],
    *,
    dry_run: bool = False,
    display_path: str | None = None,
) -> FixResult:
    target = Path(path)
    shown = display_path or str(path).replace("\\", "/")
    if target.is_symlink():
        return FixResult(
            path=shown,
            changed=False,
            source="",
            skipped=["file is a symlink"],
        )
    text = target.read_text(encoding="utf-8")
    result = fix_source(text, shown, findings)
    if result.changed and not dry_run:
        target.write_text(result.source, encoding="utf-8")
    return result


def fix_paths(
    repo: str | Path,
    findings: Sequence[Finding],
    *,
    dry_run: bool = False,
) -> list[FixResult]:
    """Apply fixes grouped by file, preserving files with no safe edits."""
    root = Path(repo).resolve()
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.path, []).append(finding)
    results: list[FixResult] = []
    for relative, file_findings in sorted(grouped.items()):
        candidate = root / relative
        if candidate.is_symlink():
            results.append(
                FixResult(
                    path=relative,
                    changed=False,
                    source="",
                    skipped=["file is a symlink"],
                )
            )
            continue
        target = candidate.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            results.append(
                FixResult(
                    path=relative,
                    changed=False,
                    source="",
                    skipped=["path escapes the repository"],
                )
            )
            continue
        if not target.is_file():
            results.append(
                FixResult(
                    path=relative,
                    changed=False,
                    source="",
                    skipped=["file does not exist"],
                )
            )
            continue
        results.append(
            fix_file(target, file_findings, dry_run=dry_run, display_path=relative)
        )
    return results


auto_fix = fix_paths
apply_safe_fixes = fix_paths
apply_fixes = fix_paths


__all__ = [
    "AUTOFIX_RULES",
    "FixResult",
    "apply_fixes",
    "apply_safe_fixes",
    "auto_fix",
    "fix_file",
    "fix_paths",
    "fix_source",
]
