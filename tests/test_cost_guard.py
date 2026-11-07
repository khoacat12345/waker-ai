from __future__ import annotations

import json
from pathlib import Path

from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, Task, TurnResult
from waker.state import RunPaths


class CostlyIdleAdapter:
    """Never writes anything; burns money every turn."""

    name = "costly"

    def __init__(self, cost: float) -> None:
        self.cost = cost

    def run_turn(self, prompt, ctx):
        return TurnResult(exit_code=0, output="working", duration=0.01, cost_usd=self.cost)


class CostlyWinnerAdapter:
    """Finishes the job while spending money; success must win over the guard."""

    name = "winner"

    def __init__(self, cost: float) -> None:
        self.cost = cost

    def run_turn(self, prompt, ctx):
        repo = Path(ctx.repo)
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "a.txt").write_text("a", encoding="utf-8")
        (repo / "src" / "b.txt").write_text("b", encoding="utf-8")
        return TurnResult(
            exit_code=0,
            output="All tasks completed",
            duration=0.01,
            cost_usd=self.cost,
        )


def labels(repo: Path, run_id: str) -> list[str]:
    path = RunPaths(repo, run_id).events
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("t") == "diagnose":
            found.append(record["label"])
    return found


def base_config(repo: Path, tasks: list[Task], max_cost: float) -> EngineConfig:
    return EngineConfig(
        repo=str(repo),
        tasks=tasks,
        agent_command="stub",
        test_command=None,
        max_kicks=3,
        turn_timeout=30,
        verify_timeout=30,
        max_cost_usd=max_cost,
        freeze_probe=False,
    )


def test_cost_guard_stops_the_run(repo: Path, tasks: list[Task]):
    result = Engine(base_config(repo, tasks, 0.5), CostlyIdleAdapter(0.6)).run()

    assert result.diagnosis is Diagnosis.BREAKER
    assert result.exit_code == 2
    assert result.kicks == 0
    assert labels(repo, result.run_id) == ["BREAKER"]


def test_done_wins_over_cost_guard(repo: Path, tasks: list[Task]):
    result = Engine(base_config(repo, tasks, 0.5), CostlyWinnerAdapter(0.9)).run()

    assert result.diagnosis is Diagnosis.DONE
