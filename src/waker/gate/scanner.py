"""Read-only anti-slop scanner."""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path

from .. import evidence, globs, winproc
from .baseline import baseline_path, load_baseline
from .config import AntiSlopConfig
from .model import Finding, ScanResult, badge_markdown, grade_for, score_findings
from .rules.common import make_finding
from .rules.complexity import complexity_findings
from .rules.duplicates import (
    Block,
    collect_blocks,
    copy_paste_findings,
    duplicate_symbol_findings,
)
from .rules.exceptions import silent_exception_findings
from .rules.growth import growth_findings

MAX_FILE_BYTES = 2 * 1024 * 1024
SUPPRESS_RE = re.compile(
    r"#\s*waker:\s*ignore\[(?P<rules>[A-Za-z0-9_,\s]+)\]\s+"
    r"reason\s*=\s*[\"'](?P<reason>.+?)[\"']"
)


def _is_git_repo(repo: Path) -> bool:
    result = winproc.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _safe_relative(repo: Path, path: Path) -> str | None:
    try:
        resolved = path.resolve()
        resolved.relative_to(repo.resolve())
    except (OSError, ValueError):
        return None
    return globs.normalize(str(resolved.relative_to(repo.resolve())))


def _all_python_files(repo: Path) -> list[Path]:
    """Fast tracked/untracked walk; falls back to a pruned os.walk."""
    top = winproc.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
    )
    is_worktree_root = False
    if top.returncode == 0:
        try:
            is_worktree_root = Path(
                top.stdout.decode("utf-8", errors="replace").strip()
            ).resolve() == repo.resolve()
        except OSError:
            is_worktree_root = False
    if is_worktree_root:
        result = winproc.run(
            [
                "git",
                "-C",
                str(repo),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "*.py",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            names = [
                name
                for name in result.stdout.decode("utf-8", errors="replace").split("\0")
                if name.endswith(".py")
            ]
            return [repo / name for name in names]

    skip = {".git", ".venv", "venv", "build", "dist", "node_modules", "__pycache__"}
    found: list[Path] = []
    for current, dirs, files in os.walk(repo):
        dirs[:] = [name for name in dirs if name not in skip]
        for name in files:
            if name.endswith(".py"):
                found.append(Path(current) / name)
    return found


def _candidate_files(
    repo: Path,
    config: AntiSlopConfig,
    changed_only: bool,
    baseline_ref: str,
) -> tuple[list[Path], int]:
    if changed_only:
        names = evidence.changed_files(repo, baseline_ref)
        candidates = [repo / name for name in names if name.endswith(".py")]
    else:
        candidates = _all_python_files(repo)
    included: list[Path] = []
    skipped = 0
    for path in candidates:
        relative = _safe_relative(repo, path)
        if relative is None or not path.exists():
            skipped += 1
            continue
        if not config.included(relative):
            skipped += 1
            continue
        if path.is_symlink():
            skipped += 1
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped += 1
                continue
        except OSError:
            skipped += 1
            continue
        included.append(path)
    return sorted(included, key=lambda item: str(item)), skipped


def _suppressions(source: str) -> dict[int, set[str]]:
    suppressions: dict[int, set[str]] = {}
    for number, line in enumerate(source.splitlines(), 1):
        match = SUPPRESS_RE.search(line)
        if not match:
            continue
        rules = {
            item.strip()
            for item in match.group("rules").split(",")
            if item.strip()
        }
        if rules:
            suppressions[number] = rules
    return suppressions


def _is_suppressed(
    finding: Finding, suppressions: dict[str, dict[int, set[str]]]
) -> bool:
    per_file = suppressions.get(finding.path, {})
    for line in (finding.line, finding.line + 1, finding.line - 1):
        if finding.rule in per_file.get(line, set()):
            return True
    return False


def scan_paths(
    repo: str | Path = ".",
    *,
    paths: list[str] | None = None,
    config: AntiSlopConfig | None = None,
    changed_only: bool | None = None,
    baseline_ref: str = "HEAD",
    use_baseline: bool = True,
) -> ScanResult:
    started = time.perf_counter()
    root = Path(repo).resolve()
    cfg = config or AntiSlopConfig()
    cfg.validate()
    result = ScanResult()

    if changed_only is None:
        changed_only = cfg.changed_only
    if changed_only and not _is_git_repo(root):
        result.errors.append("changed-only audit requires a git repository; use --all")
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    if paths:
        candidates = [root / path for path in paths]
        files = []
        for path in candidates:
            relative = _safe_relative(root, path)
            if relative and path.exists() and cfg.included(relative):
                files.append(path)
        skipped = len(candidates) - len(files)
    else:
        files, skipped = _candidate_files(root, cfg, changed_only, baseline_ref)

    result.files_skipped = skipped
    all_blocks: list[Block] = []
    suppression_map: dict[str, dict[int, set[str]]] = {}
    growth_paths: set[str] = set()
    if baseline_ref:
        try:
            growth_paths = set(evidence.changed_files(root, baseline_ref))
        except OSError:
            growth_paths = set()

    for path in files:
        relative = _safe_relative(root, path)
        if relative is None:
            result.files_skipped += 1
            continue
        try:
            source = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            result.errors.append(f"{relative}: {exc}")
            continue
        result.files_scanned += 1
        suppression_map[relative] = _suppressions(source)
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError as exc:
            finding = make_finding(
                "SLOP000",
                cfg,
                relative,
                exc.lineno or 1,
                exc.offset or 1,
                f"Syntax error: {exc.msg}",
                "Fix the syntax before running the gate.",
            )
            if finding:
                result.findings.append(finding)
            continue

        local: list[Finding] = []
        local.extend(duplicate_symbol_findings(tree, relative, cfg))
        local.extend(silent_exception_findings(tree, relative, cfg))
        local.extend(complexity_findings(tree, relative, source, cfg))
        if relative in growth_paths:
            local.extend(growth_findings(root, relative, source, baseline_ref, cfg))
        all_blocks.extend(collect_blocks(tree, relative, cfg))
        result.findings.extend(local)

    result.findings.extend(copy_paste_findings(all_blocks, cfg))
    result.findings = [
        finding
        for finding in result.findings
        if not _is_suppressed(finding, suppression_map)
    ]

    if use_baseline and cfg.baseline != "off":
        try:
            known = load_baseline(baseline_path(root, cfg))
        except (OSError, ValueError) as exc:
            result.errors.append(f"baseline: {exc}")
            known = set()
        for finding in result.findings:
            if finding.fingerprint in known:
                finding.baseline = True
                result.baseline_suppressed += 1

    actionable = [finding for finding in result.findings if not finding.baseline]
    result.score = score_findings(actionable)
    result.grade = grade_for(result.score)
    result.badge = badge_markdown(result.score)
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def scan_diff(
    repo: str | Path = ".",
    *,
    base: str = "HEAD",
    config: AntiSlopConfig | None = None,
    use_baseline: bool = True,
) -> ScanResult:
    return scan_paths(
        repo,
        config=config,
        changed_only=True,
        baseline_ref=base,
        use_baseline=use_baseline,
    )
