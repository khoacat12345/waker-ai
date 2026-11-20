from __future__ import annotations

from waker.models import Task
from waker.state import RunState
from waker.ui import (
    WakerViewModel,
    BeamPanel,
    DeckEvent,
    build_cyber_deck,
    fx_enabled,
    mini_line,
    open_watch_window,
    progress_bar,
    render_markdown,
)


def make_state(done: int) -> RunState:
    return RunState(
        run_id="7f3a",
        repo=".",
        prompt="",
        agent_command="true",
        test_command=None,
        baseline_commit="",
        baseline_test_hash="",
        test_globs=[],
        started_at="now",
        tasks=[
            Task(id="T1", desc="Auth", scope=["src/auth/**"]).to_dict(),
            Task(id="T2", desc="Payment", scope=["src/pay/**"]).to_dict(),
        ],
        session_id="ses_7f3a",
        kicks=done,
        max_kicks=5,
    )


def test_progress_bar():
    assert progress_bar(0, 4, 4) == "░░░░"
    assert progress_bar(2, 4, 4) == "██░░"
    assert progress_bar(4, 4, 4) == "████"
    assert progress_bar(0, 0, 3) == "░░░"


def test_markdown_contains_evidence_and_gate():
    ledger = {
        "tasks": {
            "T1": {
                "status": "done",
                "evidence": {"files": ["src/auth/guard.py"], "gate": "pass"},
            },
            "T2": {
                "status": "failed",
                "evidence": {"files": [], "gate": "fail", "message": "test_pay.py:31 KeyError"},
            },
        },
        "test": {"exit_code": 1, "failed": ["tests/test_pay.py::test_refund"]},
    }
    text = render_markdown(make_state(done=1), ledger)

    assert "run 7f3a" in text
    assert "1/2" in text
    assert "50%" in text
    assert "✅" in text
    assert "🔴" in text
    assert "src/auth/guard.py" in text
    assert "test_pay.py:31 KeyError" in text
    assert "tests/test_pay.py::test_refund" in text
    assert "|   | Task | Work | Evidence | Gate |" in text
    assert "Bằng chứng" not in text
    assert "chẩn đoán" not in text


def test_progress_ignores_constraints():
    state = make_state(done=1)
    ledger = {
        "tasks": {
            "T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}},
            "T2": {"status": "pending", "evidence": None},
            "C1": {"status": "done", "evidence": {"gate": "pass", "files": []}},
        },
        "test": {"exit_code": 0},
    }
    text = render_markdown(state, ledger)
    assert "1/2" in text
    assert "125%" not in text
    assert "2/2" not in text


def test_markdown_shows_hidden_counts():
    ledger = {
        "tasks": {"T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}}},
        "test": {"exit_code": 0},
        "hidden": {"auth": {"total": 2, "passed": 1, "failed": 1, "failures": []}},
    }
    text = render_markdown(make_state(done=1), ledger)
    assert "hidden: auth: 1/2" in text
    assert "hidden://" not in text


def test_viewmodel_and_cyber_deck():
    state = make_state(done=1)
    state.status = "DONE"
    state.diagnosis = "DONE"
    state.kicks = 2
    state.cost_usd = 0.0069
    ledger = {
        "tasks": {
            "T1": {
                "status": "done",
                "evidence": {"files": ["src/a.py"], "gate": "pass"},
            },
            "T2": {"status": "pending", "evidence": None},
        },
        "test": {"exit_code": 0},
        "quality": {
            "score": 76,
            "grade": "C",
            "errors": 0,
            "warnings": 8,
        },
    }
    view = WakerViewModel.from_state(state, ledger)
    assert view.done == 1
    assert view.total == 2
    assert view.score == 76
    assert view.grade == "C"
    assert view.tasks[0].percent == 100
    assert "Auth" in view.goal

    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True)
    console.print(build_cyber_deck(view, compact=False, frame=0))
    text = console.export_text()
    assert "WAKER CYBER-DECK" in text
    assert "WATCHDOG TELEMETRY" in text
    assert "76/100" in text
    assert "[q] Quit" in text

    console.print(build_cyber_deck(view, compact=False, frame=0, fx=False))
    assert "\x1b" not in console.export_text()


