"""Local control plane: detached runs + a loopback HTTP daemon.

The daemon is stateless: it reads ``.waker/runs/<id>/`` on every request, so the
chatbox skill and a terminal TUI always see the same truth.
"""

from __future__ import annotations

from . import winproc

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .process import kill_tree
from .state import (
    RunPaths,
    RunState,
    latest_run,
    new_run_id,
    read_json,
    run_lock_pid,
    utcnow,
    write_json_atomic,
)
from . import winproc


def _package_root() -> str:
    # src/waker/daemon.py -> src
    return str(Path(__file__).resolve().parents[1])


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    root = _package_root()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def start_detached(repo: str | Path, run_args: list[str], run_id: str | None = None) -> dict[str, Any]:
    """Spawn ``waker run`` in the background and record its pid."""
    root = Path(repo).resolve()
    run_id = run_id or new_run_id()
    log_dir = root / ".waker" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.log"

    argv = [sys.executable, "-m", "waker", "run", "--run-id", run_id, *run_args]
    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": subprocess.STDOUT,
        "env": _child_env(),
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True

    with log_path.open("ab") as log:
        kwargs["stdout"] = log
        process = winproc.popen(argv, **kwargs)

    pid_dir = root / ".waker" / "daemon"
    pid_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": process.pid,
        "run_id": run_id,
        "started_at": utcnow(),
        "log": str(log_path),
        "argv": argv,
    }
    write_json_atomic(pid_dir / f"{run_id}.json", record)
    return record


def stop_run(repo: str | Path, run_id: str | None = None) -> bool:
    root = Path(repo).resolve()
    run_id = run_id or latest_run(root)
    if not run_id:
        return False
    record_path = root / ".waker" / "daemon" / f"{run_id}.json"
    pid = 0
    if record_path.exists():
        try:
            pid = int(read_json(record_path).get("pid") or 0)
        except (ValueError, OSError):
            pid = 0
        if pid:
            kill_tree(pid)

    stopped = bool(pid)
    paths = RunPaths(root, run_id)
    if paths.state.exists():
        state = RunState.load(paths.state)
        if state.status == "running":
            state.status = "aborted"
            state.diagnosis = "ABORTED"
            state.ended_ts = time.time()
            state.save(paths.state)
            stopped = True

    lock = paths.root / "run.lock"
    if lock.exists():
        try:
            lock_pid = run_lock_pid(paths)
            if not lock_pid or not winproc.pid_alive(lock_pid) or lock_pid == pid:
                lock.unlink()
        except (FileNotFoundError, OSError):
            pass
    return stopped


def _run_status(root: Path, run_id: str | None) -> dict[str, Any]:
    run_id = run_id or latest_run(root)
    if not run_id:
        return {"error": "no run found"}
    paths = RunPaths(root, run_id)
    if not paths.state.exists():
        return {"error": f"run {run_id} not found"}
    state = RunState.load(paths.state)
    ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
    return {
        "run_id": state.run_id,
        "status": state.status,
        "diagnosis": state.diagnosis,
        "kicks": state.kicks,
        "max_kicks": state.max_kicks,
        "elapsed": round(state.elapsed, 1),
        "cost_usd": round(state.cost_usd, 6),
        "max_cost_usd": state.max_cost_usd,
        "tasks": ledger.get("tasks", {}),
        "test": ledger.get("test", {}),
        "report": str(paths.report) if paths.report.exists() else None,
    }


def _build_run_args(payload: dict[str, Any]) -> list[str]:
    """Translate a JSON /start body into ``waker run`` flags."""
    args: list[str] = []
    mapping = {
        "tasks": "--tasks",
        "prompt": "--prompt",
        "test": "--test",
        "agent": "--agent",
        "adapter": "--adapter",
        "model": "--model",
        "repo": "--repo",
    }
    for key, flag in mapping.items():
        value = payload.get(key)
        if value not in (None, ""):
            args.extend([flag, str(value)])
    numeric = {
        "max_kicks": "--max-kicks",
        "max_cost": "--max-cost",
        "turn_timeout": "--turn-timeout",
        "freeze_after": "--freeze-after",
        "max_wall_clock": "--max-wall-clock",
    }
    for key, flag in numeric.items():
        value = payload.get(key)
        if value not in (None, ""):
            args.extend([flag, str(value)])
    if payload.get("no_freeze_probe"):
        args.append("--no-freeze-probe")
    return args


class _Handler(BaseHTTPRequestHandler):
    server_version = "waker-daemon/0.2"
    default_repo = "."

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib API
        # Keep the daemon quiet; the run log is the audit trail.
        return

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        root = Path(query.get("repo") or self.default_repo).resolve()
        if parsed.path == "/health":
            self._json(200, {"ok": True, "version": "0.2"})
            return
        if parsed.path == "/status":
            self._json(200, _run_status(root, query.get("run")))
            return
        if parsed.path == "/runs":
            runs_dir = root / ".waker" / "runs"
            runs = (
                [p.name for p in runs_dir.iterdir() if (p / "run.json").exists()]
                if runs_dir.is_dir()
                else []
            )
            self._json(200, {"repo": str(root), "runs": runs})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "body must be an object"})
            return

        root = Path(payload.get("repo") or self.default_repo).resolve()
        if parsed.path == "/start":
            run_args = _build_run_args({**payload, "repo": str(root)})
            if not run_args:
                self._json(400, {"error": "empty run arguments"})
                return
            record = start_detached(root, run_args)
            self._json(200, record)
            return
        if parsed.path == "/stop":
            stopped = stop_run(root, payload.get("run"))
            self._json(200, {"stopped": stopped})
            return
        self._json(404, {"error": "not found"})


def make_server(repo: str | Path, host: str = "127.0.0.1", port: int = 47821) -> ThreadingHTTPServer:
    handler = type("WakerHandler", (_Handler,), {"default_repo": str(Path(repo).resolve())})
    return ThreadingHTTPServer((host, port), handler)


def serve(repo: str | Path, host: str = "127.0.0.1", port: int = 47821) -> None:
    server = make_server(repo, host, port)
    print(f"waker daemon listening on http://{host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
