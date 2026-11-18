from __future__ import annotations

from waker.models import Task
from waker.state import RunState
from waker.ui import WakerViewModel, build_cyber_deck, progress_bar, render_markdown


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
    assert "WAKER SUPERVISOR" in text
    assert "WATCHDOG TELEMETRY" in text
    assert "76/100" in text
    assert "[q] Quit" in text


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
