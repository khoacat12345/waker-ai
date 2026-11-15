from __future__ import annotations

import json
from pathlib import Path

from conftest import exists_cmd, py

from waker.detector import diagnose
from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, Observation, Task, TurnResult
from waker.state import RunPaths


class SlopThenFixAdapter:
    """Writes raw eval() slop first, then repairs it after the wake prompt."""

    name = "slop-then-fix"

    def __init__(self) -> None:
        self.turns = 0

    def run_turn(self, prompt, ctx):
        self.turns += 1
        repo = Path(ctx.repo)
        (repo / "src").mkdir(exist_ok=True)
        if self.turns == 1:
            source = 'def run():\n    return eval("1 + 1")\n'
        else:
            source = "def run():\n    return 2\n"
        (repo / "src" / "helper.py").write_text(source, encoding="utf-8")
        return TurnResult(exit_code=0, output="All tasks completed", duration=0.01)


class EvalAlwaysAdapter:
    name = "eval-always"

    def run_turn(self, prompt, ctx):
        repo = Path(ctx.repo)
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "helper.py").write_text(
            'def run():\n    return eval("1 + 1")\n', encoding="utf-8"
        )
        return TurnResult(exit_code=0, output="All tasks completed", duration=0.01)


def labels(repo: Path, run_id: str) -> list[str]:
    path = RunPaths(repo, run_id).events
    found: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("t") == "diagnose":
            found.append(record["label"])
    return found


def make_task() -> Task:
    return Task(
        id="T1",
        desc="write src/helper.py",
        scope=["src/helper.py"],
        verify=exists_cmd("src/helper.py"),
    )


def make_config(repo: Path, adapter: str = "stub", **kwargs) -> EngineConfig:
    defaults = dict(
        repo=str(repo),
        tasks=[make_task()],
        agent_command=adapter,
        test_command=py("import sys; sys.exit(0)"),
        max_kicks=2,
        turn_timeout=30,
        verify_timeout=30,
        freeze_probe=False,
    )
    defaults.update(kwargs)
    return EngineConfig(**defaults)


def test_done_is_refused_while_a_blocking_slop_finding_exists() -> None:
    observation = Observation(
        all_tasks_done=True,
        has_test=True,
        test_exit=0,
        integrity_ok=True,
        hidden_ok=True,
        slop_ok=False,
        slop_blocking=True,
        slop_findings=["ERROR SEC001 src/helper.py:2 - eval()"],
    )
    assert diagnose(observation) is Diagnosis.SLOP


def test_engine_kicks_eval_and_wakes_with_ast_evidence(repo: Path) -> None:
    result = Engine(make_config(repo, "slop-then-fix"), SlopThenFixAdapter()).run()

    assert result.diagnosis is Diagnosis.DONE
    assert result.kicks == 1
    assert labels(repo, result.run_id) == ["SLOP", "DONE"]

    prompt = (RunPaths(repo, result.run_id).root / "kick-1" / "prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "reason: SLOP" in prompt
    assert "SEC001" in prompt
    assert "src/helper.py:2" in prompt
    assert "eval" in prompt
    assert "Fix:" in prompt

    kick0 = json.loads(
        (RunPaths(repo, result.run_id).root / "kick-0" / "result.json").read_text(
            encoding="utf-8"
        )
    )
    assert kick0["slop"]["blocking"] is True
    assert any("SEC001" in item for item in kick0["slop"]["findings"])


def test_repeated_slop_hits_the_kick_limit(repo: Path) -> None:
    result = Engine(
        make_config(repo, "eval-always", max_kicks=1), EvalAlwaysAdapter()
    ).run()

    assert result.diagnosis is Diagnosis.BREAKER
    assert result.exit_code == 2
    assert labels(repo, result.run_id) == ["SLOP", "BREAKER"]


def test_legacy_mode_can_disable_the_watchdog(repo: Path) -> None:
    result = Engine(
        make_config(repo, "eval-always", anti_slop=False), EvalAlwaysAdapter()
    ).run()

    assert result.diagnosis is Diagnosis.DONE
    assert labels(repo, result.run_id) == ["DONE"]
