"""On-disk evidence: what actually changed, what actually passes.

This module is the only place allowed to decide "done" for a task:

    done(T) = (changed_files  T.scope) AND (T.command exits 0)

No agent message is trusted here.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import globs
from .models import Failure, Task

RUNTIME_PREFIXES = (".waker/", ".git/")
DONE_PATTERNS = re.compile(
    r"(?:all\s+(?:tasks?\s+)?(?:done|completed)"
    r"|everything\s+(?:is\s+)?done"
    r"|task\s+complete"
    r"|hoàn\s+thành(?:\s+tất\s+cả)?"
    r"|xong\s+hết"
    r"|đã\s+xong)",
    re.IGNORECASE,
)
BLOCKED_RE = re.compile(r"^\s*BLOCKED\s*[:：]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
FAILED_RE = re.compile(r"^FAILED\s+(\S+?)(?:::([^\s]+))?(?:\s+-\s+(.+))?$", re.MULTILINE)
LOCATION_RE = re.compile(r"^(\S+\.py):(\d+):\s+(.+)$", re.MULTILINE)
SUSPECT_TOKENS = (
    "importerror",
    "modulenotfounderror",
    "attributeerror",
    "no module named",
    "error collecting",
    "errors during collection",
)


@dataclass
class CommandResult:
    exit_code: int | None
    output: str = ""
    duration: float = 0.0
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "duration": round(self.duration, 3),
            "timed_out": self.timed_out,
        }


@dataclass
class RequirementResult:
    """Per-task verification result."""

    task_id: str
    exit_code: int | None
    files: list[str] = field(default_factory=list)
    output: str = ""


def run_command(command: str, cwd: str | Path, timeout: float = 600.0) -> CommandResult:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return CommandResult(proc.returncode, output, time.time() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return CommandResult(None, stdout + stderr, time.time() - started, timed_out=True)


def _git(repo: str | Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout or ""


def list_files(repo: str | Path) -> list[str]:
    root = Path(repo)
    tracked = _git(root, "ls-files").splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    files = [
        globs.normalize(path)
        for path in [*tracked, *untracked]
        if path.strip() and (root / path.strip()).is_file()
    ]
    return sorted(set(files))


def changed_files(repo: str | Path, baseline: str) -> list[str]:
    """Tracked diffs since baseline + untracked files. Deleted files are kept."""
    root = Path(repo)
    diff = _git(root, "diff", "--name-only", baseline, "--").splitlines()
    staged = _git(root, "diff", "--name-only", "--cached", baseline, "--").splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    names = [
        globs.normalize(path)
        for path in [*diff, *staged, *untracked]
        if path.strip()
    ]
    return sorted(set(names))


def lines_changed(repo: str | Path, baseline: str) -> int:
    root = Path(repo)
    total = 0
    for line in _git(root, "diff", "--numstat", baseline, "--").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            for value in parts[:2]:
                if value.isdigit():
                    total += int(value)
    for name in _git(root, "ls-files", "--others", "--exclude-standard").splitlines():
        path = root / name
        try:
            total += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            continue
    return total


def diff_digest(repo: str | Path, files: list[str]) -> str:
    """Content hash of the changed set. Changes if bytes change, not just names."""
    root = Path(repo)
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8", "replace"))
        path = root / name
        if path.is_file():
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"<unreadable>")
        else:
            digest.update(b"<deleted>")
    return digest.hexdigest()


def hash_globs(repo: str | Path, patterns: list[str]) -> str:
    """Hash of every file matching *patterns* - the tamper baseline."""
    root = Path(repo)
    digest = hashlib.sha256()
    for name in list_files(root):
        if patterns and not globs.matches_any(name, patterns):
            continue
        digest.update(name.encode("utf-8", "replace"))
        try:
            digest.update((root / name).read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()


def test_signature(output: str) -> str:
    """Stable signature of the failures only - used for fingerprinting."""
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.startswith(("FAILED", "ERROR")) or "AssertionError" in line
    ]
    return hashlib.sha256("\n".join(sorted(set(lines))).encode("utf-8")).hexdigest()


def parse_failures(output: str) -> list[Failure]:
    failures: list[Failure] = []
    seen: set[tuple[str, str]] = set()
    for match in FAILED_RE.finditer(output):
        file_name, name, message = match.group(1), match.group(2) or "", match.group(3) or ""
        key = (file_name, name)
        if key in seen:
            continue
        seen.add(key)
        failures.append(Failure(file=file_name, name=name, message=message.strip()))
    if not failures:
        for match in LOCATION_RE.finditer(output):
            file_name, line, message = match.group(1), int(match.group(2)), match.group(3)
            failures.append(Failure(file=file_name, line=line, message=message.strip()))
    return failures[:20]


def suspect_test(failures: list[Failure], output: str) -> bool:
    """True when every failure looks like a broken test, not broken code."""
    lowered = output.lower()
    if "error collecting" in lowered or "errors during collection" in lowered:
        return True
    if not failures:
        return False
    messages = " ".join(f.message.lower() for f in failures)
    if not messages.strip():
        return False
    return any(token in messages for token in SUSPECT_TOKENS)


def claimed_done(output: str) -> bool:
    return bool(DONE_PATTERNS.search(output))


def parse_blocked(output: str) -> str | None:
    match = BLOCKED_RE.search(output)
    return match.group(1).strip() if match else None


def scope_hits(tasks: list[Task], files: list[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for task in tasks:
        if not task.scope:
            continue
        matched = [f for f in files if globs.matches_any(f, task.scope)]
        if matched:
            hits[task.id] = matched
    return hits


def unscoped_files(tasks: list[Task], files: list[str]) -> list[str]:
    patterns: list[str] = []
    for task in tasks:
        patterns.extend(task.scope)
    return [
        f
        for f in files
        if not f.startswith(RUNTIME_PREFIXES) and not globs.matches_any(f, patterns)
    ]


def verify_tasks(
    tasks: list[Task], repo: str | Path, timeout: float = 600.0
) -> dict[str, RequirementResult]:
    """Run every task command. Missing command counts as not-done."""
    results: dict[str, RequirementResult] = {}
    for task in tasks:
        if not task.command:
            results[task.id] = RequirementResult(task.id, None)
            continue
        outcome = run_command(task.command, cwd=repo, timeout=timeout)
        results[task.id] = RequirementResult(
            task.id, outcome.exit_code, output=outcome.output
        )
    return results


def restore_globs(repo: str | Path, patterns: list[str], baseline: str) -> list[str]:
    """Restore files matching *patterns* to the baseline commit.

    Used on TAMPER: the agent does not get to edit the exam.
    """
    root = Path(repo)
    restored: list[str] = []
    candidates = [f for f in list_files(root) if globs.matches_any(f, patterns)]
    for name in candidates:
        exists_in_baseline = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{baseline}:{name}"],
            capture_output=True,
            check=False,
        ).returncode == 0
        if exists_in_baseline:
            subprocess.run(
                ["git", "-C", str(root), "checkout", baseline, "--", name],
                capture_output=True,
                check=False,
            )
        else:
            path = root / name
            if path.exists():
                path.unlink()
        restored.append(name)
    return restored


def all_tasks_done(
    tasks: list[Task],
    hits: dict[str, list[str]],
    verifications: dict[str, RequirementResult],
    constraints: list[Task] | None = None,
    constraint_results: dict[str, RequirementResult] | None = None,
) -> bool:
    for task in tasks:
        if task.kind != "work":
            continue
        if not hits.get(task.id):
            return False
        result = verifications.get(task.id)
        if result is None or result.exit_code != 0:
            return False
    for constraint in constraints or []:
        if constraint.severity != "blocking":
            continue
        result = (constraint_results or {}).get(constraint.id)
        if result is None or result.exit_code != 0:
            return False
    return True
