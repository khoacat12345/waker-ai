from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import exists_cmd

from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, Task, TurnResult
from waker.state import RunPaths
from waker.vault import Vault

HIDDEN_TEST = """
import pytest


def test_value():
    try:
        from src.a import VALUE
    except ImportError:
        pytest.fail("src.a is not implemented")
    assert VALUE == 42
"""


class ValueAdapter:
    name = "value"

    def __init__(self, value: int) -> None:
        self.value = value

    def run_turn(self, prompt, ctx):
        repo = Path(ctx.repo)
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "a.py").write_text(
            f"VALUE = {self.value}\n", encoding="utf-8"
        )
        return TurnResult(exit_code=0, output="done", duration=0.01)


def make_vault(tmp_path: Path, repo: Path) -> Vault:
    source = tmp_path / "test_hidden.py"
    source.write_text(HIDDEN_TEST, encoding="utf-8")
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    vault.add_suite(
        "core",
        [str(source)],
        task="T1",
        baseline="red",
        timeout=30,
        leak="message",
    )
    return vault


def make_task() -> Task:
    return Task(
        id="T1",
        desc="write src/a.py with VALUE=42",
        scope=["src/a.py"],
        verify=exists_cmd("src/a.py"),
        blind={"suite": "core", "baseline": "red", "timeout": 30, "leak": "message"},
    )


def make_config(tmp_path: Path, repo: Path, vault: Vault, max_kicks: int = 1) -> EngineConfig:
    return EngineConfig(
        repo=str(repo),
        tasks=[make_task()],
        agent_command="stub",
        test_command=exists_cmd("src/a.py"),
        max_kicks=max_kicks,
        turn_timeout=30,
        verify_timeout=30,
        freeze_probe=False,
        vault_id=vault.vault_id,
        vault_dir=str(tmp_path / "vaults"),
    )


def test_blind_run_passes_only_hidden_suite(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    result = Engine(make_config(tmp_path, repo, vault), ValueAdapter(42)).run()

    assert result.diagnosis is Diagnosis.DONE
    paths = RunPaths(repo, result.run_id)
    ledger = json.loads(paths.ledger.read_text(encoding="utf-8"))
    assert ledger["hidden"]["core"]["total"] == 1
    assert ledger["hidden"]["core"]["passed"] == 1
    assert ledger["hidden"]["core"]["failed"] == 0
    assert ledger["tasks"]["T1"]["status"] == "done"
    assert ledger["vault_tamper"] is False


def test_hidden_failure_blocks_done(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    result = Engine(make_config(tmp_path, repo, vault), ValueAdapter(0)).run()

    assert result.diagnosis is Diagnosis.BREAKER
    paths = RunPaths(repo, result.run_id)
    ledger = json.loads(paths.ledger.read_text(encoding="utf-8"))
    hidden = ledger["hidden"]["core"]
    assert hidden["failed"] == 1
    assert hidden["passed"] == 0
    assert ledger["tasks"]["T1"]["status"] == "failed"
    assert hidden["failures"][0].startswith("hidden://core/test_")
    assert "def test_value" not in json.dumps(hidden)
    assert "import pytest" not in json.dumps(hidden)


def test_blind_task_without_vault_fails_closed(repo: Path):
    config = EngineConfig(
        repo=str(repo),
        tasks=[make_task()],
        agent_command="stub",
        test_command=exists_cmd("src/a.py"),
        max_kicks=1,
        freeze_probe=False,
    )
    with pytest.raises(RuntimeError, match="--vault"):
        Engine(config, ValueAdapter(42)).run()


def test_prepare_validates_the_suite(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    Engine(make_config(tmp_path, repo, vault), ValueAdapter(42)).prepare()
    reloaded = Vault.load(vault.vault_id, base_dir=tmp_path / "vaults")
    assert reloaded.suites["core"]["validated_at"]
    assert reloaded.suites["core"]["tests"] == 1


def test_resume_keeps_vault(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    first = Engine(
        make_config(tmp_path, repo, vault, max_kicks=0), ValueAdapter(0)
    ).run()
    assert first.diagnosis is Diagnosis.BREAKER

    resumed = Engine.from_run(repo, first.run_id, adapter=ValueAdapter(42))
    second = resumed.run()
    assert second.diagnosis is Diagnosis.DONE
    assert resumed.state is not None
    assert resumed.state.vault_id == vault.vault_id


def test_cli_blind_requires_vault(repo: Path, tmp_path: Path, capsys):
    from waker.cli import main
    from waker.models import PlanBundle
    from waker.planner import write_tasks

    contract = tmp_path / "tasks.yaml"
    write_tasks(contract, PlanBundle(tasks=[make_task()]))
    code = main(
        [
            "run",
            "--repo",
            str(repo),
            "--tasks",
            str(contract),
            "--agent",
            "true",
        ]
    )
    assert code == 2
    assert "--vault" in capsys.readouterr().err
