from __future__ import annotations

from pathlib import Path

from waker.state import (
    RunState,
    checkpoint,
    git_head,
    latest_run,
    new_ledger,
    read_json,
    set_task,
    write_json_atomic,
)


def test_json_roundtrip(tmp_path: Path):
    path = tmp_path / "a.json"
    write_json_atomic(path, {"x": 1})
    assert read_json(path) == {"x": 1}


def test_run_state_roundtrip(tmp_path: Path):
    state = RunState(
        run_id="abcd",
        repo=str(tmp_path),
        prompt="p",
        agent_command="true",
        test_command=None,
        baseline_commit="",
        baseline_test_hash="",
        test_globs=[],
        started_at="now",
        tasks=[],
        session_id="ses_x",
    )
    path = tmp_path / "run.json"
    state.save(path)
    loaded = RunState.load(path)
    assert loaded.run_id == "abcd"
    assert loaded.session_id == "ses_x"


def test_checkpoint_commits_and_noops(repo: Path):
    (repo / "x.txt").write_text("x", encoding="utf-8")
    commit = checkpoint(repo, "waker: test")
    assert commit
    assert commit == git_head(repo)
    assert checkpoint(repo, "again") is None


def test_latest_run_picks_newest(tmp_path: Path):
    for name in ("aaaa", "bbbb"):
        root = tmp_path / ".waker" / "runs" / name
        root.mkdir(parents=True)
        (root / "run.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".waker" / "runs" / "bbbb" / "run.json").touch()
    assert latest_run(tmp_path) in {"aaaa", "bbbb"}


def test_ledger_status_transitions():
    from waker.models import Task

    ledger = new_ledger([Task(id="T1", desc="x")])
    assert ledger["tasks"]["T1"]["status"] == "pending"
    set_task(ledger, "T1", "done", {"files": ["a"]}, 0)
    assert ledger["tasks"]["T1"]["status"] == "done"
    assert ledger["tasks"]["T1"]["since_kick"] == 0
    set_task(ledger, "T1", "failed", None, 1)
    assert ledger["tasks"]["T1"]["since_kick"] == 1
