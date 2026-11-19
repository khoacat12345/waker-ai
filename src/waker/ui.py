"""Renderers. The UI never computes state - it only draws the run truth."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import globs, winproc
from .models import Task
from .state import RunPaths, RunState, read_json
from .tui import quality_line

ICONS = {
    "done": "\u2705",
    "failed": "\U0001F534",
    "pending": "\u2b1c",
    "blocked": "\u23f8",
}

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_FINDING_RE = re.compile(
    r"^(ERROR|WARNING)\s+([A-Z]+[0-9]+)\s+(.+?):(\d+)\s+-\s+(.*?)(?:\s+\|\s+Fix:\s+(.*))?$"
)
_DECK_BORDER = "#3b4261"
_DECK_TEXT = "#c0caf5"
_DECK_MUTED = "#565f89"
_DECK_BLUE = "#7aa2f7"
_DECK_CYAN = "#7dcfff"
_DECK_GREEN = "#9ece6a"
_DECK_MINT = "#73daca"
_DECK_RED = "#f7768e"
_DECK_YELLOW = "#e0af68"
_DECK_ORANGE = "#ff9e64"


def _grade_for_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _short(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def fx_enabled(no_fx: bool = False) -> bool:
    """FX are opt-out and automatically disabled on hostile terminals."""
    if no_fx:
        return False
    if "NO_COLOR" in os.environ:
        return False
    if any(os.environ.get(name) for name in ("SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY")):
        return False
    return True


def mini_line(view: WakerViewModel) -> str:
    """One-line plain-text fallback for pipes, SSH and chatboxes."""
    status = view.state.status.upper()
    if view.state.diagnosis and view.state.diagnosis not in {"DONE", status}:
        status = f"{status}/{view.state.diagnosis}"
    return (
        f"waker {view.state.run_id} · {view.grade} {view.score}/100 · "
        f"{view.state.kicks}/{view.state.max_kicks} kicks · "
        f"{view.errors} err · {view.warnings} warn · {status}"
    )


def open_watch_window(
    repo: str | Path,
    run_id: str | None = None,
    *,
    no_fx: bool = False,
) -> bool:
    """Open the Cyber-Deck in a separate Windows terminal, once per run.

    The marker is intentionally conservative: a second invocation for the same
    run is refused while the marker is fresh. It prevents the chatbox from
    spawning a window every time the user asks for progress.
    """
    if sys.platform != "win32":
        return False
    root = Path(repo).resolve()
    resolved = run_id
    if resolved is None:
        from .state import latest_run

        resolved = latest_run(root)
    if not resolved:
        return False
    paths = RunPaths(root, resolved)
    marker = paths.root / "watch.window"
    if marker.exists():
        try:
            if time.time() - marker.stat().st_mtime < 3600:
                return False
            marker.unlink()
        except OSError:
            return False
    paths.root.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(int(time.time())), encoding="utf-8")
    command = [
        "cmd.exe",
        "/c",
        "start",
        "Waker Cyber-Deck",
        sys.executable,
        "-m",
        "waker",
        "watch",
        "--repo",
        str(root),
        "--run",
        str(resolved),
    ]
    if no_fx:
        command.append("--no-fx")
    try:
        winproc.popen_visible(command, cwd=str(root))
    except OSError:
        try:
            marker.unlink()
        except OSError:
            pass
        return False
    return True


@dataclass(frozen=True)
class DeckFinding:
    severity: str
    rule: str
    path: str
    line: int
    message: str
    suggestion: str = ""


@dataclass
class TaskView:
    id: str
    desc: str
    status: str
    percent: int
    grade: str | None
    errors: int
    warnings: int
    files: list[str] = field(default_factory=list)
    diffs: list[tuple[str, int, int]] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    verify: str = "—"
    added: int = 0
    deleted: int = 0
    message: str = ""


@dataclass(frozen=True)
class DeckEvent:
    timestamp: str
    label: str
    message: str


@dataclass
class WakerViewModel:
    """Pure read model for the Cyber-Deck terminal UI.

    This deliberately does not run the gate or modify the run. It reads the
    same ledger/events/run files as every other UI surface, then derives a
    compact view model. Waker is still the source of truth.
    """

    state: RunState
    ledger: dict[str, Any]
    paths: RunPaths | None = None
    tasks: list[TaskView] = field(default_factory=list)
    events: list[DeckEvent] = field(default_factory=list)
    kick_log: list[str] = field(default_factory=list)
    fail_log: list[str] = field(default_factory=list)
    anti_slop: list[DeckFinding] = field(default_factory=list)
    agent: str = ""
    goal: str = ""
    quality: dict[str, Any] = field(default_factory=dict)
    out_of_scope: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(1 for task in self.tasks if task.status == "done")

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def score(self) -> int:
        return int(self.quality.get("score", 100))

    @property
    def grade(self) -> str:
        return str(self.quality.get("grade") or _grade_for_score(self.score))

    @property
    def errors(self) -> int:
        return int(self.quality.get("errors", 0))

    @property
    def warnings(self) -> int:
        return int(self.quality.get("warnings", 0))

    @classmethod
    def from_paths(cls, paths: RunPaths) -> "WakerViewModel":
        state = RunState.load(paths.state)
        ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
        return cls.from_state(state, ledger, paths)

    @classmethod
    def from_state(
        cls,
        state: RunState,
        ledger: dict[str, Any],
        paths: RunPaths | None = None,
    ) -> "WakerViewModel":
        repo = Path(state.repo)
        quality = dict(ledger.get("quality") or {})
        result_payload = _read_latest_result(paths)
        findings = _findings_from_payload(result_payload)
        task_objects = state.task_objects()
        changed, diff_stats, additions, deletions = _git_changes(
            repo, state.baseline_commit
        )
        tasks: list[TaskView] = []
        for task in task_objects:
            record = ledger.get("tasks", {}).get(task.id, {})
            status = str(record.get("status", "pending"))
            evidence = record.get("evidence") or {}
            files = [str(item) for item in evidence.get("files") or []]
            scoped = [
                path
                for path in changed
                if task.scope and globs.matches_any(path, task.scope)
            ]
            task_findings = [
                finding
                for finding in findings
                if task.scope and globs.matches_any(finding.path, task.scope)
            ]
            task_errors = sum(1 for item in task_findings if item.severity == "ERROR")
            task_warnings = sum(
                1 for item in task_findings if item.severity == "WARNING"
            )
            if task_findings:
                task_score = max(
                    0, 100 - 10 * task_errors - 3 * task_warnings
                )
                task_grade: str | None = _grade_for_score(task_score)
            else:
                task_grade = None
            if status == "done" or evidence.get("gate") == "pass":
                percent = 100
            elif scoped or files:
                percent = 50
            else:
                percent = 0
            verify = str(evidence.get("gate") or "—")
            message = str(evidence.get("message") or "")
            added = sum(diff_stats.get(path, (0, 0))[0] for path in scoped)
            deleted = sum(diff_stats.get(path, (0, 0))[1] for path in scoped)
            diffs = [
                (path, *diff_stats.get(path, (0, 0)))
                for path in scoped
                if path in diff_stats
            ]
            tasks.append(
                TaskView(
                    id=task.id,
                    desc=task.desc,
                    status=status,
                    percent=percent,
                    grade=task_grade,
                    errors=task_errors,
                    warnings=task_warnings,
                    files=list(dict.fromkeys([*scoped, *files]))[:12],
                    diffs=diffs[:12],
                    scope=list(task.scope),
                    verify=verify,
                    added=added,
                    deleted=deleted,
                    message=message,
                )
            )

        events_raw = _read_events(paths)
        kick_log: list[str] = []
        events: list[DeckEvent] = []
        for item in events_raw:
            kind = str(item.get("t", ""))
            timestamp = _event_time(item.get("ts"))
            if kind == "diagnose":
                label = str(item.get("label", "?"))
                kick_log.append(f"kick {item.get('kick', '?')} {label}")
                events.append(
                    DeckEvent(timestamp, label, f"kick {item.get('kick', '?')}")
                )
            elif kind in {"slop_revert", "slop_abort"}:
                events.append(DeckEvent(timestamp, kind.upper(), "anti-slop policy"))
            elif kind == "terminal":
                label = str(item.get("diagnosis", "TERMINAL"))
                if events and events[-1].label == label:
                    continue
                events.append(
                    DeckEvent(
                        timestamp,
                        label,
                        str(item.get("status", "")),
                    )
                )

        test = ledger.get("test") or {}
        fail_log = [str(item) for item in test.get("failed") or []][:5]
        out_of_scope = [
            str(path) for path in result_payload.get("unscoped") or []
        ]
        if not result_payload and task_objects:
            out_of_scope = [
                path
                for path in changed
                if not any(
                    task.scope and globs.matches_any(path, task.scope)
                    for task in task_objects
                )
            ]
        quality.setdefault("score", _score_from_findings(findings))
        quality.setdefault("grade", _grade_for_score(int(quality["score"])))
        quality.setdefault("errors", sum(1 for f in findings if f.severity == "ERROR"))
        quality.setdefault(
            "warnings", sum(1 for f in findings if f.severity == "WARNING")
        )
        agent = _agent_label(state)
        goal = _goal(state, task_objects)
        return cls(
            state=state,
            ledger=ledger,
            paths=paths,
            tasks=tasks,
            events=events[-5:],
            kick_log=kick_log[-5:],
            fail_log=fail_log,
            anti_slop=findings[-12:],
            agent=agent,
            goal=goal,
            quality=quality,
            out_of_scope=out_of_scope,
            changed_files=changed,
        )


def _event_time(value: Any) -> str:
    if not value:
        return "--:--:--"
    try:
        return datetime.fromisoformat(str(value)).strftime("%H:%M:%S")
    except ValueError:
        return str(value)[-8:]


def _agent_label(state: RunState) -> str:
    adapter = (state.adapter or "generic").lower()
    names = {
        "opencode": "OpenCode",
        "claude": "Claude",
        "generic": "Generic",
        "pty": "PTY",
    }
    name = names.get(adapter, state.adapter or "generic")
    model = state.model
    if not model and ":" in state.agent_command:
        model = state.agent_command.split(":", 1)[1]
    return f"{name} · {model}" if model else name


def _goal(state: RunState, tasks: list[Task]) -> str:
    prompt = " ".join((state.prompt or "").split())
    if prompt:
        return _short(prompt, 90)
    if tasks:
        return _short(tasks[0].desc, 90)
    return "(no goal recorded)"


def _score_from_findings(findings: list[DeckFinding]) -> int:
    errors = sum(1 for item in findings if item.severity == "ERROR")
    warnings = sum(1 for item in findings if item.severity == "WARNING")
    return max(0, 100 - errors * 10 - warnings * 3)


def _read_events(paths: RunPaths | None) -> list[dict[str, Any]]:
    if paths is None or not paths.events.exists():
        return []
    result: list[dict[str, Any]] = []
    try:
        for line in paths.events.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                result.append(item)
    except OSError:
        return []
    return result


def _read_latest_result(paths: RunPaths | None) -> dict[str, Any]:
    if paths is None:
        return {}
    candidates = sorted(
        paths.root.glob("kick-*/result.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        return {}
    try:
        payload = read_json(candidates[-1])
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _findings_from_payload(payload: dict[str, Any]) -> list[DeckFinding]:
    raw = (payload.get("slop") or {}).get("findings") or []
    findings: list[DeckFinding] = []
    for line in raw:
        match = _FINDING_RE.match(str(line))
        if not match:
            continue
        severity, rule, path, number, message, suggestion = match.groups()
        findings.append(
            DeckFinding(
                severity=severity,
                rule=rule,
                path=path,
                line=int(number),
                message=message.strip(),
                suggestion=(suggestion or "").strip(),
            )
        )
    return findings


def _git_changes(
    repo: Path,
    baseline: str,
) -> tuple[list[str], dict[str, tuple[int, int]], int, int]:
    """Read real numstat data; failures are non-fatal for the UI."""
    if not baseline:
        return [], {}, 0, 0
    try:
        result = winproc.run(
            ["git", "-C", str(repo), "diff", "--numstat", baseline, "--"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return [], {}, 0, 0
    if result.returncode != 0:
        return [], {}, 0, 0
    changed: list[str] = []
    stats: dict[str, tuple[int, int]] = {}
    total_added = total_deleted = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        if added == "-" or deleted == "-":
            continue
        try:
            additions, removals = int(added), int(deleted)
        except ValueError:
            continue
        path = globs.normalize(path)
        changed.append(path)
        stats[path] = (additions, removals)
        total_added += additions
        total_deleted += removals
    return changed, stats, total_added, total_deleted


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
            shown = "\u2014 no diff yet"
        gate = evidence.get("gate") or ("\u2014" if status == "pending" else status)
        if evidence.get("message") and status != "done":
            gate = f"{gate} \u00b7 {evidence['message']}"
        rows.append([ICONS.get(status, "\u2b1c"), task.id, task.desc, shown, gate])
    return rows


def render_markdown(state: RunState, ledger: dict[str, Any]) -> str:
    tasks = state.task_objects()
    task_ids = {task.id for task in tasks}
    total = len(tasks)
    done = len(
        [
            1
            for task_id, rec in ledger.get("tasks", {}).items()
            if task_id in task_ids and rec.get("status") == "done"
        ]
    )
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
        f"\U0001F501 {state.kicks}/{state.max_kicks}  \U0001F9EA {test_label}"
        + (f"  \U0001F4B0 ${state.cost_usd:.4f}" if state.cost_usd else ""),
    ]
    if ledger.get("quality"):
        lines.append(quality_line(ledger))
    hidden = ledger.get("hidden") or {}
    if hidden:
        summary = "  ".join(
            f"{name}: {record.get('passed', 0)}/{record.get('total', 0)}"
            for name, record in hidden.items()
        )
        lines.append(f"hidden: {summary}")
    lines.extend(["", "|   | Task | Work | Evidence | Gate |",
                  "|---|------|------|-----------|------|"])
    for icon, task_id, desc, evidence, gate in _task_rows(state, ledger):
        lines.append(f"| {icon} | {task_id} | {desc} | {evidence} | {gate} |")

    failures = test.get("failed") or []
    if failures:
        lines.append("")
        lines.append("Latest test failures:")
        for failure in failures[:5]:
            lines.append(f"- {failure}")
    if state.diagnosis:
        lines.append("")
        lines.append(f"Final diagnosis: **{state.diagnosis}** \u00b7 status: `{state.status}`")
    return "\n".join(lines)


def build_rich(state: RunState, ledger: dict[str, Any]):
    """Return a Rich renderable (imported lazily so the dep stays optional)."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    tasks = state.task_objects()
    task_ids = {task.id for task in tasks}
    total = len(tasks)
    done = len(
        [
            1
            for task_id, rec in ledger.get("tasks", {}).items()
            if task_id in task_ids and rec.get("status") == "done"
        ]
    )
    percent = int(round(100 * done / total)) if total else 0

    table = Table(box=box.SIMPLE_HEAD, expand=True)
    table.add_column("", width=2)
    table.add_column("Task", width=6)
    table.add_column("Work", overflow="fold")
    table.add_column("Evidence", overflow="fold")
    table.add_column("Gate", width=18)
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
    if ledger.get("quality"):
        body.add_row(Text(quality_line(ledger), style="bold green" if not ledger["quality"].get("errors") else "bold red"))
    hidden = ledger.get("hidden") or {}
    if hidden:
        summary = "  ".join(
            f"{name}: {record.get('passed', 0)}/{record.get('total', 0)}"
            for name, record in hidden.items()
        )
        body.add_row(Text(f"hidden: {summary}", style="cyan"))
    body.add_row(table)
    if state.diagnosis:
        body.add_row(Text(f"diagnosis: {state.diagnosis}", style="yellow"))
    return Panel(body, title=f"waker \u00b7 run {state.run_id}", border_style="cyan")


