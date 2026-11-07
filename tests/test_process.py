from __future__ import annotations

import sys
import time
from pathlib import Path

from conftest import fake_agent

from waker.process import kill_tree, repo_activity, run_live


def test_run_live_accepts_argv_list(repo: Path):
    result = run_live(
        [sys.executable, "-c", "print('hello-argv')"], cwd=repo, timeout=30
    )
    assert result.exit_code == 0
    assert "hello-argv" in result.output


def test_repo_activity_changes_when_a_file_is_written(tmp_path: Path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    before = repo_activity(tmp_path)
    time.sleep(0.01)
    (tmp_path / "a.txt").write_text("two-two", encoding="utf-8")
    after = repo_activity(tmp_path)
    assert before != after


def test_live_probe_kills_a_frozen_agent(repo: Path):
    started = time.time()
    result = run_live(
        fake_agent("freeze"),
        cwd=repo,
        timeout=30,
        freeze_after=0.5,
        probe_interval=0.1,
    )
    elapsed = time.time() - started
    assert result.frozen is True
    assert result.timed_out is False
    assert elapsed < 15


def test_timeout_kills_the_process(repo: Path):
    started = time.time()
    result = run_live(fake_agent("freeze"), cwd=repo, timeout=0.6, freeze_after=0)
    assert result.timed_out is True
    assert time.time() - started < 15


def test_output_is_streamed(repo: Path):
    seen: list[str] = []
    result = run_live(fake_agent("blocked"), cwd=repo, timeout=30, on_line=seen.append)
    assert result.exit_code == 0
    assert any("BLOCKED" in line for line in seen)


def test_kill_tree_on_missing_pid_is_safe():
    kill_tree(999_999_999)  # must not raise
