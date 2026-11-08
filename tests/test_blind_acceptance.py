from __future__ import annotations

import json
from pathlib import Path

from conftest import exists_cmd, py_script

from waker.cli import main
from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, Task, TurnResult
from waker.planner import PlanBundle, write_tasks
from waker.state import RunPaths
from waker.vault import Vault

FAKE = Path(__file__).parent / "fake_blind_agent.py"

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


class TamperAdapter(ValueAdapter):
    def __init__(self, vault: Vault) -> None:
        super().__init__(42)
        self.vault = vault

    def run_turn(self, prompt, ctx):
        result = super().run_turn(prompt, ctx)
        target = self.vault.suite_dir("core") / "test_hidden.py"
        target.write_text(
            target.read_text(encoding="utf-8") + "\n# tampered\n",
            encoding="utf-8",
        )
        return result


def make_vault(tmp_path: Path, repo: Path) -> Vault:
    source = tmp_path / "test_hidden.py"
    source.write_text(HIDDEN_TEST, encoding="utf-8")
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    vault.add_suite(
        "core", [str(source)], task="T1", baseline="red", timeout=30, leak="message"
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


def test_prompt_and_report_never_leak_vault_or_source(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    result = Engine(make_config(tmp_path, repo, vault), ValueAdapter(42)).run()
    assert result.diagnosis is Diagnosis.DONE

    paths = RunPaths(repo, result.run_id)
    prompt = (paths.root / "kick-0" / "prompt.txt").read_text(encoding="utf-8")
    for secret in (vault.vault_id, str(vault.path), "test_hidden.py", "def test_value"):
        assert secret not in prompt

    ledger = paths.ledger.read_text(encoding="utf-8")
    report = paths.report.read_text(encoding="utf-8")
    for text in (ledger, report):
        assert "def test_value" not in text
        assert "import pytest" not in text
        assert "test_hidden.py" not in text


def test_public_smoke_pass_but_hidden_fail(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    result = Engine(make_config(tmp_path, repo, vault), ValueAdapter(0)).run()
    assert result.diagnosis is Diagnosis.BREAKER

    paths = RunPaths(repo, result.run_id)
    events = [
        json.loads(line)
        for line in paths.events.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event.get("label") == "HIDDEN_FAIL" for event in events)

    wake = (paths.root / "kick-1" / "prompt.txt").read_text(encoding="utf-8")
    assert "hidden://core/test_1" in wake
    assert "def test_value" not in wake
    assert "test_hidden.py" not in wake
    assert str(vault.path) not in wake


def test_vault_tamper_stops_the_run(repo: Path, tmp_path: Path):
    vault = make_vault(tmp_path, repo)
    result = Engine(
        make_config(tmp_path, repo, vault), TamperAdapter(vault)
    ).run()
    assert result.diagnosis is Diagnosis.VAULT_TAMPER
    assert result.exit_code == 5


def test_current_hash_detects_file_change(tmp_path: Path, repo: Path):
    vault = make_vault(tmp_path, repo)
    before = vault.current_hash()
    target = vault.suite_dir("core") / "test_hidden.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    assert vault.current_hash() != before


def test_cli_blind_run_end_to_end(repo: Path, tmp_path: Path, capsys):
    vault = make_vault(tmp_path, repo)
    contract = tmp_path / "tasks.yaml"
    write_tasks(contract, PlanBundle(tasks=[make_task()]))
    agent = py_script(FAKE, "--mode", "good")

    code = main(
        [
            "run",
            "--repo",
            str(repo),
            "--tasks",
            str(contract),
            "--test",
            exists_cmd("src/a.py"),
            "--agent",
            agent,
            "--adapter",
            "generic",
            "--vault",
            vault.vault_id,
            "--vault-dir",
            str(tmp_path / "vaults"),
            "--max-kicks",
            "1",
        ]
    )
    assert code == 0
    assert "VALUE = 42" in (repo / "src" / "a.py").read_text(encoding="utf-8")
    capsys.readouterr()