def _deck_bar(score: int, width: int = 10, *, frame: int = 0, fx: bool = True) -> Any:
    from rich.text import Text

    filled = int(round(width * max(0, min(100, score)) / 100))
    bar = Text()
    for index in range(width):
        if index < filled:
            style = _DECK_BLUE if score >= 70 else _DECK_YELLOW
            if fx and filled and index == frame % filled:
                style = f"bold {_DECK_CYAN}"
            bar.append("▰", style=style)
        else:
            bar.append("▱", style=_DECK_BORDER)
    return bar


def _deck_rule_counts(view: WakerViewModel) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for finding in view.anti_slop:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


class BeamPanel:
    """Rounded panel with an animated electric laser border beam.

    Rich's Panel applies one style to the whole border. This renderable
    keeps the child layout intact while styling an intense electric laser beam
    traveling smoothly along the entire 2D perimeter of the panel
    (top -> right -> bottom -> left) with a glowing comet gradient.
    """

    def __init__(
        self,
        renderable: Any,
        *,
        border_style: str = _DECK_BORDER,
        beam: bool = False,
        frame: int = 0,
    ) -> None:
        self.renderable = renderable
        self.border_style = border_style
        self.beam = beam
        self.frame = frame

    def _beam_style(self, p: int, P: int, phase: int) -> str:
        if not self.beam:
            return self.border_style
        dist = min((p - phase) % P, (phase - p) % P)
        if dist == 0:
            return "bold #ffffff on #7dcfff"  # Lightning spark head!
        if dist <= 1:
            return "bold #ffffff"  # Blinding white core
        if dist <= 3:
            return "bold #00ffff"  # Electric neon cyan
        if dist <= 6:
            return "bold #7dcfff"  # Glowing cyan
        if dist <= 10:
            return "#7aa2f7"  # Electric blue aura
        if dist <= 15:
            return "#3d59a1"  # Deep blue fading comet tail
        return self.border_style

    def __rich_console__(self, console: Any, options: Any):
        from rich.text import Text

        width = max(20, options.max_width)
        inner = max(1, width - 2)
        child_options = options.update(width=inner)
        lines = console.render_lines(self.renderable, child_options, pad=True)
        if not lines:
            lines = [[]]

        H = len(lines)
        P = max(1, 2 * (width + H))
        phase = (self.frame * 4) % P

        # 1. Top row: p travels 0 .. width - 1
        top = Text("╭", style=self._beam_style(0, P, phase))
        for index in range(inner):
            p = index + 1
            top.append("─", style=self._beam_style(p, P, phase))
        top.append("╮", style=self._beam_style(width - 1, P, phase))
        yield top

        # 2. Body rows: left wall travels UP (P - 1 - y), right wall travels DOWN (width + y)
        for y, row in enumerate(lines):
            p_left = P - 1 - y
            p_right = width + y
            left = Text("│", style=self._beam_style(p_left, P, phase))
            body = Text()
            for segment in row:
                text = getattr(segment, "text", "")
                if not text:
                    continue
                body.append(text, style=getattr(segment, "style", None))
            if body.cell_len < inner:
                body.append(" " * (inner - body.cell_len))
            left.append_text(body)
            left.append("│", style=self._beam_style(p_right, P, phase))
            yield left

        # 3. Bottom row: travels right to left
        p_bot_left = 2 * width + H - 1
        p_bot_right = width + H
        bottom = Text("╰", style=self._beam_style(p_bot_left, P, phase))
        for index in range(inner):
            x = index + 1
            p = width + H + (width - 1 - x)
            bottom.append("─", style=self._beam_style(p, P, phase))
        bottom.append("╯", style=self._beam_style(p_bot_right, P, phase))
        yield bottom


