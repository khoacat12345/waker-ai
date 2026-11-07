from __future__ import annotations

import json
from pathlib import Path

from conftest import exists_cmd, fake_agent

from waker.engine import Engine, EngineConfig
from waker.models import Task
from waker.state import RunPaths


def make_tasks() -> list[Task]:
    return [
        Task(id="T1", desc="write a", scope=["src/a.txt"], verify=exists_cmd("src/a.txt")),
        Task(id="T2", desc="write b", scope=["src/b.txt"], verify=exists_cmd("src/b.txt")),
    ]


def test_resume_after_breaker_continues_the_run(repo: Path):
    config = EngineConfig(
        repo=str(repo),
        tasks=make_tasks(),
        agent_command=fake_agent("lazy"),
        test_command=exists_cmd("src/a.txt", "src/b.txt"),
        max_kicks=0,
        turn_timeout=30,
        verify_timeout=30,
        freeze_probe=False,
    )
    first = Engine(config).run()
    assert first.diagnosis.name == "BREAKER"
    assert first.kicks == 0
    assert not (repo / "src" / "b.txt").exists()

    resumed = Engine.from_run(repo, first.run_id, max_kicks=2)
    second = resumed.run()

    assert second.diagnosis.name == "DONE"
    assert second.run_id == first.run_id
    assert (repo / "src" / "b.txt").exists()

    paths = RunPaths(repo, first.run_id)
    generations = {path.name for path in paths.root.iterdir()}
    assert "kick-0-g1" in generations
    events = [
        json.loads(line)
        for line in paths.events.read_text(encoding="utf-8").splitlines()
    ]
    resumes = [event for event in events if event.get("t") == "resume"]
    assert resumes and resumes[0]["generation"] == 1
    assert resumes[0]["previous_status"] == "BREAKER"


def test_resume_missing_run_raises(repo: Path):
    import pytest

    with pytest.raises(FileNotFoundError):
        Engine.from_run(repo, "deadbeef")
