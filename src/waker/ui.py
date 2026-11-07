"""Renderers. The UI never computes state - it only draws `ledger.json`."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .models import Task
from .state import RunPaths, RunState, read_json

ICONS = {
    "done": "\u2705",
    "failed": "\U0001F534",
    "pending": "\u2b1c",
    "blocked": "\u23f8",
}


def progress_bar(done: int, total: int, width: int = 16) -> str:
    if total <= 0:
        return "\u2591" * width
    filled = int(round(width * done / total))
    filled = max(0, min(width, filled))
    return "\u2588" * filled + "\u2591" * (width - filled)


def fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes:02d}:{sec:02d}"


def _task_rows(state: RunState, ledger: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for task in state.task_objects():
        record = ledger.get("tasks", {}).get(task.id, {})
        status = record.get("status", "pending")
        evidence = record.get("evidence") or {}
        files = evidence.get("files") or []
        if files:
            shown = ", ".join(files[:2])
            if len(files) > 2:
                shown += f" (+{len(files) - 2})"
        else:
            shown = "\u2014 chưa có diff"
        gate = evidence.get("gate") or ("\u2014" if status == "pending" else status)
        if evidence.get("message") and status != "done":
            gate = f"{gate} \u00b7 {evidence['message']}"
        rows.append([ICONS.get(status, "\u2b1c"), task.id, task.desc, shown, gate])
    return rows


def render_markdown(state: RunState, ledger: dict[str, Any]) -> str:
    tasks = state.task_objects()
    total = len(tasks)
    done = len([1 for rec in ledger.get("tasks", {}).values() if rec.get("status") == "done"])
    percent = int(round(100 * done / total)) if total else 0
    test = ledger.get("test", {})
    test_exit = test.get("exit_code")
    if test_exit is None:
        test_label = "\u2014"
    elif test_exit == 0:
        test_label = "\u2705 PASS"
    else:
        test_label = "\u274c FAIL"

    lines = [
        f"**waker \u00b7 run {state.run_id} \u00b7 {done}/{total} \u2014 {percent}%**",
        f"`{progress_bar(done, total)}`  \u23f1 {fmt_duration(state.elapsed)}  "
        f"\U0001F501 {state.kicks}/{state.max_kicks}  \U0001F9EA {test_label}",
        "",
        "|   | Task | Việc | Bằng chứng | Cổng |",
        "|---|------|------|-----------|------|",
    ]
    for icon, task_id, desc, evidence, gate in _task_rows(state, ledger):
        lines.append(f"| {icon} | {task_id} | {desc} | {evidence} | {gate} |")

    failures = test.get("failed") or []
    if failures:
        lines.append("")
        lines.append("Lỗi test gần nhất:")
        for failure in failures[:5]:
            lines.append(f"- {failure}")
    if state.diagnosis:
        lines.append("")
        lines.append(f"Chẩn đoán cuối: **{state.diagnosis}** \u00b7 trạng thái: `{state.status}`")
    return "\n".join(lines)


def build_rich(state: RunState, ledger: dict[str, Any]):
    """Return a Rich renderable (imported lazily so the dep stays optional)."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    tasks = state.task_objects()
    total = len(tasks)
    done = len([1 for rec in ledger.get("tasks", {}).values() if rec.get("status") == "done"])
    percent = int(round(100 * done / total)) if total else 0

    table = Table(box=box.SIMPLE_HEAD, expand=True)
    table.add_column("", width=2)
    table.add_column("Task", width=6)
    table.add_column("Việc", overflow="fold")
    table.add_column("Bằng chứng", overflow="fold")
    table.add_column("Cổng", width=18)
    for icon, task_id, desc, evidence, gate in _task_rows(state, ledger):
        table.add_row(icon, task_id, desc, evidence, gate)

    test = ledger.get("test", {})
    test_exit = test.get("exit_code")
    test_label = "\u2014" if test_exit is None else ("PASS" if test_exit == 0 else "FAIL")
    header = Text(
        f"{progress_bar(done, total, 22)}  {done}/{total} \u00b7 {percent}%   "
        f"kick {state.kicks}/{state.max_kicks}   test {test_label}",
        style="bold",
    )
    body = Table.grid(padding=(0, 1))
    body.add_row(header)
    body.add_row(table)
    if state.diagnosis:
        body.add_row(Text(f"chẩn đoán: {state.diagnosis}", style="yellow"))
    return Panel(body, title=f"waker \u00b7 run {state.run_id}", border_style="cyan")


def load_latest(repo: str | Path) -> tuple[RunState, dict[str, Any], RunPaths]:
    from .state import latest_run

    run_id = latest_run(repo)
    if not run_id:
        raise FileNotFoundError("chưa có run nào trong .waker/runs")
    paths = RunPaths(repo, run_id)
    state = RunState.load(paths.state)
    ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
    return state, ledger, paths


def watch(repo: str | Path, run_id: str | None = None, interval: float = 1.0) -> None:
    from rich.live import Live

    paths = RunPaths(repo, run_id) if run_id else load_latest(repo)[2]
    with Live(build_rich(RunState.load(paths.state), read_json(paths.ledger)), refresh_per_second=4) as live:
        while True:
            if not paths.state.exists():
                break
            state = RunState.load(paths.state)
            ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
            live.update(build_rich(state, ledger))
            if state.status != "running":
                break
            time.sleep(interval)