def build_cyber_deck(
    view: WakerViewModel,
    *,
    compact: bool = False,
    frame: int = 0,
    fx: bool = True,
):
    """Render the approved v2.2 two-column Cyber-Deck from a ViewModel."""
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    def task_panel() -> Panel:
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(width=2)
        table.add_column(ratio=1)
        table.add_column(width=6, justify="right")
        table.add_column(width=8, justify="right")
        table.add_column(width=13, justify="right")
        if not view.tasks:
            table.add_row("○", Text("No tasks in contract", style=_DECK_MUTED), "")
        for task in view.tasks:
            if task.status == "done":
                icon = "✓"
                color = _DECK_MINT
            elif task.status == "failed":
                icon = "✖"
                color = _DECK_RED
            elif task.status == "blocked":
                icon = "⏸"
                color = _DECK_YELLOW
            else:
                icon = SPINNER[frame % len(SPINNER)]
                color = _DECK_BLUE
            grade = task.grade or "—"
            warn = f"{task.errors}err · {task.warnings}warn"
            label = Text(
                f"{task.id}  {_short(task.desc, 34)}", style=_DECK_TEXT
            )
            if task.diffs:
                path, added, deleted = max(task.diffs, key=lambda item: item[1])
                label.append(
                    f"\n   {path.rsplit('/', 1)[-1]} +{added} -{deleted}"
                    f" · {len(task.diffs)} files",
                    style=_DECK_MUTED,
                )
            elif task.files:
                label.append(
                    f"\n   {len(task.files)} files · +{task.added} -{task.deleted}",
                    style=_DECK_MUTED,
                )
            table.add_row(
                Text(icon, style=f"bold {color}"),
                label,
                Text(f"{task.percent}%", style=_DECK_GREEN if task.percent == 100 else _DECK_YELLOW),
                Text(grade, style=_DECK_MUTED),
                Text(warn, style=_DECK_YELLOW if task.warnings else _DECK_MUTED),
            )
        return Panel(
            table,
            title="[bold]PIPELINE TASKS[/]",
            title_align="left",
            border_style=_DECK_BORDER,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def telemetry_panel() -> Panel:
        test = view.ledger.get("test") or {}
        test_exit = test.get("exit_code")
        test_label = "—" if test_exit is None else (
            f"PASS · exit {test_exit}" if test_exit == 0 else f"FAIL · exit {test_exit}"
        )
        test_color = _DECK_GREEN if test_exit == 0 else (_DECK_RED if test_exit is not None else _DECK_MUTED)
        status = "DONE" if view.state.status == "DONE" else ("SLOP" if view.state.diagnosis == "SLOP" else view.state.status.upper())
        status_color = _DECK_GREEN if status == "DONE" else (_DECK_RED if status == "SLOP" else _DECK_BLUE)
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(width=13)
        table.add_column(ratio=1)
        quality = Text()
        quality.append_text(_deck_bar(view.score, frame=frame, fx=fx))
        quality.append(f"  {view.score}/100 [{view.grade}]", style=f"bold {_DECK_GREEN if view.score >= 90 else (_DECK_YELLOW if view.score >= 70 else _DECK_RED)}")
        table.add_row(Text("CLEANLINESS", style=_DECK_MUTED), quality)
        table.add_row(Text("KICKS", style=_DECK_MUTED), Text(f"{view.state.kicks}/{view.state.max_kicks}", style=_DECK_RED if view.state.diagnosis == "SLOP" else _DECK_GREEN))
        table.add_row(Text("TEST SUITE", style=_DECK_MUTED), Text(test_label, style=f"bold {test_color}"))
        table.add_row(Text("COST", style=_DECK_MUTED), Text(f"${view.state.cost_usd:.4f}", style=_DECK_ORANGE))
        table.add_row(Text("STATUS", style=_DECK_MUTED), Text(status, style=f"bold {status_color}"))
        if view.out_of_scope:
            table.add_row(Text("SCOPE", style=_DECK_MUTED), Text(f"{len(view.out_of_scope)} out-of-scope", style=_DECK_RED))
        else:
            table.add_row(Text("SCOPE", style=_DECK_MUTED), Text("0 out-of-scope", style=_DECK_GREEN))
        rule_text = Text()
        rules = _deck_rule_counts(view)
        if rules:
            for index, (rule, count) in enumerate(rules[:4]):
                prefix = "├─" if index < min(3, len(rules) - 1) else "╰─"
                rule_text.append(f"{prefix} {rule}  ×{count}\n", style=_DECK_YELLOW)
        else:
            rule_text.append("clean", style=_DECK_GREEN)
        return Panel(
            Group(table, Text(""), Text("ANTI-SLOP SHIELD", style=f"bold {_DECK_MUTED}"), rule_text),
            title="[bold]WATCHDOG TELEMETRY[/]",
            title_align="left",
            border_style=_DECK_BORDER,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def event_panel() -> Panel:
        lines = Text()
        if view.events:
            for event in view.events[-4:]:
                color = _DECK_GREEN if event.label == "DONE" else _DECK_RED
                lines.append(f"{event.timestamp}  ", style=_DECK_MUTED)
                lines.append(f"{event.label:<5}", style=f"bold {color}")
                lines.append(f"  {event.message}\n", style=_DECK_TEXT)
        else:
            lines.append("Waiting for the first event…", style=_DECK_MUTED)
        if view.fail_log:
            lines.append("\nFAIL LOG  ", style=f"bold {_DECK_RED}")
            lines.append(" · ".join(view.fail_log[:3]), style=_DECK_TEXT)
        if fx and view.state.status == "running" and view.events:
            spark = ("✦ * · .", "✧ · * .", "· ✦ . *")[frame % 3]
            lines.append(f"\n{spark}", style=_DECK_ORANGE)
        return Panel(
            lines,
            title="[bold]⚡ REALTIME EVENT STREAM[/]",
            title_align="left",
            border_style=_DECK_BORDER,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    header = Text()
    header.append("WAKER SUPERVISOR", style=f"bold {_DECK_TEXT}")
    header.append("  v2.2  ·  ", style=_DECK_MUTED)
    header.append(f"run {view.state.run_id}", style=_DECK_MUTED)
    if compact:
        header.append(f"\n⏱ {fmt_duration(view.state.elapsed)}", style=_DECK_CYAN)
        header.append(f"  ·  Agent: {view.agent}", style=_DECK_MUTED)
    else:
        header.append(f"  ·  ⏱ {fmt_duration(view.state.elapsed)}", style=_DECK_CYAN)
        header.append(f"  ·  Agent: {view.agent}", style=_DECK_MUTED)
    goal = Text()
    goal.append("Goal: ", style=f"bold {_DECK_MUTED}")
    goal.append(view.goal, style=_DECK_TEXT)
    footer = Text()
    footer.append("[q] Quit  ", style=_DECK_MUTED)
    footer.append("[p] Pause  ", style=_DECK_MUTED)
    footer.append("[v] Diff  ", style=_DECK_MUTED)
    footer.append("[l] Full Log", style=_DECK_MUTED)
    title = Text("✨ WAKER CYBER-DECK", style=f"bold {_DECK_CYAN}")
    main = Table.grid(expand=True, padding=(0, 1))
    if compact:
        main.add_column(ratio=1)
        main.add_row(task_panel())
        main.add_row(Text(""))
        main.add_row(telemetry_panel())
    else:
        main.add_column(ratio=3)
        main.add_column(ratio=2)
        main.add_row(task_panel(), telemetry_panel())
    body = Group(
        title,
        Panel(Group(header, goal), box=box.ROUNDED, border_style=_DECK_BORDER, padding=(0, 1)),
        Text(""),
        main,
        Text(""),
        event_panel(),
        Text(""),
        footer,
    )
    if view.state.status == "DONE":
        border_style = _DECK_GREEN
        beam_active = False
    elif view.state.status in ("FAILED", "BLOCKED") or any(task.status == "failed" for task in view.tasks):
        border_style = _DECK_RED
        beam_active = False
    else:
        border_style = _DECK_BORDER
        beam_active = fx and (view.state.status == "running" or not view.state.status)

    return BeamPanel(
        body,
        border_style=border_style,
        beam=beam_active,
        frame=frame,
    )


def load_latest(repo: str | Path) -> tuple[RunState, dict[str, Any], RunPaths]:
    from .state import latest_run

    run_id = latest_run(repo)
    if not run_id:
        raise FileNotFoundError("no runs in .waker/runs")
    paths = RunPaths(repo, run_id)
    state = RunState.load(paths.state)
    ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
    return state, ledger, paths


def watch(
    repo: str | Path,
    run_id: str | None = None,
    interval: float = 1.0,
    *,
    no_fx: bool = False,
    mini: bool = False,
) -> None:
    from rich.console import Console
    from rich.live import Live

    paths = RunPaths(repo, run_id) if run_id else load_latest(repo)[2]
    view = WakerViewModel.from_paths(paths)
    if mini or not sys.stdout.isatty():
        print(mini_line(view))
        return
    console = Console()
    compact = console.width < 100
    fx = fx_enabled(no_fx)
    last_poll = 0.0
    frame = 0
    with Live(
        build_cyber_deck(view, compact=compact, frame=frame, fx=fx),
        console=console,
        refresh_per_second=10,
        transient=False,
    ) as live:
        while True:
            if not paths.state.exists():
                break
            now = time.monotonic()
            if now - last_poll >= max(0.2, interval):
                view = WakerViewModel.from_paths(paths)
                last_poll = now
            frame += 1
            live.update(
                build_cyber_deck(view, compact=compact, frame=frame, fx=fx),
                refresh=True,
            )
            if view.state.status != "running":
                break
            time.sleep(0.1)
