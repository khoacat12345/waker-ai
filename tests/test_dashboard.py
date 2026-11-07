from __future__ import annotations

import time
from pathlib import Path

from waker.dashboard import render_html, write_static
from waker.models import Task
from waker.state import RunPaths, RunState, write_json_atomic


def make_state(tasks: list[Task]) -> RunState:
    return RunState(
        run_id="dash1",
        repo=".",
        prompt="",
        agent_command="x",
        test_command=None,
        baseline_commit="",
        baseline_test_hash="",
        test_globs=[],
        started_at="now",
        tasks=[task.to_dict() for task in tasks],
        session_id="ses_dash",
        kicks=2,
        max_kicks=5,
        cost_usd=0.0123,
    )


def test_html_contains_progress_tasks_and_escaping():
    tasks = [
        Task(id="T1", desc="Auth <script>alert(1)</script>", scope=["src/auth/**"]),
        Task(id="T2", desc="Payment", scope=["src/pay/**"]),
    ]
    ledger = {
        "tasks": {
            "T1": {"status": "done", "evidence": {"files": ["src/auth/a.py"], "gate": "pass"}},
            "T2": {"status": "failed", "evidence": {"files": [], "gate": "fail", "message": "boom"}},
        },
        "test": {"exit_code": 1, "failed": ["tests/test_pay.py::x"]},
    }
    html = render_html(make_state(tasks), ledger, tasks)

    assert "T1" in html and "T2" in html
    assert "50%" in html
    assert "badge done" in html and "badge failed" in html
    assert "src/auth/a.py" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "$0.0123" in html


def test_write_static(tmp_path: Path, repo: Path):
    paths = RunPaths(repo, "dash1")
    state = make_state([Task(id="T1", desc="Auth", scope=["src/**"])])
    state.repo = str(repo)
    state.ended_ts = time.time()
    state.save(paths.state)
    write_json_atomic(paths.ledger, {"tasks": {"T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}}}, "test": {"exit_code": 0}})

    target = write_static(repo, tmp_path / "dashboard.html", "dash1")
    text = target.read_text(encoding="utf-8")
    assert "dash1" in text
    assert "T1" in text
    assert "100%" in text



def test_live_dashboard_http(repo: Path):
    import json
    import threading
    import urllib.request

    from waker.dashboard import make_dashboard_server

    paths = RunPaths(repo, "dash2")
    state = make_state([Task(id="T1", desc="Auth", scope=["src/**"])])
    state.run_id = "dash2"
    state.repo = str(repo)
    state.ended_ts = time.time()
    state.save(paths.state)
    write_json_atomic(
        paths.ledger,
        {
            "tasks": {
                "T1": {"status": "done", "evidence": {"files": ["src/a.py"], "gate": "pass"}}
            },
            "test": {"exit_code": 0},
        },
    )

    server = make_dashboard_server(repo, "dash2", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/", timeout=10) as response:
            html = response.read().decode("utf-8")
        assert "dash2" in html
        assert "T1" in html
        with urllib.request.urlopen(base + "/api/status", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["run_id"] == "dash2"
        assert payload["status"] == "running"
    finally:
        server.shutdown()
        server.server_close()
