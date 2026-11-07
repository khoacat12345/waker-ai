from __future__ import annotations

import json
from pathlib import Path

from conftest import exists_cmd, fake_agent, py

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


def test_verify_cache_avoids_rerunning_unchanged_tasks(repo: Path):
    t1 = Task(
        id="T1",
        desc="write a",
        scope=["src/a.txt"],
        verify=py(
            "import os,sys; open('calls_t1.txt','a').write('x'); "
            "sys.exit(0 if os.path.exists('src/a.txt') else 1)"
        ),
    )
    t2 = Task(
        id="T2",
        desc="write b",
        scope=["src/b.txt"],
        verify=py(
            "import os,sys; open('calls_t2.txt','a').write('x'); "
            "sys.exit(0 if os.path.exists('src/b.txt') else 1)"
        ),
    )
    config = EngineConfig(
        repo=str(repo),
        tasks=[t1, t2],
        agent_command=fake_agent("lazy"),
        test_command=exists_cmd("src/a.txt", "src/b.txt"),
        max_kicks=3,
        turn_timeout=30,
        verify_timeout=30,
        freeze_probe=False,
    )
    result = Engine(config).run()

    assert result.diagnosis is Diagnosis.DONE
    assert len((repo / "calls_t1.txt").read_text(encoding="utf-8")) == 1
    assert len((repo / "calls_t2.txt").read_text(encoding="utf-8")) == 1


def test_full_suite_is_skipped_until_candidate(repo: Path):
    suite = repo / "suite.txt"
    test_command = py(
        "import os,sys; open('suite.txt','a').write('x'); "
        "sys.exit(0 if os.path.exists('src/a.txt') and os.path.exists('src/b.txt') else 1)"
    )
    tasks = [
        Task(id="T1", desc="write a", scope=["src/a.txt"], verify=exists_cmd("src/a.txt")),
        Task(id="T2", desc="write b", scope=["src/b.txt"], verify=exists_cmd("src/b.txt")),
    ]
    config = EngineConfig(
        repo=str(repo),
        tasks=tasks,
        agent_command=fake_agent("lazy"),
        test_command=test_command,
        max_kicks=3,
        turn_timeout=30,
        verify_timeout=30,
        freeze_probe=False,
    )
    result = Engine(config).run()

    assert result.diagnosis is Diagnosis.DONE
    # one baseline run at prepare + one at the candidate-DONE boundary
    assert len(suite.read_text(encoding="utf-8")) == 2
    kick0 = json.loads(
        (RunPaths(repo, result.run_id).root / "kick-0" / "result.json").read_text(
            encoding="utf-8"
        )
    )
    assert kick0["test_skipped"] is True
