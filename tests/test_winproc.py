from __future__ import annotations

import sys
from pathlib import Path

from waker import doctor, evidence, opencode_events, planner, process, state, winproc
from waker.daemon import start_detached


class FakeCompleted:
    returncode = 0
    stdout = ""
    stderr = ""


def test_no_window_flag_value():
    if sys.platform == "win32":
        assert winproc.NO_WINDOW == 0x08000000
    else:
        assert winproc.NO_WINDOW == 0


def test_wrapper_run_and_popen_add_flag(monkeypatch):
    calls: list[dict] = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(winproc.subprocess, "run", fake_run)
    winproc.run(["echo", "ok"])
    assert calls[0]["creationflags"] & winproc.NO_WINDOW

    popen_calls: list[dict] = []

    class FakePopen:
        pid = 1234

        def __init__(self, *args, **kwargs):
            popen_calls.append(kwargs)

    monkeypatch.setattr(winproc.subprocess, "Popen", FakePopen)
    winproc.popen(["echo", "ok"], creationflags=0x200)
    assert popen_calls[0]["creationflags"] & winproc.NO_WINDOW
    assert popen_calls[0]["creationflags"] & 0x200


def test_patched_call_sites_pass_no_window(monkeypatch):
    calls: list[dict] = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(winproc.subprocess, "run", fake_run)

    evidence.run_command("echo ok", ".", timeout=5)
    state.git_head(".")
    process.kill_tree(999_999_999)
    planner._repo_files(".")
    opencode_events.read_session_usage("ses_x", ".", binary="opencode")
    doctor._version("git", "git")

    assert calls
    assert all(call["creationflags"] & winproc.NO_WINDOW for call in calls)


def test_daemon_start_detached_hides_window(tmp_path: Path, monkeypatch):
    captured: list[dict] = []

    class FakePopen:
        pid = 4321

        def __init__(self, *args, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(winproc.subprocess, "Popen", FakePopen)
    record = start_detached(tmp_path, ["--tasks", "tasks.yaml", "--agent", "true"], "run1")

    assert record["pid"] == 4321
    assert captured
    assert captured[0]["creationflags"] & winproc.NO_WINDOW
    if sys.platform == "win32":
        assert captured[0]["creationflags"] & 0x08000000


def test_no_direct_subprocess_calls_in_src():
    root = Path(__file__).resolve().parents[1] / "src" / "waker"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "winproc.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "subprocess.run(" in text or "subprocess.Popen(" in text:
            offenders.append(str(path.relative_to(root)))
    assert not offenders, offenders
