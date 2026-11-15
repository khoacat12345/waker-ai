from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import exists_cmd, py

from waker.engine import Engine, EngineConfig
from waker.gate import (
    AntiSlopConfig,
    baseline_path,
    load_baseline,
    scan_paths,
    write_baseline,
)
from waker.models import Diagnosis, Task, TurnResult
from waker.revert import restore_files
from waker.state import RunPaths, read_json
from waker.tui import (
    build_quality_bar,
    build_quality_panel,
    quality_from_ledger,
    quality_line,
)
from waker.ui import render_markdown


def write_file(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scan(root: Path, *, use_baseline: bool, config: AntiSlopConfig | None = None):
    return scan_paths(
        root,
        config=config or AntiSlopConfig(),
        changed_only=False,
        baseline_ref="",
        use_baseline=use_baseline,
    )


def test_baseline_roundtrip_suppresses_legacy_but_not_new(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "legacy.py",
        "def parse(x):\n    return x\n\ndef parse(y):\n    return y\n",
    )
    config = AntiSlopConfig()
    first = scan(tmp_path, use_baseline=False, config=config)
    assert first.errors_count > 0

    target = baseline_path(tmp_path, config)
    assert target is not None
    write_baseline(target, first.findings)
    assert load_baseline(target)
    assert json.loads(target.read_text(encoding="utf-8"))["count"] == len(
        first.findings
    )

    second = scan(tmp_path, use_baseline=True, config=config)
    assert second.errors_count == 0
    assert second.score == 100
    assert second.baseline_suppressed > 0

    write_file(
        tmp_path,
        "new_bad.py",
        "def load(x):\n    return x\n\ndef load(y):\n    return y\n",
    )
    third = scan(tmp_path, use_baseline=True, config=config)
    assert third.errors_count >= 1
    assert any(finding.rule == "SLOP001" for finding in third.actionable)
    assert third.baseline_suppressed > 0


def test_baseline_cli_write_then_clean(tmp_path: Path, capsys) -> None:
    from waker.cli import main

    write_file(
        tmp_path,
        "bad.py",
        "def parse(x):\n    return x\n\ndef parse(y):\n    return y\n",
    )
    assert main(["audit", "--all", "--repo", str(tmp_path), "--write-baseline"]) == 0
    capsys.readouterr()
    assert (tmp_path / ".waker" / "anti-slop-baseline.json").exists()
    assert main(["audit", "--all", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Baseline:" in out
    assert "Cleanliness: 100/100" in out


def test_baseline_tracks_line_shifts_without_hiding_new_same_file_findings(
    tmp_path: Path,
) -> None:
    config = AntiSlopConfig(enable_core=False, enable_security=True)
    write_file(tmp_path, "legacy.py", 'VALUE = eval("1")\n')
    first = scan(tmp_path, use_baseline=False, config=config)
    assert first.errors_count == 1
    target = baseline_path(tmp_path, config)
    assert target is not None
    write_baseline(target, first.findings)

    write_file(tmp_path, "legacy.py", 'HEADER = 0\nVALUE = eval("1")\n')
    shifted = scan(tmp_path, use_baseline=True, config=config)
    assert shifted.errors_count == 0

    write_file(
        tmp_path,
        "legacy.py",
        'HEADER = 0\nVALUE = eval("1")\nSECOND = eval("2")\n',
    )
    new_one = scan(tmp_path, use_baseline=True, config=config)
    assert new_one.errors_count == 1
    assert new_one.baseline_suppressed >= 1


def test_restore_files_is_selective_and_removes_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@local"], check=False)
    write_file(repo, "src/evil.py", "VALUE = 0\n")
    write_file(repo, "src/good.py", "GOOD = 0\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=False)

    write_file(repo, "src/evil.py", 'VALUE = eval("1")\n')
    write_file(repo, "src/good.py", "GOOD = 1\n")
    write_file(repo, "src/untracked.py", 'VALUE = eval("1")\n')

    outcome = restore_files(repo, ["src/evil.py", "src/untracked.py"])
    assert outcome["restored"] == ["src/evil.py"]
    assert outcome["removed"] == ["src/untracked.py"]
    assert (repo / "src" / "evil.py").read_text(encoding="utf-8") == "VALUE = 0\n"
    assert (repo / "src" / "good.py").read_text(encoding="utf-8") == "GOOD = 1\n"
    assert not (repo / "src" / "untracked.py").exists()


class TouchLegacyAdapter:
    name = "touch-legacy"

    def run_turn(self, prompt, ctx):
        path = Path(ctx.repo) / "src" / "helper.py"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            path.read_text(encoding="utf-8") + "VALUE = 1\n", encoding="utf-8"
        )
        return TurnResult(exit_code=0, output="All tasks completed", duration=0.01)


class RevertAdapter:
    name = "revert"

    def __init__(self) -> None:
        self.turns = 0

    def run_turn(self, prompt, ctx):
        self.turns += 1
        repo = Path(ctx.repo)
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
        if self.turns == 1:
            source = 'VALUE = eval("1")\n'
        else:
            source = "VALUE = 2\n"
        (repo / "src" / "helper.py").write_text(source, encoding="utf-8")
        return TurnResult(exit_code=0, output="All tasks completed", duration=0.01)


class EvalAdapter:
    name = "eval"

    def run_turn(self, prompt, ctx):
        repo = Path(ctx.repo)
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "helper.py").write_text(
            'VALUE = eval("1")\n', encoding="utf-8"
        )
        return TurnResult(exit_code=0, output="All tasks completed", duration=0.01)


def engine_config(repo: Path, config: AntiSlopConfig, **kwargs) -> EngineConfig:
    defaults = dict(
        repo=str(repo),
        tasks=[
            Task(
                id="T1",
                desc="write helper",
                scope=["src/helper.py"],
                verify=exists_cmd("src/helper.py"),
            )
        ],
        agent_command="stub",
        test_command=py("import sys; sys.exit(0)"),
        max_kicks=2,
        turn_timeout=30,
        verify_timeout=30,
        freeze_probe=False,
        slop_config=config,
    )
    defaults.update(kwargs)
    return EngineConfig(**defaults)


def test_engine_run_baseline_ignores_preexisting_slop(repo: Path) -> None:
    write_file(repo, "src/helper.py", 'VALUE = eval("1")\n')
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "legacy"], check=False)

    config = AntiSlopConfig(enable_security=True)
    result = Engine(engine_config(repo, config), TouchLegacyAdapter()).run()

    assert result.diagnosis is Diagnosis.DONE
    ledger = read_json(RunPaths(repo, result.run_id).ledger)
    assert ledger["quality"]["errors"] == 0
    assert ledger["quality"]["suppressed"] >= 1