def test_cyber_deck_empty_state_is_safe():
    state = make_state(done=0)
    state.tasks = []
    state.status = "DONE"
    view = WakerViewModel.from_state(state, {"tasks": {}})

    from rich.console import Console

    console = Console(width=80, record=True, force_terminal=True)
    console.print(build_cyber_deck(view, compact=True, frame=0))
    text = console.export_text()
    assert "No tasks in contract" in text


def test_mini_line_is_plain_and_contains_quality():
    state = make_state(done=1)
    state.status = "DONE"
    state.diagnosis = "DONE"
    state.kicks = 2
    ledger = {
        "tasks": {"T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}}},
        "quality": {"score": 76, "grade": "C", "errors": 0, "warnings": 8},
    }
    view = WakerViewModel.from_state(state, ledger)
    line = mini_line(view)
    assert line.startswith("waker 7f3a")
    assert "C 76/100" in line
    assert "2/5 kicks" in line
    assert "0 err" in line
    assert "8 warn" in line
    assert "\x1b" not in line


def test_fx_can_be_disabled_and_honors_no_color(monkeypatch):
    assert fx_enabled(True) is False
    assert fx_enabled(False) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert fx_enabled(False) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("SSH_CONNECTION", "127.0.0.1")
    assert fx_enabled(False) is False


def test_open_watch_window_is_idempotent(tmp_path, monkeypatch):
    from waker import ui

    class FakeProcess:
        pid = 4242

    calls: list[list[str]] = []
    monkeypatch.setattr(ui.sys, "platform", "win32")
    monkeypatch.setattr(
        ui.winproc,
        "popen_visible",
        lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )
    monkeypatch.setattr(ui.winproc, "pid_alive", lambda pid: pid == 4242)

    assert open_watch_window(tmp_path, "run1") is True
    assert calls
    assert "watch" in calls[0]
    assert "--run" in calls[0]
    assert "--hold" in calls[0]
    assert "/wait" in calls[0]
    assert open_watch_window(tmp_path, "run1") is False
    assert len(calls) == 1

    # Legacy timestamp markers and dead PIDs must not block a new window.
    marker = tmp_path / ".waker" / "runs" / "run1" / "watch.window"
    marker.write_text("1795146262", encoding="utf-8")
    monkeypatch.setattr(ui.winproc, "pid_alive", lambda pid: False)
    assert open_watch_window(tmp_path, "run1") is True
    assert len(calls) == 2

    marker.write_text('{"pid": 999, "started": 1}', encoding="utf-8")
    assert open_watch_window(tmp_path, "run1") is True
    assert len(calls) == 3


def test_watch_done_renders_static_without_live(tmp_path, monkeypatch):
    import json

    from rich.console import Console

    from waker import ui
    from waker.state import RunPaths

    paths = RunPaths(tmp_path, "done")
    paths.root.mkdir(parents=True)
    state = make_state(done=1)
    state.repo = str(tmp_path)
    state.run_id = "done"
    state.status = "DONE"
    state.diagnosis = "DONE"
    state.tasks[0].update({"status": "done"})
    state.save(paths.state)
    paths.ledger.write_text(
        json.dumps(
            {
                "tasks": {
                    "T1": {
                        "status": "done",
                        "evidence": {"files": ["src/auth/guard.py"], "gate": "pass"},
                    }
                },
                "quality": {"score": 90, "grade": "A", "errors": 0, "warnings": 0},
            }
        ),
        encoding="utf-8",
    )

    import io

    class TTYBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    console = Console(width=120, record=True, force_terminal=True)
    monkeypatch.setattr("rich.console.Console", lambda: console)
    monkeypatch.setattr(
        "rich.live.Live",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("completed run must not use Live")
        ),
    )
    monkeypatch.setattr(ui.sys, "stdout", TTYBuffer())

    ui.watch(tmp_path, "done", hold=False)
    text = console.export_text()
    assert "WAKER CYBER-DECK" in text
    assert "DONE" in text
    assert 0 < len(text.splitlines()) <= 22


