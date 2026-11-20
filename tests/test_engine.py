from __future__ import annotations

import json
import time
from pathlib import Path

from conftest import exists_cmd, fake_agent, py

from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, PhaseSpec, Task
from waker.state import RunPaths, RunState


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


def test_phase_elapsed_for_includes_active_phase_clock():
    state = RunState(
        run_id="phase-time",
        repo=".",
        prompt="",
        agent_command="true",
        test_command=None,
        baseline_commit="",
        baseline_test_hash="",
        test_globs=[],
        started_at="now",
        tasks=[],
        session_id="ses_phase",
        phase_id="P1",
        phase_started_ts=100.0,
        phase_elapsed={"P1": 5.0, "P2": 7.0},
    )
    assert state.phase_elapsed_for("P1", now=110.0) == 15.0
    assert state.phase_elapsed_for("P2", now=110.0) == 7.0


def test_phase_budget_timeout_stops_before_next_phase(repo: Path, tasks: list[Task]):
    for task in tasks:
        task.phase = "P1"
    phases = [
        PhaseSpec("P1", "Core", "0.001s"),
        PhaseSpec("P2", "Docs", "1h"),
    ]
    result = Engine(
        config(repo, tasks, "lazy", max_kicks=3, phases=phases)
    ).run()

    assert result.diagnosis is Diagnosis.TIMEOUT
    assert result.exit_code == 7
    assert "TIMEOUT" in labels(repo, result.run_id)
    state = RunState.load(RunPaths(repo, result.run_id).state)
    assert state.phase_id == "P1"
    assert state.phase_status == "timeout"
    assert "T2" in (state.phase_timeout_reason or "")
    timeout_event = next(
        record for record in events(repo, result.run_id) if record.get("t") == "phase_timeout"
    )
    assert timeout_event["phase"] == "P1"
    assert "T2" in timeout_event["unfinished"]
    assert not any(
        record.get("t") == "turn_start" and record.get("kick") == 1
        for record in events(repo, result.run_id)
    )


def test_phase_budget_warning_is_emitted_and_injected(repo: Path, tasks: list[Task]):
    for task in tasks:
        task.phase = "P1"
    phases = [PhaseSpec("P1", "Core", "100s")]
    engine = Engine(config(repo, tasks, "lazy", max_kicks=2, phases=phases))
    engine.prepare()
    assert engine.state is not None
    engine.state.phase_started_ts = time.time() - 85
    result = engine.run()

    assert result.diagnosis is Diagnosis.DONE
    warnings = [
        record for record in events(repo, result.run_id) if record.get("t") == "budget_warning"
    ]
    assert warnings
    assert warnings[0]["phase"] == "P1"
    prompt = RunPaths(repo, result.run_id).kick_prompt(1).read_text(encoding="utf-8")
    assert "PHASE BUDGET WARNING" in prompt


def test_resume_extend_reopens_timed_out_phase(repo: Path, tasks: list[Task]):
    for task in tasks:
        task.phase = "P1"
    phases = [
        PhaseSpec("P1", "Core", "0.001s"),
        PhaseSpec("P2", "Docs", "1h"),
    ]
    first = Engine(config(repo, tasks, "lazy", max_kicks=3, phases=phases)).run()
    assert first.diagnosis is Diagnosis.TIMEOUT
    before = RunState.load(RunPaths(repo, first.run_id).state)
    contract_hash = before.contract_hash
    old_budget = next(
        phase.budget_seconds for phase in phases if phase.id == "P1"
    )
    old_wall = before.max_wall_clock

    resumed = Engine.from_run(repo, first.run_id, extend_seconds=10)
    second = resumed.run()

    assert second.diagnosis is Diagnosis.DONE
    state = RunState.load(RunPaths(repo, first.run_id).state)
    assert state.phase_status == "completed"
    assert state.contract_hash == contract_hash
    assert state.max_wall_clock == old_wall + 10
    phase = next(item for item in state.phases if item["id"] == "P1")
    assert phase["budget"] == f"{old_budget + 10:.3f}s"
    assert state.phase_elapsed["P1"] > old_budget
    extended = next(
        record for record in events(repo, first.run_id) if record.get("t") == "budget_extended"
    )
    assert extended["phase"] == "P1"
    assert extended["extend_seconds"] == 10
    assert extended["approved_by"] == "user"


def test_turn_timeout_is_reported_as_timeout(repo: Path, tasks: list[Task]):
    result = Engine(
        config(
            repo,
            tasks,
            "freeze",
            max_kicks=1,
            turn_timeout=0.3,
            freeze_after=10.0,
            freeze_probe=False,
        )
    ).run()

    assert result.diagnosis is Diagnosis.TIMEOUT
    assert result.exit_code == 7
    assert "TIMEOUT" in labels(repo, result.run_id)
    turn_end = next(
        record for record in events(repo, result.run_id) if record.get("t") == "turn_end"
    )
    assert turn_end["timed_out"] is True
    assert turn_end["turn_timeout"] == 0.3


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
