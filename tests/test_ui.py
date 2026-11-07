from __future__ import annotations

from waker.models import Task
from waker.state import RunState
from waker.ui import progress_bar, render_markdown


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
