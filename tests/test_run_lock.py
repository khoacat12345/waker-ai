from __future__ import annotations

import os
from pathlib import Path

import pytest

from waker.state import (
    RunPaths,
    acquire_run_lock,
    release_run_lock,
    run_is_active,
    run_lock_pid,
)
from waker.winproc import pid_alive


def make_paths(tmp_path: Path) -> RunPaths:
    paths = RunPaths(tmp_path, "run1")
    paths.root.mkdir(parents=True)
    return paths


def test_pid_alive():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(999_999_999) is False


def test_lock_blocks_a_second_supervisor(tmp_path: Path):
    paths = make_paths(tmp_path)
    acquire_run_lock(paths, "run1")
    assert run_lock_pid(paths) == os.getpid()
    assert run_is_active(paths) is True

    with pytest.raises(RuntimeError, match="already active"):
        acquire_run_lock(paths, "run1")

    release_run_lock(paths)
    assert run_lock_pid(paths) is None
    acquire_run_lock(paths, "run1")
    release_run_lock(paths)


def test_stale_lock_is_replaced(tmp_path: Path):
    paths = make_paths(tmp_path)
    (paths.root / "run.lock").write_text("999999999\nold\nrun1\n", encoding="utf-8")
    assert run_is_active(paths) is False
    acquire_run_lock(paths, "run1")
    assert run_lock_pid(paths) == os.getpid()
    release_run_lock(paths)


def test_cli_start_refuses_active_run(tmp_path: Path, capsys):
    from waker.cli import main

    paths = make_paths(tmp_path)
    acquire_run_lock(paths, "run1")
    try:
        code = main(["start", "--resume", "run1", "--repo", str(tmp_path)])
        assert code == 2
        assert "đang chạy" in capsys.readouterr().err
    finally:
        release_run_lock(paths)
