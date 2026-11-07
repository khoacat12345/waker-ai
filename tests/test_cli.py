from __future__ import annotations

from pathlib import Path

from conftest import exists_cmd, fake_agent

from waker.cli import main
from waker.engine import Engine, EngineConfig
from waker.models import Task


def test_plan_writes_contract(tmp_path: Path, repo: Path, capsys):
    out = tmp_path / "tasks.yaml"
    code = main(
        [
            "plan",
            "--prompt",
            "Phase 1: auth, scope: src/**, verify: pytest tests/auth -q",
            "--out",
            str(out),
            "--repo",
            str(repo),
        ]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "T1" in text
    assert "pytest tests/auth -q" in text
    capsys.readouterr()


def test_lint_returns_two_on_errors(tmp_path: Path, repo: Path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: T1\n  desc: x\n", encoding="utf-8")
    code = main(["lint", "--tasks", str(bad), "--repo", str(repo)])
    assert code == 2
    assert "thiếu" in capsys.readouterr().out


def _run_good(repo: Path, tasks: list[Task]):
    config = EngineConfig(
        repo=str(repo),
        tasks=tasks,
        agent_command=fake_agent("good"),
        test_command=exists_cmd("src/a.txt", "src/b.txt"),
        max_kicks=1,
        turn_timeout=30,
        verify_timeout=30,
    )
    return Engine(config).run()


def test_status_json_after_run(repo: Path, tasks: list[Task], capsys):
    result = _run_good(repo, tasks)
    capsys.readouterr()
    code = main(["status", "--repo", str(repo), "--format", "json"])
    assert code == 0
    out = capsys.readouterr().out
    assert result.run_id in out
    assert '"DONE"' in out or "DONE" in out


def test_report_command(repo: Path, tasks: list[Task], capsys):
    _run_good(repo, tasks)
    capsys.readouterr()
    code = main(["report", "--repo", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert "#" in out or "waker" in out


def test_cli_survives_legacy_console_encoding(repo: Path, tasks: list[Task]):
    """Emoji output must not crash on a cp1252 pipe (legacy Windows console)."""
    import os
    import subprocess
    import sys

    _run_good(repo, tasks)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "waker", "status", "--repo", str(repo)],
        env=env,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"waker" in proc.stdout


def test_cli_install_skill(tmp_path: Path, capsys):
    code = main(["install-skill", "--for", "opencode", "--dir", str(tmp_path)])
    assert code == 0
    target = tmp_path / ".opencode" / "skills" / "waker" / "SKILL.md"
    assert target.exists()
    assert "waker" in target.read_text(encoding="utf-8").lower()
    capsys.readouterr()
