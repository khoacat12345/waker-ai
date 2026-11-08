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
    text = target.read_text(encoding="utf-8")
    assert "waker" in text.lower()
    assert "waker watch" in text
    assert "Đã bật chạy ngầm" in text
    capsys.readouterr()


def test_cli_setup_explicit_provider(tmp_path: Path, capsys):
    code = main(["setup", "--for", "opencode", "--dir", str(tmp_path), "--local"])
    assert code == 0
    assert (tmp_path / ".opencode" / "skills" / "waker" / "SKILL.md").exists()
    out = capsys.readouterr().out
    assert "waker watch" in out
    assert "tiến độ" in out


def test_cli_setup_auto_detects(tmp_path: Path, monkeypatch, capsys):
    from waker.doctor import ToolReport

    monkeypatch.setattr(
        "waker.doctor.detect_tools",
        lambda: [ToolReport("opencode", True, "x", "1.0", "T1", "test")],
    )
    code = main(["setup", "--dir", str(tmp_path), "--local"])
    assert code == 0
    assert (tmp_path / ".opencode" / "skills" / "waker" / "SKILL.md").exists()
    capsys.readouterr()



def test_cli_doctor_json(capsys):
    code = main(["doctor", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    assert '"environment"' in out
    assert '"tools"' in out


def test_cli_dashboard_static(repo: Path, tasks: list[Task], tmp_path: Path, capsys):
    _run_good(repo, tasks)
    capsys.readouterr()
    target = tmp_path / "dash.html"
    code = main(["dashboard", "--repo", str(repo), "--out", str(target)])
    assert code == 0
    assert target.exists()
    assert "waker" in target.read_text(encoding="utf-8").lower()
    capsys.readouterr()



def test_cli_plan_via_opencode(tmp_path: Path, repo: Path, monkeypatch, capsys):
    from waker.models import PlanBundle, Task

    monkeypatch.setattr(
        "waker.llm_plan.generate_contract",
        lambda text, repo_path, model=None, binary=None: PlanBundle(
            tasks=[
                Task(
                    id="T1",
                    desc="auth",
                    scope=["src/auth/**"],
                    verify="pytest tests/auth -q",
                )
            ]
        ),
    )
    out = tmp_path / "tasks.yaml"
    code = main(
        [
            "plan",
            "--via",
            "opencode",
            "--prompt",
            "làm auth",
            "--out",
            str(out),
            "--repo",
            str(repo),
        ]
    )
    assert code == 0
    assert "T1" in out.read_text(encoding="utf-8")
    capsys.readouterr()


def test_cli_detect_json(repo: Path, capsys):
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    code = main(["detect", "--repo", str(repo), "--json"])
    assert code == 0
    out = capsys.readouterr().out
    assert "pytest -q" in out


def test_cli_resume_after_breaker(repo: Path, capsys):
    from conftest import exists_cmd, fake_agent
    from waker.models import PlanBundle, Task
    from waker.planner import write_tasks
    from waker.state import latest_run

    contract = repo / "tasks.yaml"
    write_tasks(
        contract,
        PlanBundle(
            tasks=[
                Task(id="T1", desc="write a", scope=["src/a.txt"], verify=exists_cmd("src/a.txt")),
                Task(id="T2", desc="write b", scope=["src/b.txt"], verify=exists_cmd("src/b.txt")),
            ]
        ),
    )
    test_cmd = exists_cmd("src/a.txt", "src/b.txt")
    first = main(
        [
            "run",
            "--repo",
            str(repo),
            "--tasks",
            str(contract),
            "--test",
            test_cmd,
            "--agent",
            fake_agent("lazy"),
            "--adapter",
            "generic",
            "--max-kicks",
            "0",
        ]
    )
    assert first == 2
    run_id = latest_run(repo)
    assert run_id
    capsys.readouterr()

    second = main(["run", "--resume", run_id, "--repo", str(repo)])
    assert second == 0
    assert (repo / "src" / "b.txt").exists()



def test_cli_plan_warns_on_prose_prompt(tmp_path: Path, repo: Path, capsys):
    prompt = "\n".join(
        [
            "Dòng một phê duyệt",
            "Dòng hai phê duyệt",
            "Dòng ba phê duyệt",
            "Dòng bốn phê duyệt",
            "Dòng năm phê duyệt",
            "Dòng sáu phê duyệt",
        ]
    )
    main(
        [
            "plan",
            "--prompt",
            prompt,
            "--out",
            str(tmp_path / "tasks.yaml"),
            "--repo",
            str(repo),
        ]
    )
    captured = capsys.readouterr()
    assert "Gợi ý" in captured.err
    assert "--via opencode" in captured.err



def test_cli_start_accepts_detach_flag(capsys):
    from waker.cli import build_parser, cmd_start

    args = build_parser().parse_args(
        ["start", "--detach", "--tasks", "tasks.yaml", "--agent", "true"]
    )
    assert args.detach is True
    assert args.func is cmd_start


def test_hidden_summary_in_wake_prompt():
    from waker.injector import build_wake_prompt
    from waker.models import Diagnosis

    prompt = build_wake_prompt(
        Diagnosis.HIDDEN_FAIL,
        [Task(id="T1", desc="auth", scope=["src/auth/**"], verify="pytest -q")],
        [],
        {"tasks": {"T1": {"status": "failed"}}},
        [],
        None,
        1,
        5,
        hidden_summary=["auth: 1/2"],
        hidden_failures=["hidden://auth/test_1: AssertionError: boom"],
    )
    assert "Hidden suite" in prompt
    assert "hidden://auth/test_1" in prompt
    assert "def test_" not in prompt
