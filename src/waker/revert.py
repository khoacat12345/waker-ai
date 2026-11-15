"""Selective rollback for anti-slop violations.

The default policy is ``kick``.  ``revert`` only touches the files named by
blocking findings and restores those paths from the pre-turn git checkpoint.
It deliberately never runs ``git reset --hard``: unrelated work in the same
working tree must survive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import winproc


def _relative_paths(repo: str | Path, paths: list[str] | set[str]) -> list[str]:
    root = Path(repo).resolve()
    result: set[str] = set()
    for raw in paths:
        value = str(raw).replace("\\", "/").strip()
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
        if any(part in {"..", ""} for part in candidate.parts):
            continue
        if candidate.parts and candidate.parts[0] == ".git":
            continue
        result.add(candidate.as_posix())
    return sorted(result)


def _tracked_in(repo: Path, source: str, path: str) -> bool:
    result = winproc.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{source}:{path}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _remove_untracked(repo: Path, paths: list[str]) -> list[str]:
    removed: list[str] = []
    for path in paths:
        target = repo / path
        try:
            target.relative_to(repo)
        except ValueError:
            continue
        if not target.exists() or target.is_symlink() or target.is_dir():
            continue
        try:
            target.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed


def restore_files(
    repo: str | Path,
    paths: list[str] | set[str] | str,
    *,
    source: str = "HEAD",
) -> dict[str, Any]:
    """Restore only ``paths`` from ``source`` and remove new untracked files.

    Returns a small JSON-safe report so the engine can write an audit event:
    ``restored``, ``removed`` and ``failed`` lists.  Any path outside the repo
    is ignored; no directory, symlink, or git metadata is touched.
    """
    root = Path(repo).resolve()
    if isinstance(paths, str):
        paths = [paths]
    candidates = _relative_paths(root, paths)
    tracked = [path for path in candidates if _tracked_in(root, source, path)]
    untracked = [path for path in candidates if path not in tracked]
    failed: list[str] = []

    if tracked:
        result = winproc.run(
            [
                "git",
                "-C",
                str(root),
                "restore",
                "--source",
                source,
                "--staged",
                "--worktree",
                "--",
                *tracked,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            failed.extend(tracked)
            tracked = []

    removed = _remove_untracked(root, untracked)
    failed.extend(path for path in untracked if path not in removed)
    return {
        "source": source,
        "restored": tracked,
        "removed": removed,
        "failed": sorted(set(failed)),
    }


__all__ = ["restore_files", "revert_files", "restore_violating_files"]

revert_files = restore_files
restore_violating_files = restore_files