def test_watch_hold_waits_only_on_tty(tmp_path, monkeypatch):
    import json

    from rich.console import Console

    from waker import ui
    from waker.state import RunPaths

    paths = RunPaths(tmp_path, "done")
    paths.root.mkdir(parents=True)
    state = make_state(done=1)
    state.repo = str(tmp_path)
    state.run_id = "done"
    state.status = "DONE"
    state.diagnosis = "DONE"
    state.save(paths.state)
    paths.ledger.write_text(
        json.dumps({"tasks": {}, "quality": {"score": 100, "grade": "A"}}),
        encoding="utf-8",
    )

    import io

    class TTYBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    console = Console(width=120, record=True, force_terminal=True)
    waits: list[str] = []
    monkeypatch.setattr("rich.console.Console", lambda: console)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: waits.append(prompt),
    )
    monkeypatch.setattr(ui.sys, "stdout", TTYBuffer())
    ui.watch(tmp_path, "done", hold=True)
    assert len(waits) == 1
    assert "Press Enter" in waits[0]

    class NonTTY(io.StringIO):
        def isatty(self) -> bool:
            return False

    waits.clear()
    monkeypatch.setattr(ui.sys, "stdout", NonTTY())
    ui.watch(tmp_path, "done", hold=True)
    assert waits == []


def test_watch_cli_flags_parse():
    from waker.cli import build_parser

    args = build_parser().parse_args(
        ["watch", "--repo", ".", "--run", "abc", "--no-fx", "--mini", "--window", "--hold"]
    )
    assert args.no_fx is True
    assert args.mini is True
    assert args.window is True
    assert args.hold is True


def test_snake_beam_is_forward_only():
    from rich.text import Text

    from waker import ui

    panel = BeamPanel(Text("x"), border_style=ui._DECK_BORDER, beam=True, frame=0)
    total = 30
    assert "on #00ffff" in panel._beam_style(0, total, 0)
    assert panel._beam_style(1, total, 0) == ui._DECK_BORDER  # ahead of head
    assert panel._beam_style(29, total, 0) == "bold #ffffff"  # immediate tail
    assert panel._beam_style(28, total, 0) == "bold #00ffff"  # neon tail
    assert panel._beam_style(18, total, 0) == "#3d59a1"  # fading tail
    assert panel._beam_style(17, total, 0) == ui._DECK_BORDER  # beyond tail


def test_slop_uses_orange_border_and_done_stops_beam():
    from waker import ui

    state = make_state(done=1)
    state.status = "running"
    state.diagnosis = "SLOP"
    ledger = {
        "tasks": {"T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}}},
        "quality": {"score": 76, "grade": "C", "errors": 0, "warnings": 8},
    }
    running = WakerViewModel.from_state(state, ledger)
    deck = build_cyber_deck(running, compact=False, frame=0, fx=True)
    assert isinstance(deck, BeamPanel)
    assert deck.border_style == ui._DECK_ORANGE
    assert deck.beam is True

    state.status = "DONE"
    state.diagnosis = "DONE"
    done = WakerViewModel.from_state(state, ledger)
    done_deck = build_cyber_deck(done, compact=False, frame=0, fx=True)
    assert done_deck.border_style == ui._DECK_GREEN
    assert done_deck.beam is False


def test_preview_slop_border_and_spinner_animation():
    import importlib.util
    import sys
    from pathlib import Path

    from rich.console import Console

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "waker_preview_for_test", root / "scripts" / "preview_waker_deck.py"
    )
    assert spec is not None and spec.loader is not None
    preview = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = preview
    spec.loader.exec_module(preview)

    slop = preview.PHASES[1]
    deck = preview.render(slop, 10, 0, "\u280b", compact=False, frame_idx=0)
    assert deck.border_style == preview.ORANGE
    assert deck.beam is True

    done = preview.render(preview.PHASES[-1], 151, 0, "\u2713", compact=False, frame_idx=0)
    assert done.border_style == preview.GREEN
    assert done.beam is False

    for width, limit in ((120, 22), (80, 24)):
        console = Console(width=width, record=True, force_terminal=True)
        console.print(preview.render(slop, 10, 0, "\u280b", compact=width < 100, frame_idx=0))
        assert len(console.export_text().splitlines()) <= limit

    first = Console(width=120, record=True, force_terminal=True)
    first.print(preview.render(slop, 10, 0, "\u280b", compact=False, frame_idx=0))
    second = Console(width=120, record=True, force_terminal=True)
    second.print(preview.render(slop, 10, 0, "\u2819", compact=False, frame_idx=1))
    assert first.export_text() != second.export_text()


