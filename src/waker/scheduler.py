"""Verify scheduling: cheap checks first, full suite only when it matters.

Rules:
- A task's ``verify`` only runs when a file in its scope changed since the last
  verification (or it never ran).
- The full suite runs only when every task is a candidate for DONE, when the
  agent *claims* it is done (to catch lying), or every N kicks if configured.
- Cached results are keyed by a content digest, so touching a file re-runs the
  check and leaving it alone reuses the result.
"""

from __future__ import annotations

from pathlib import Path

from . import globs
from .evidence import diff_digest
from .models import Task


def scope_files(task: Task, changed_files: list[str]) -> list[str]:
    if not task.scope:
        return []
    return [f for f in changed_files if globs.matches_any(f, task.scope)]


def scope_digest(repo: str | Path, files: list[str]) -> str:
    return diff_digest(repo, sorted(set(files)))


def cached_result(cache: dict, key: str, digest: str) -> int | None:
    entry = cache.get(key)
    if not entry or entry.get("digest") != digest:
        return None
    return entry.get("exit")


def remember(cache: dict, key: str, digest: str, exit_code: int | None, kick: int) -> None:
    cache[key] = {"digest": digest, "exit": exit_code, "kick": kick}


def should_run_suite(
    candidate_done: bool,
    claimed_done: bool,
    kick: int,
    every: int,
) -> bool:
    if candidate_done or claimed_done:
        return True
    if every and kick > 0 and kick % every == 0:
        return True
    return False
