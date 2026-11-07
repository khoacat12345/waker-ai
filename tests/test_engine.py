from __future__ import annotations

import json
from pathlib import Path

from conftest import exists_cmd, fake_agent

from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, Task
from waker.state import RunPaths


def labels(repo: Path, run_id: str) -> list[str]:
    path = RunPaths(repo, run_id).events
    found: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("t") == "diagnose":
            found.append(record["label"])
    return found


def events(repo: Path, run_id: str) -> list[dict]:
    path = RunPaths(repo, run_id).events
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def config(repo: Path, tasks: list[Task], mode: str, **kwargs) -> EngineConfig:
    defaults = dict(
        max_kicks=3,
        turn_timeout=30.0,
        verify_timeout=30.0,
        freeze_after=10.0,
        alive_threshold=0.05,
        max_wall_clock=3600.0,
    )
    defaults.update(kwargs)
    return EngineConfig(
        repo=str(repo),
        tasks=tasks,
        agent_command=fake_agent(mode),
        test_command=exists_cmd("src/a.txt", "src/b.txt"),
        **defaults,
    )


def test_lazy_agent_is_kicked_until_done(repo: Path, tasks: list[Task]):
    result = Engine(config(repo, tasks, "lazy")).run()

    assert result.diagnosis is Diagnosis.DONE
    assert result.exit_code == 0
    assert result.kicks == 1
    assert labels(repo, result.run_id) == ["PARTIAL", "DONE"]


def test_liar_agent_never_gets_a_false_green(repo: Path, tasks: list[Task]):
    result = Engine(config(repo, tasks, "liar", max_kicks=2)).run()

    assert result.diagnosis is Diagnosis.BREAKER
    assert result.exit_code == 2
    assert "FALSE_DONE" in labels(repo, result.run_id)


def test_tamper_agent_is_reverted_and_never_wins(repo: Path, tasks: list[Task]):
    result = Engine(config(repo, tasks, "tamper", max_kicks=1)).run()

    assert result.diagnosis is Diagnosis.BREAKER
    assert "TAMPER" in labels(repo, result.run_id)
    assert any(record.get("t") == "tamper_revert" for record in events(repo, result.run_id))
    # The exam must be restored even on the final (terminal) turn.
    restored = (repo / "tests" / "test_all.py").read_text(encoding="utf-8")
    assert "assert False" in restored


def test_frozen_agent_is_detected(repo: Path, tasks: list[Task]):
    result = Engine(
        config(repo, tasks, "freeze", max_kicks=1, turn_timeout=0.4, freeze_after=0.1)
    ).run()

    assert result.diagnosis is Diagnosis.BREAKER
    assert "FROZEN" in labels(repo, result.run_id)


def test_blocked_agent_stops_without_burning_kicks(repo: Path, tasks: list[Task]):
    result = Engine(config(repo, tasks, "blocked")).run()

    assert result.diagnosis is Diagnosis.BLOCKED
    assert result.exit_code == 3
    assert result.kicks == 0


def test_good_agent_finishes_in_one_turn(repo: Path, tasks: list[Task]):
    result = Engine(config(repo, tasks, "good")).run()

    assert result.diagnosis is Diagnosis.DONE
    assert result.kicks == 0
    path = RunPaths(repo, result.run_id)
    assert path.report.exists()
    assert (path.root / "kick-0" / "prompt.txt").exists()
    assert (path.root / "kick-0" / "result.json").exists()


def test_tampered_contract_blocks_the_run(tmp_path: Path):
    from waker import planner

    repo = tmp_path / "r"
    repo.mkdir()
    contract = repo / "tasks.yaml"
    contract.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    desc: x\n"
        "    scope: [\"src/**\"]\n"
        "    verify: \"true\"\n",
        encoding="utf-8",
    )
    tasks = planner.load_tasks(contract)
    issues = planner.lint_tasks(tasks)
    assert planner.has_errors(issues)
