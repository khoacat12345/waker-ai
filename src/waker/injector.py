"""Wake-up prompt construction.

Every sentence is a fact read from disk or from the test output. No LLM writes
these prompts - that is the whole point.
"""

from __future__ import annotations

from .models import Diagnosis, Failure, Task
from .state import done_ids

MAX_FAILURES = 5


def _task_line(task: Task) -> str:
    scope = ", ".join(task.scope) if task.scope else "(chưa khai báo scope)"
    verify = task.command or "(chưa khai báo verify)"
    return f"- {task.id}: {task.desc} -> cần thay đổi trong {scope}; verify: {verify}"


def build_initial_prompt(
    tasks: list[Task],
    constraints: list[Task],
    preferences: list[str],
    test_command: str | None,
) -> str:
    lines = ["[waker] Bắt đầu run. Hợp đồng công việc:"]
    for task in tasks:
        lines.append(_task_line(task))
        if task.public_api:
            lines.append("  public API:")
            lines.extend(f"  - {item}" for item in task.public_api)
        if task.blind:
            lines.append("  hidden tests: có (không hiển thị; phải pass 100%)")
    if constraints:
        lines.append("")
        lines.append("RÀNG BUỘC (không được vi phạm):")
        for constraint in constraints:
            check = constraint.command or "(chưa có check)"
            lines.append(f"- {constraint.id}: {constraint.desc} (check: {check})")
    if preferences:
        lines.append("")
        lines.append("Sở thích (không chấm bằng máy, chỉ để tham khảo):")
        lines.extend(f"- {pref}" for pref in preferences)
    lines.append("")
    lines.append("Quy tắc:")
    lines.append("1. Không sửa file test. Không thêm skip/xfail.")
    lines.append("2. Chỉ báo xong khi mọi task có thay đổi thật trong scope của nó.")
    if test_command:
        lines.append(f"3. Trước khi báo xong, chạy: {test_command}")
    lines.append("4. Nếu bị chặn thật sự, in đúng một dòng: BLOCKED: <lý do>")
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
    lines = [f"[waker kick {kick}/{max_kicks}] lý do: {diagnosis.value}", ""]

    lines.append(f"ĐÃ XONG: {', '.join(sorted(done)) or 'chưa có'}")
    if missing:
        lines.append("CHƯA XONG:")
        for task in missing:
            lines.append(_task_line(task))
    else:
        lines.append("CHƯA XONG: (không còn task nào thiếu scope)")

    if failures:
        lines.append("")
        lines.append(f"Test đang đỏ ({len(failures)} lỗi):")
        for failure in failures[:MAX_FAILURES]:
            message = f" - {failure.message}" if failure.message else ""
            lines.append(f"- {failure.label()}{message}")

    if constraints:
        lines.append("")
        lines.append("Nhắc lại ràng buộc:")
        for constraint in constraints:
            lines.append(f"- {constraint.desc}")

    if hidden_summary:
        lines.append("")
        lines.append("Hidden suite:")
        lines.extend(f"- {item}" for item in hidden_summary)
    if hidden_failures:
        lines.append("")
        lines.append("Hidden failures (đã lọc, không có source):")
        lines.extend(f"- {item}" for item in hidden_failures[:5])

    if notes:
        lines.append("")
        lines.extend(notes)

    lines.append("")
    if missing:
        lines.append(f"Việc phải làm ngay: {missing[0].id} - {missing[0].desc}")
    lines.append("Không được sửa file test. Không thêm skip/xfail.")
    if test_command:
        lines.append(f"Xong thì chạy: {test_command}")
    lines.append("Nếu bị chặn thật: in đúng 1 dòng BLOCKED: <lý do>")
    return "\n".join(lines)


def failure_summary(failures: list[Failure]) -> str:
    if not failures:
        return "không có lỗi"
    first = failures[0]
    return f"{first.label()} {first.message}".strip()
