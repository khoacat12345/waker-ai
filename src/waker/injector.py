"""Wake-up prompt construction.

Every sentence is a fact read from disk or from the test output. No LLM writes
these prompts - that is the whole point.
"""

from __future__ import annotations

from .models import Diagnosis, Failure, Task
from .state import done_ids

MAX_FAILURES = 5


def _task_line(task: Task) -> str:
    scope = ", ".join(task.scope) if task.scope else "(scope not declared)"
    verify = task.command or "(verify not declared)"
    return f"- {task.id}: {task.desc} -> needs changes in {scope}; verify: {verify}"


def build_initial_prompt(
    tasks: list[Task],
    constraints: list[Task],
    preferences: list[str],
    test_command: str | None,
) -> str:
    lines = ["[waker] Starting run. Work contract:"]
    for task in tasks:
        lines.append(_task_line(task))
        if task.public_api:
            lines.append("  public API:")
            lines.extend(f"  - {item}" for item in task.public_api)
        if task.blind:
            lines.append("  hidden tests: present (not shown; must pass 100%)")
    if constraints:
        lines.append("")
        lines.append("CONSTRAINTS (must not violate):")
        for constraint in constraints:
            check = constraint.command or "(no check declared)"
            lines.append(f"- {constraint.id}: {constraint.desc} (check: {check})")
    if preferences:
        lines.append("")
        lines.append("Preferences (not machine-graded; reference only):")
        lines.extend(f"- {pref}" for pref in preferences)
    lines.append("")
    lines.append("Rules:")
    lines.append("1. Do not edit test files. Do not add skip/xfail.")
    lines.append("2. Only claim done when every task has real changes within its scope.")
    if test_command:
        lines.append(f"3. Before claiming done, run: {test_command}")
    lines.append("4. If truly blocked, print exactly one line: BLOCKED: <reason>")
    return "\n".join(lines)


def build_wake_prompt(
    diagnosis: Diagnosis,
    tasks: list[Task],
    constraints: list[Task],
    ledger: dict,
    failures: list[Failure],
    test_command: str | None,
    kick: int,
    max_kicks: int,
    notes: list[str] | None = None,
    hidden_failures: list[str] | None = None,
    hidden_summary: list[str] | None = None,
) -> str:
    done = set(done_ids(ledger))
    missing = [task for task in tasks if task.id not in done]
    lines = [f"[waker kick {kick}/{max_kicks}] reason: {diagnosis.value}", ""]

    lines.append(f"DONE: {', '.join(sorted(done)) or 'none yet'}")
    if missing:
        lines.append("NOT DONE:")
        for task in missing:
            lines.append(_task_line(task))
    else:
        lines.append("NOT DONE: (no tasks missing scope)")

    if failures:
        lines.append("")
        lines.append(f"Tests are red ({len(failures)} failures):")
        for failure in failures[:MAX_FAILURES]:
            message = f" - {failure.message}" if failure.message else ""
            lines.append(f"- {failure.label()}{message}")

    if constraints:
        lines.append("")
        lines.append("Constraints reminder:")
        for constraint in constraints:
            lines.append(f"- {constraint.desc}")

    if hidden_summary:
        lines.append("")
        lines.append("Hidden suite:")
        lines.extend(f"- {item}" for item in hidden_summary)
    if hidden_failures:
        lines.append("")
        lines.append("Hidden failures (sanitized, no source):")
        lines.extend(f"- {item}" for item in hidden_failures[:5])

    if notes:
        lines.append("")
        lines.extend(notes)

    lines.append("")
    if missing:
        lines.append(f"Next action: {missing[0].id} - {missing[0].desc}")
    lines.append("Do not edit test files. Do not add skip/xfail.")
    if test_command:
        lines.append(f"When done, run: {test_command}")
    lines.append("If truly blocked: print exactly one line: BLOCKED: <reason>")
    return "\n".join(lines)


def failure_summary(failures: list[Failure]) -> str:
    if not failures:
        return "no failures"
    first = failures[0]
    return f"{first.label()} {first.message}".strip()
