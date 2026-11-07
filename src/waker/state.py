"""Run state, ledger, audit trail and git checkpoints.

Everything that matters is written to disk under ``.waker/runs/<run_id>/`` so a
crash never loses the truth. The UI is only ever a renderer of these files.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Task


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return secrets.token_hex(4)


def write_json_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def is_git_repo(repo: str | Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_head(repo: str | Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def git_dirty(repo: str | Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def ensure_runtime_excluded(repo: str | Path) -> None:
    """Keep ``.waker/`` out of commits without touching the user's .gitignore."""
    git_dir = Path(repo) / ".git"
    if not git_dir.is_dir():
        return
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    except OSError:  # pragma: no cover - exotic filesystem
        return
    if ".waker/" not in text:
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write("\n# waker runtime\n.waker/\n")


def checkpoint(repo: str | Path, message: str) -> str | None:
    """Commit the working tree. Returns the commit hash, or None if clean."""
    root = str(repo)
    subprocess.run(["git", "-C", root, "add", "-A"], capture_output=True, check=False)
    status = subprocess.run(
        ["git", "-C", root, "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    if not status.stdout.strip():
        return None
    subprocess.run(
        [
            "git",
            "-C",
            root,
            "-c",
            "user.name=waker",
            "-c",
            "user.email=waker@local",
            "commit",
            "-q",
            "-m",
            message,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return git_head(root)


@dataclass
class RunState:
    run_id: str
    repo: str
    prompt: str
    agent_command: str
    test_command: str | None
    baseline_commit: str
    baseline_test_hash: str
    test_globs: list[str]
    started_at: str
    tasks: list[dict[str, Any]]
    session_id: str
    agent_session_id: str | None = None
    constraints: list[dict[str, Any]] = field(default_factory=list)
    adapter: str = "generic"
    model: str | None = None
    permission_mode: str = "acceptEdits"
    binary: str | None = None
    contract_path: str | None = None
    generation: int = 0
    elapsed_offset: float = 0.0
    max_kicks: int = 5
    kicks: int = 0
    turn_timeout: float = 900.0
    freeze_after: float = 300.0
    alive_threshold: float = 120.0
    max_wall_clock: float = 5400.0
    status: str = "running"
    diagnosis: str | None = None
    last_fingerprint: str | None = None
    prev_fingerprint: str | None = None
    fingerprint_streak: int = 0
    last_diff_hash: str | None = None
    contract_hash: str = ""
    cost_usd: float = 0.0
    max_cost_usd: float = 0.0
    started_ts: float = field(default_factory=time.time)
    ended_ts: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.ended_ts if self.ended_ts is not None else time.time()
        return max(0.0, self.elapsed_offset + end - self.started_ts)

    def task_objects(self) -> list[Task]:
        return [Task.from_dict(item) for item in self.tasks]

    def save(self, path: str | Path) -> None:
        write_json_atomic(path, asdict(self))

    @classmethod
    def load(cls, path: str | Path) -> "RunState":
        data = read_json(path)
        return cls(**data)


class RunPaths:
    """Canonical layout of one run."""

    def __init__(self, repo: str | Path, run_id: str) -> None:
        self.repo = Path(repo)
        self.run_id = run_id
        self.root = self.repo / ".waker" / "runs" / run_id
        self.state = self.root / "run.json"
        self.ledger = self.root / "ledger.json"
        self.events = self.root / "events.jsonl"
        self.report = self.root / "report.md"

    def kick_dir(self, index: int, generation: int = 0) -> Path:
        name = f"kick-{index}" if generation == 0 else f"kick-{index}-g{generation}"
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def kick_prompt(self, index: int, generation: int = 0) -> Path:
        return self.kick_dir(index, generation) / "prompt.txt"

    def kick_result(self, index: int, generation: int = 0) -> Path:
        return self.kick_dir(index, generation) / "result.json"


class EventLog:
    """Append-only audit trail. Written before actions, not after."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {"ts": utcnow(), "t": event, **fields}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record


def new_ledger(tasks: list[Task]) -> dict[str, Any]:
    return {
        "tasks": {
            task.id: {"status": "pending", "evidence": None, "since_kick": None}
            for task in tasks
        },
        "test": {"exit_code": None, "failed": [], "signature": ""},
        "kicks": 0,
        "updated_at": utcnow(),
    }


def set_task(
    ledger: dict[str, Any],
    task_id: str,
    status: str,
    evidence: dict[str, Any] | None,
    kick: int,
) -> None:
    record = ledger.setdefault("tasks", {}).setdefault(
        task_id, {"status": "pending", "evidence": None, "since_kick": None}
    )
    if record.get("status") != status:
        record["since_kick"] = kick
    record["status"] = status
    record["evidence"] = evidence
    ledger["updated_at"] = utcnow()


def done_ids(ledger: dict[str, Any]) -> list[str]:
    return [tid for tid, rec in ledger.get("tasks", {}).items() if rec.get("status") == "done"]


def pending_ids(ledger: dict[str, Any]) -> list[str]:
    return [tid for tid, rec in ledger.get("tasks", {}).items() if rec.get("status") != "done"]


def latest_run(repo: str | Path) -> str | None:
    root = Path(repo) / ".waker" / "runs"
    if not root.is_dir():
        return None
    candidates = [p for p in root.iterdir() if (p / "run.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime).name
