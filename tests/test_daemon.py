from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from conftest import exists_cmd, fake_agent

from waker.daemon import make_server, stop_run
from waker.planner import PlanBundle, write_tasks


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def test_daemon_starts_a_detached_run_and_reports_status(repo: Path, tasks):
    contract = repo / "tasks.yaml"
    write_tasks(contract, PlanBundle(tasks=tasks))

    server = make_server(repo, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    run_id = None
    try:
        assert _get(f"{base}/health")["ok"] is True

        record = _post(
            f"{base}/start",
            {
                "repo": str(repo),
                "tasks": str(contract),
                "test": exists_cmd("src/a.txt", "src/b.txt"),
                "agent": fake_agent("good"),
                "adapter": "generic",
                "max_kicks": 1,
            },
        )
        run_id = record["run_id"]
        assert record["pid"] > 0

        status: dict = {}
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                status = _get(
                    f"{base}/status?repo={urllib.parse.quote(str(repo))}&run={run_id}"
                )
            except OSError:
                status = {}
            if status.get("status") in {
                "DONE",
                "BREAKER",
                "BLOCKED",
                "SUSPECT_TEST",
                "aborted",
            }:
                break
            time.sleep(0.3)

        assert status.get("status") == "DONE", status
        assert status["tasks"]["T1"]["status"] == "done"
        assert status["tasks"]["T2"]["status"] == "done"
        assert status["report"]
    finally:
        if run_id:
            stop_run(repo, run_id)
        server.shutdown()
        server.server_close()


def test_stop_unknown_run_returns_false(tmp_path: Path):
    assert stop_run(tmp_path, "deadbeef") is False


def test_stop_marks_running_state_aborted(tmp_path: Path):
    from waker.state import RunPaths, RunState, write_json_atomic

    paths = RunPaths(tmp_path, "r1")
    paths.root.mkdir(parents=True)
    state = RunState(
        run_id="r1",
        repo=str(tmp_path),
        prompt="",
        agent_command="true",
        test_command=None,
        baseline_commit="",
        baseline_test_hash="",
        test_globs=[],
        started_at="now",
        tasks=[],
        session_id="ses",
        status="running",
    )
    state.save(paths.state)
    daemon_dir = tmp_path / ".waker" / "daemon"
    daemon_dir.mkdir(parents=True)
    write_json_atomic(daemon_dir / "r1.json", {"pid": 999999999})

    assert stop_run(tmp_path, "r1") is True
    assert RunState.load(paths.state).status == "aborted"