def test_viewmodel_phase_and_budget_line():
    from rich.console import Console

    state = make_state(done=1)
    state.status = "running"
    state.diagnosis = "SLOP"
    state.phases = [
        {"id": "P1", "name": "Core", "budget": "1h"},
        {"id": "P2", "name": "Docs", "budget": "2h"},
    ]
    state.tasks[0]["phase"] = "P1"
    state.tasks[1]["phase"] = "P2"
    state.phase_id = "P2"
    state.phase_started_ts = None
    state.phase_elapsed = {"P2": 4330}
    ledger = {
        "tasks": {
            "T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}},
            "T2": {"status": "pending", "evidence": None},
        },
        "quality": {"score": 76, "grade": "C", "errors": 0, "warnings": 8},
    }

    view = WakerViewModel.from_state(state, ledger)
    assert view.phase_id == "P2"
    assert view.phase_name == "Docs"
    assert view.phase_index == 2
    assert view.phase_total == 2
    assert view.phase_elapsed == 4330
    assert view.phase_budget == 7200
    assert view.phase_percent == 4330 / 7200 * 100

    console = Console(width=120, record=True, force_terminal=True)
    console.print(build_cyber_deck(view, compact=False, frame=0, fx=True))
    text = console.export_text()
    assert "PHASE 2/2" in text
    assert "Docs" in text
    assert "01:12:10 / 02:00:00" in text
    assert "[######----]" in text


def test_phase_colors_use_usage_thresholds():
    from waker import ui

    assert ui._phase_color(79.9) == ui._DECK_GREEN
    assert ui._phase_color(80.0) == ui._DECK_YELLOW
    assert ui._phase_color(94.9) == ui._DECK_YELLOW
    assert ui._phase_color(95.0) == ui._DECK_RED


def test_deck_height_fits_terminal_budget():
    from rich.console import Console

    state = make_state(done=1)
    state.status = "running"
    state.diagnosis = "SLOP"
    state.phases = [
        {"id": "P1", "name": "Core", "budget": "1h"},
        {"id": "P2", "name": "Docs", "budget": "2h"},
    ]
    state.tasks[0]["phase"] = "P1"
    state.tasks[1]["phase"] = "P2"
    state.phase_id = "P2"
    state.phase_started_ts = None
    state.phase_elapsed = {"P2": 4330}
    ledger = {
        "tasks": {
            "T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}},
            "T2": {"status": "pending", "evidence": None},
        },
        "quality": {"score": 76, "grade": "C", "errors": 0, "warnings": 8},
    }
    view = WakerViewModel.from_state(state, ledger)
    view.events = [
        DeckEvent("00:01", "KICK", f"attempt {index} failed on a long line that should be clipped")
        for index in range(5)
    ]
    view.fail_log = ["pytest failed at test_todo.py:42", "ruff TYPE006 x7"]
    for width, limit in ((120, 22), (80, 24)):
        console = Console(width=width, record=True, force_terminal=True)
        console.print(build_cyber_deck(view, compact=width < 100, frame=0, fx=True))
        assert len(console.export_text().splitlines()) <= limit