def test_engine_revert_restores_only_violating_file(repo: Path) -> None:
    write_file(repo, "src/helper.py", "VALUE = 0\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=False)

    config = AntiSlopConfig(enable_security=True, on_violation="revert")
    result = Engine(engine_config(repo, config), RevertAdapter()).run()

    assert result.diagnosis is Diagnosis.DONE
    events = [
        json.loads(line)
        for line in RunPaths(repo, result.run_id).events.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    reverts = [event for event in events if event.get("t") == "slop_revert"]
    assert reverts
    assert "src/helper.py" in reverts[0]["restored"]
    assert (repo / "src" / "other.py").read_text(encoding="utf-8") == "OTHER = 1\n"
    assert (repo / "src" / "helper.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_engine_abort_policy_terminates_with_exit_six(repo: Path) -> None:
    config = AntiSlopConfig(enable_security=True, on_violation="abort")
    result = Engine(engine_config(repo, config), EvalAdapter()).run()

    assert result.diagnosis is Diagnosis.SLOP
    assert result.exit_code == 6
    assert result.kicks == 0
    events = [
        json.loads(line)
        for line in RunPaths(repo, result.run_id).events.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert any(event.get("t") == "slop_abort" for event in events)


def test_run_cli_exposes_baseline_switch() -> None:
    from waker.cli import build_parser

    parser = build_parser()
    enabled = parser.parse_args(["run", "--prompt", "x"])
    disabled = parser.parse_args(["run", "--prompt", "x", "--no-baseline"])
    assert enabled.slop_baseline is True
    assert disabled.slop_baseline is False


def test_tui_quality_status_and_markdown() -> None:
    ledger = {
        "quality": {
            "score": 100,
            "grade": "A",
            "errors": 0,
            "warnings": 0,
            "suppressed": 2,
        },
        "tasks": {},
        "test": {"exit_code": 0},
    }
    status = quality_from_ledger(ledger)
    assert status.score == 100
    assert status.display_grade == "A+"
    line = quality_line(ledger)
    assert "100/100" in line
    assert "Grade A+" in line
    assert "0 errors" in line
    assert "0 warnings" in line
    assert "2 legacy suppressed" in line
    assert build_quality_bar(ledger).plain == line
    assert build_quality_panel(ledger) is not None

    state = type(
        "State",
        (),
        {
            "run_id": "r1",
            "elapsed": 0.0,
            "kicks": 0,
            "max_kicks": 5,
            "cost_usd": 0.0,
            "task_objects": lambda self: [],
            "diagnosis": None,
            "status": "running",
        },
    )()
    markdown = render_markdown(state, ledger)
    assert "Cleanliness: 100/100" in markdown
