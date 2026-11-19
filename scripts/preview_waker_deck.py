"""Terminal design preview for the Waker v2.2 living dashboard.

This is a visual prototype, not the production `waker watch` command yet.
It replays the real b81c627e run shape (SLOP -> SLOP -> DONE) with a live
clock, live cost counter, spinner, and event stream.

Run:
    .venv\\Scripts\\python.exe scripts\\preview_waker_deck.py
    .venv\\Scripts\\python.exe scripts\\preview_waker_deck.py --once
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Ensure src is in python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from waker.ui import BeamPanel

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Tokyo Night-ish tokens; Rich degrades to 256/16 colors automatically.
BG = "#1a1b26"
PANEL = "#1f2335"
BORDER = "#3b4261"
TEXT = "#c0caf5"
MUTED = "#565f89"
BLUE = "#7aa2f7"
CYAN = "#7dcfff"
GREEN = "#9ece6a"
MINT = "#73daca"
RED = "#f7768e"
YELLOW = "#e0af68"
ORANGE = "#ff9e64"

RUN_ID = "b81c627e"
AGENT = "OpenCode · deepseek-v4.1-flash"
GOAL = "Implement a small Todo CLI in src/todo"
TASK = "T1 · Todo CLI core"
SCOPE = "src/todo/ · 4 files"
FINAL_SECONDS = 151.65
FINAL_COST = 0.006879814

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
EVENTS = [
    ("07:53:42", "SLOP", "kick 0 · TYPE002 ×4 in store.py"),
    ("07:54:21", "SLOP", "kick 1 · TYPE001 remains in store.py"),
    ("07:55:02", "DONE", "kick 2 · 0 errors · report.md committed"),
]


@dataclass(frozen=True)
class Phase:
    start: float
    kick: int
    status: str
    score: int
    grade: str
    errors: int
    warnings: int
    attempt: int


PHASES = [
    Phase(0.0, 0, "SLOP", 57, "F", 4, 1, 0),
    Phase(4.0, 1, "SLOP", 66, "D", 1, 8, 1),
    Phase(8.0, 2, "DONE", 76, "C", 0, 8, 2),
]


def fmt_time(seconds: float) -> str:
    value = max(0, int(seconds))
    return f"{value // 60:02d}:{value % 60:02d}"


def phase_at(now: float) -> Phase:
    phase = PHASES[0]
    for candidate in PHASES:
        if now >= candidate.start:
            phase = candidate
    return phase


def status_color(status: str):
    if status == "DONE":
        return GREEN
    if status == "SLOP":
        return RED
    return YELLOW


def quality_bar(score: int, width: int = 10) -> Text:
    filled = int(round(width * score / 100))
    bar = Text()
    # A moving highlight makes the live counter visibly alive.
    tick = int(time.monotonic() * 8) % max(1, filled or 1)
    for index in range(width):
        if index < filled:
            style = f"bold {CYAN}" if index == tick and filled else BLUE
            bar.append("▰", style=style)
        else:
            bar.append("▱", style=BORDER)
    return bar


def header(phase: Phase, elapsed: float, compact: bool = False) -> Panel:
    line = Text()
    line.append("WAKER SUPERVISOR", style=f"bold {TEXT}")
    line.append("  v2.2", style=MUTED)
    line.append(f"   run {RUN_ID}", style=MUTED)
    line.append(f"   ⏱ {fmt_time(elapsed)}", style=CYAN)
    line.append(f"   Agent: {AGENT}", style=MUTED)
    if compact:
        line = Text()
        line.append("WAKER SUPERVISOR", style=f"bold {TEXT}")
        line.append(f"  v2.2  ·  run {RUN_ID}\n", style=MUTED)
        line.append(f"⏱ {fmt_time(elapsed)}", style=CYAN)
        line.append(f"  ·  Agent: {AGENT}", style=MUTED)
    return Panel(line, box=box.ROUNDED, border_style=BORDER, padding=(0, 1))


def task_panel(phase: Phase, frame: str) -> Panel:
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=1)
    table.add_column(width=8, justify="right")
    table.add_column(width=10, justify="right")
    icon = "✅" if phase.status == "DONE" else frame
    color = GREEN if phase.status == "DONE" else BLUE
    table.add_row(
        Text(f"{icon}  {TASK}", style=f"bold {color}"),
        Text("100%", style=GREEN),
        Text(f"attempt {phase.attempt}", style=MUTED),
    )
    table.add_row(
        Text(f"   scope  {SCOPE}", style=MUTED),
        Text(""),
        Text(""),
    )
    table.add_row(
        Text("   diff   0 out-of-scope", style=MUTED),
        Text(""),
        Text(""),
    )
    return Panel(
        table,
        title="[bold]PIPELINE TASKS (1/1)[/]",
        title_align="left",
        border_style=BORDER,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def telemetry_panel(phase: Phase, elapsed: float, cost: float) -> Panel:
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=13)
    table.add_column(ratio=1)
    bar = quality_bar(phase.score)
    quality = Text()
    quality.append_text(bar)
    quality.append(f"  {phase.score}/100 ", style=f"bold {status_color(phase.status)}")
    quality.append(f"[{phase.grade}]", style=MUTED)
    status = phase.status if phase.status == "DONE" else "RUNNING"
    table.add_row(Text("CLEANLINESS", style=MUTED), quality)
    table.add_row(
        Text("KICKS", style=MUTED),
        Text(f"{phase.kick}/5", style=RED if phase.status == "SLOP" else GREEN),
    )
    table.add_row(
        Text("TEST SUITE", style=MUTED),
        Text("PASS · exit 0", style=GREEN),
    )
    table.add_row(
        Text("COST", style=MUTED),
        Text(f"${cost:.4f}", style=ORANGE),
    )
    table.add_row(
        Text("STATUS", style=MUTED),
        Text(status, style=f"bold {status_color(phase.status)}"),
    )
    table.add_row(
        Text("ANTI-SLOP", style=MUTED),
        Text("TYPE006 ×7 · TYPE012 ×1", style=YELLOW),
    )
    return Panel(
        table,
        title="[bold]WATCHDOG TELEMETRY[/]",
        title_align="left",
        border_style=BORDER,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def event_panel(phase: Phase, elapsed: float) -> Panel:
    lines = Text()
    count = max(1, min(len(EVENTS), phase.kick + 1))
    for timestamp, label, message in EVENTS[max(0, count - 2):count]:
        color = GREEN if label == "DONE" else RED
        lines.append(f"{timestamp}  ", style=MUTED)
        lines.append(f"{label:<4}", style=f"bold {color}")
        lines.append(f"  {message}\n", style=TEXT)
    if phase.status != "DONE":
        lines.append("⠋  ", style=CYAN)
        lines.append("Evaluating next AST boundary…", style=MUTED)
    else:
        lines.append("✓  ", style=GREEN)
        lines.append("Gate green · no further kick", style=GREEN)
    return Panel(
        lines,
        title="[bold]⚡ REALTIME EVENT STREAM[/]",
        title_align="left",
        border_style=BORDER,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render(
    phase: Phase,
    elapsed: float,
    cost: float,
    frame: str,
    compact: bool = False,
    frame_idx: int = 0,
):
    main = Table.grid(expand=True, padding=(0, 1))
    if compact:
        main.add_column(ratio=1)
        main.add_row(task_panel(phase, frame))
        main.add_row(Text(""))
        main.add_row(telemetry_panel(phase, elapsed, cost))
    else:
        main.add_column(ratio=3)
        main.add_column(ratio=2)
        main.add_row(task_panel(phase, frame), telemetry_panel(phase, elapsed, cost))
    footer = Text()
    footer.append("[q] Quit  ", style=MUTED)
    footer.append("[p] Pause  ", style=MUTED)
    footer.append("[v] View Diff  ", style=MUTED)
    footer.append("[l] Full Log", style=MUTED)
    body = Group(
        header(phase, elapsed, compact=compact),
        main,
        event_panel(phase, elapsed),
        footer,
    )
    border_style = (
        GREEN
        if phase.status == "DONE"
        else BORDER
    )
    is_running = phase.status != "DONE"
    return BeamPanel(
        body,
        border_style=border_style,
        beam=is_running,
        frame=frame_idx,
    )


def run_once(width: int | None) -> None:
    phase = PHASES[-1]
    console = Console(width=width)
    console.print(render(phase, FINAL_SECONDS, FINAL_COST, "✓", compact=console.width < 100, frame_idx=0))


def run_live(
    speed: float,
    width: int | None,
    loop: bool = True,
    infinite: bool = False,
) -> None:
    console = Console(width=width)
    console.clear()
    compact = console.width < 100
    frame_idx = 0
    try:
        while True:
            started = time.monotonic()
            with Live(
                render(PHASES[0], 0, 0, SPINNER[0], compact=compact, frame_idx=0),
                console=console,
                refresh_per_second=10,
                transient=False,
            ) as live:
                while True:
                    now = (time.monotonic() - started) * speed
                    if infinite:
                        phase = PHASES[1]
                        elapsed = (time.monotonic() - started) * speed
                        cost = min(FINAL_COST, 0.001 + (elapsed / 30.0) * 0.005)
                    else:
                        phase = phase_at(now)
                        if now >= 12.5:
                            break
                        elapsed = min(FINAL_SECONDS, now / 12.5 * FINAL_SECONDS)
                        progress = min(1.0, now / 12.5)
                        cost = min(FINAL_COST, FINAL_COST * progress)

                    frame = SPINNER[int(time.monotonic() * 10) % len(SPINNER)]
                    frame_idx += 1
                    live.update(
                        render(phase, elapsed, cost, frame, compact=compact, frame_idx=frame_idx),
                        refresh=True,
                    )
                    time.sleep(0.08)

                # Show DONE state
                live.update(
                    render(PHASES[-1], FINAL_SECONDS, FINAL_COST, "✓", compact=compact, frame_idx=frame_idx),
                    refresh=True,
                )
                time.sleep(2.5)
            if not loop or infinite:
                break
    except KeyboardInterrupt:
        pass


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="print the final frame only")
    parser.add_argument("--speed", type=float, default=1.0, help="replay speed (default 1x)")
    parser.add_argument(
        "--width",
        type=int,
        default=120,
        help="preview width in columns (default 120; use 80 for compact fallback)",
    )
    parser.add_argument("--no-loop", action="store_true", help="do not loop the replay")
    parser.add_argument(
        "--infinite",
        action="store_true",
        help="keep running continuously in RUNNING state to observe Border Beam glow",
    )
    args = parser.parse_args()
    width = args.width if args.width > 0 else None
    if args.once:
        run_once(width)
    else:
        run_live(max(0.1, args.speed), width, loop=not args.no_loop, infinite=args.infinite)


if __name__ == "__main__":
    main()
