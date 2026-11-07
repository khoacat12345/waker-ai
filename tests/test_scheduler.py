from __future__ import annotations

from pathlib import Path

from waker import scheduler
from waker.models import Task


def test_scope_files_filters_by_glob():
    task = Task(id="T1", desc="x", scope=["src/auth/**", "tests/auth/**"])
    files = ["src/auth/a.py", "src/pay/b.py", "tests/auth/test_a.py"]
    assert scheduler.scope_files(task, files) == ["src/auth/a.py", "tests/auth/test_a.py"]


def test_cache_roundtrip(repo: Path):
    cache: dict = {}
    digest = scheduler.scope_digest(repo, ["tests/test_all.py"])
    assert scheduler.cached_result(cache, "T1", digest) is None
    scheduler.remember(cache, "T1", digest, 0, kick=1)
    assert scheduler.cached_result(cache, "T1", digest) == 0
    assert scheduler.cached_result(cache, "T1", "different") is None


def test_digest_changes_when_content_changes(repo: Path):
    first = scheduler.scope_digest(repo, ["tests/test_all.py"])
    (repo / "tests" / "test_all.py").write_text(
        "def test_real():\n    assert False\n# edit\n", encoding="utf-8"
    )
    second = scheduler.scope_digest(repo, ["tests/test_all.py"])
    assert first != second


def test_suite_runs_when_candidate_or_claiming():
    assert scheduler.should_run_suite(candidate_done=True, claimed_done=False, kick=0, every=0)
    assert scheduler.should_run_suite(candidate_done=False, claimed_done=True, kick=0, every=0)
    assert not scheduler.should_run_suite(candidate_done=False, claimed_done=False, kick=0, every=0)


def test_suite_interval():
    assert scheduler.should_run_suite(False, False, kick=3, every=3)
    assert not scheduler.should_run_suite(False, False, kick=0, every=3)
    assert not scheduler.should_run_suite(False, False, kick=2, every=3)
