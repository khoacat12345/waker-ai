"""Deterministic planner: prompt -> 4 buckets -> contract.

No LLM, no network, no token. The four buckets are:

* **work**       - something that must be built
* **constraint** - a rule that must never be violated (negative gate)
* **preference** - taste; cannot be machine-verified
* **unknown**    - needs a human answer before the run may start

The parser is intentionally conservative: it refuses to invent ``scope`` or
``verify``. Missing fields are reported by :func:`lint_tasks` so the run fails
closed instead of grading against a meaningless contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from . import globs
from .models import PlanBundle, Question, Task

BULLET_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
PHASE_RE = re.compile(
    r"^\s*(?:phase|giai\s*đoạn|buớc|bước|step)\s*([0-9]+)\s*[:.\-–]\s*(.*)$",
    re.IGNORECASE,
)
META_RE = re.compile(
    r"\b(scope|verify|test|check|phase|depends_on)\s*[:=]\s*"
    r"(.+?)(?=(?:\s+(?:scope|verify|test|check|phase|depends_on)\s*[:=])|$)",
    re.IGNORECASE,
)

CONSTRAINT_MARKERS = (
    "đừng",
    "không được",
    "không dùng",
    "không sử dụng",
    "cấm",
    "tránh",
    "do not",
    "don't",
    "dont",
    "never use",
    "must not",
)
PREFERENCE_MARKERS = (
    "đẹp",
    "mượt",
    "nhanh",
    "thân thiện",
    "dễ dùng",
    "gọn gàng",
    "sạch sẽ",
    "clean",
    "nice",
    "beautiful",
    "smooth",
    "fast",
    "modern",
    "responsive",
    "ux",
    "ui",
)
CREDENTIAL_MARKERS = (
    "deploy",
    "token",
    "api key",
    "api_key",
    "apikey",
    "password",
    "mật khẩu",
    "secret",
    "credential",
    "chứng chỉ",
)
UNKNOWN_MARKERS = ("chưa rõ", "tbd", "chưa có", "chưa biết", "không rõ")

TRIVIAL_VERIFY = {"true", ":", "exit 0", "echo", "echo ok", "echo 0", "pass"}


class LintIssue:
    def __init__(self, level: str, task_id: str | None, message: str) -> None:
        self.level = level
        self.task_id = task_id
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "task_id": self.task_id, "message": self.message}

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        where = f"[{self.task_id}] " if self.task_id else ""
        return f"{self.level.upper()}: {where}{self.message}"


def _lower(text: str) -> str:
    return text.strip().lower()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    low = _lower(text)
    return any(marker in low for marker in markers)


def _split_units(prompt: str) -> list[str]:
    """Split a prompt into deterministic units.

    Multi-line prompts: one unit per line.
    Single-paragraph prompts: split on ``;`` and ``,`` so a messy sentence still
    yields several items - *unless* the line carries metadata (``scope:`` /
    ``verify:``), because those commas belong to the metadata values.
    """
    raw_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if len(raw_lines) > 1:
        return raw_lines
    if not raw_lines:
        return []
    line = raw_lines[0]
    if META_RE.search(line):
        return [line]
    parts = re.split(r"[;,]", line)
    return [part.strip() for part in parts if part.strip()]


def _extract_meta(text: str) -> tuple[str, dict[str, str]]:
    meta: dict[str, str] = {}
    for match in META_RE.finditer(text):
        meta[match.group(1).lower()] = match.group(2).strip()
    cleaned = META_RE.sub(" ", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-")
    return cleaned, meta


def _parse_scope(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _constraint_term(text: str) -> str | None:
    for pattern in (r"'([^']+)'", r'"([^"]+)"', r"\u201c([^\u201d]+)\u201d"):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    match = re.search(
        r"(?:dùng|sử dụng|use|using)\s+([A-Za-z0-9_.@/-]+)", text, re.IGNORECASE
    )
    return match.group(1) if match else None


def generate_constraint_check(term: str) -> str:
    """Build a portable Python one-liner that fails if *term* appears in the repo."""
    return (
        'python -c "import sys,pathlib;'
        f"t={term!r};"
        "skip={'.git','.venv','node_modules','__pycache__','.waker','dist','build'};"
        "bad=[str(p) for p in pathlib.Path('.').rglob('*') "
        "if p.is_file() and not any(x in skip for x in p.parts) "
        "and t in p.read_text(errors='ignore').lower()];"
        "print(chr(10).join(bad));"
        'sys.exit(1 if bad else 0)"'
    )


def parse_prompt(prompt: str) -> PlanBundle:
    """Parse a free-form prompt into the four buckets. Deterministic, 0 token."""
    bundle = PlanBundle()
    work_index = 0
    constraint_index = 0
    question_index = 0

    for raw in _split_units(prompt):
        unit = BULLET_RE.sub("", raw).strip()
        if not unit:
            continue

        phase = None
        phase_match = PHASE_RE.match(unit)
        if phase_match:
            phase = phase_match.group(1)
            unit = phase_match.group(2).strip()

        desc, meta = _extract_meta(unit)
        desc = desc.strip()
        if not desc and not meta:
            continue

        phase = meta.get("phase", phase)
        scope = _parse_scope(meta.get("scope"))
        verify = meta.get("verify") or meta.get("test")

        if _contains_any(desc, CONSTRAINT_MARKERS):
            constraint_index += 1
            term = _constraint_term(desc)
            check = meta.get("check") or (generate_constraint_check(term) if term else None)
            bundle.constraints.append(
                Task(
                    id=f"C{constraint_index}",
                    desc=desc,
                    kind="constraint",
                    check=check,
                    phase=phase,
                    source=[raw],
                )
            )
            continue

        if (
            desc.endswith("?")
            or _contains_any(desc, UNKNOWN_MARKERS)
            or _contains_any(desc, CREDENTIAL_MARKERS)
        ):
            question_index += 1
            kind = "credential" if _contains_any(desc, CREDENTIAL_MARKERS) else "clarify"
            bundle.questions.append(
                Question(
                    id=f"Q{question_index}",
                    kind=kind,
                    text=f"Cần làm rõ: {desc}",
                    options=[],
                )
            )
            continue

        if _contains_any(desc, PREFERENCE_MARKERS):
            bundle.preferences.append(desc)
            continue

        work_index += 1
        depends_on = [
            part.strip()
            for part in (meta.get("depends_on") or "").split(",")
            if part.strip()
        ]
        bundle.tasks.append(
            Task(
                id=f"T{work_index}",
                desc=desc,
                scope=scope or None or [],
                verify=verify,
                phase=phase,
                depends_on=depends_on,
                source=[raw],
            )
        )

    return bundle


def parse_plan_markdown(text: str) -> PlanBundle:
    """Parse the human-friendly ``plan.md`` contract format.

    ``## T1 - Auth`` followed by ``- scope: ...`` / ``- verify: ...`` lines.
    """
    bundle = PlanBundle()
    current: dict[str, Any] | None = None
    auto_work = 0
    auto_constraint = 0

    def flush() -> None:
        nonlocal current, auto_work, auto_constraint
        if current is None:
            return
        kind = current.get("kind", "work")
        if kind == "constraint":
            auto_constraint += 1
            task_id = current.get("id") or f"C{auto_constraint}"
        else:
            auto_work += 1
            task_id = current.get("id") or f"T{auto_work}"
        task = Task(
            id=task_id,
            desc=current.get("desc", ""),
            scope=current.get("scope", []),
            verify=current.get("verify"),
            check=current.get("check"),
            kind=kind,
            phase=current.get("phase"),
            depends_on=current.get("depends_on", []),
            test_writer=bool(current.get("test_writer")),
            source=[current.get("source", "")],
        )
        (bundle.constraints if kind == "constraint" else bundle.tasks).append(task)
        current = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            heading = stripped[3:].strip()
            phase = None
            phase_match = re.search(r"\(phase:\s*([^)]+)\)", heading, re.IGNORECASE)
            if phase_match:
                phase = phase_match.group(1).strip()
                heading = heading[: phase_match.start()].strip()
            id_match = re.match(r"^([TC]\d+)\s*[\u2014\-:\u2013]\s*(.+)$", heading)
            if id_match:
                task_id, desc = id_match.group(1), id_match.group(2)
            else:
                task_id, desc = None, heading
            current = {
                "id": task_id,
                "desc": desc,
                "phase": phase,
                "source": stripped,
                "kind": "constraint" if (task_id or "").startswith("C") else "work",
            }
            continue

        if current is None or not stripped.startswith(("-", "*")):
            continue

        item = stripped.lstrip("-* ").strip()
        key, _, value = item.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "scope":
            current["scope"] = _parse_scope(value)
        elif key in ("verify", "test"):
            current["verify"] = value
        elif key == "check":
            current["check"] = value
        elif key == "phase":
            current["phase"] = value
        elif key == "type":
            current["kind"] = "constraint" if value.lower() == "constraint" else "work"
        elif key == "test_writer":
            current["test_writer"] = value.lower() in ("1", "true", "yes")
        elif key == "depends_on":
            current["depends_on"] = [p.strip() for p in value.split(",") if p.strip()]
    flush()
    return bundle


def render_yaml(bundle: PlanBundle) -> str:
    payload: dict[str, Any] = {
        "tasks": [t.to_dict() for t in bundle.all_tasks()],
    }
    if bundle.preferences:
        payload["preferences"] = bundle.preferences
    if bundle.questions:
        payload["questions"] = [q.to_dict() for q in bundle.questions]
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def load_tasks(path: str | Path) -> list[Task]:
    """Load tasks from YAML. Accepts a list or a ``tasks:`` mapping."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or []
    if isinstance(raw, dict):
        items = raw.get("tasks") or raw.get("constraints") or []
    else:
        items = raw
    return [Task.from_dict(item) for item in items]


def parse_contract_text(text: str) -> PlanBundle:
    """Parse a YAML document (as returned by an LLM planner)."""
    raw = yaml.safe_load(text) or []
    if isinstance(raw, dict):
        items = raw.get("tasks") or raw.get("constraints") or []
    else:
        items = raw
    tasks = [Task.from_dict(item) for item in items if isinstance(item, dict)]
    return PlanBundle(
        tasks=[task for task in tasks if task.kind == "work"],
        constraints=[task for task in tasks if task.kind != "work"],
    )


def write_tasks(path: str | Path, bundle: PlanBundle) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(render_yaml(bundle), encoding="utf-8")


def _repo_files(repo: str | Path) -> list[str]:
    import subprocess

    root = Path(repo)
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
        files = (tracked + untracked).splitlines()
        if files:
            return [globs.normalize(f) for f in files if f.strip()]
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - git missing
        pass
    return [
        globs.normalize(str(p.relative_to(root)))
        for p in root.rglob("*")
        if p.is_file()
    ]


def lint_tasks(tasks: list[Task], repo: str | Path | None = None) -> list[LintIssue]:
    """Mechanical contract validation. No LLM, no guessing."""
    issues: list[LintIssue] = []
    seen: dict[str, Task] = {}
    repo_files = _repo_files(repo) if repo else None

    for task in tasks:
        if task.id in seen:
            issues.append(LintIssue("error", task.id, "id bị trùng"))
        seen[task.id] = task

        if task.kind == "work":
            if not task.scope:
                issues.append(
                    LintIssue("error", task.id, "thiếu `scope` (không biết file nào thuộc task)")
                )
            if not task.verify:
                issues.append(
                    LintIssue("error", task.id, "thiếu `verify` (không có lệnh chứng minh xong)")
                )
        else:
            if not task.command:
                issues.append(
                    LintIssue("error", task.id, "constraint thiếu `check` hoặc `verify`")
                )

        command = (task.command or "").strip()
        if command:
            if command.lower() in TRIVIAL_VERIFY or command.lower().startswith("echo "):
                issues.append(
                    LintIssue(
                        "error",
                        task.id,
                        f"verify quá yếu (`{command}`) - không kiểm tra gì cả",
                    )
                )
            if repo_files is not None and "python -c" not in command:
                # Only warn for shell commands that look like test runners.
                lowered = command.lower()
                if any(token in lowered for token in ("pytest", "npm test", "go test", "cargo test")):
                    if not any("test" in f.lower() for f in repo_files):
                        issues.append(
                            LintIssue(
                                "warning",
                                task.id,
                                "không tìm thấy file test nào trong repo",
                            )
                        )

        if task.scope and repo_files is not None:
            # A concrete file that does not exist yet is a new artifact, not a
            # broken glob. Only warn for directory-ish / wildcard scopes.
            checkable = [
                pattern
                for pattern in task.scope
                if any(ch in pattern for ch in "*?[") or not Path(pattern).suffix
            ]
            if checkable:
                hits = [f for f in repo_files if globs.matches_any(f, checkable)]
                if not hits:
                    issues.append(
                        LintIssue(
                            "warning",
                            task.id,
                            f"scope không match file nào hiện có: {checkable}",
                        )
                    )

    work = [t for t in tasks if t.kind == "work" and t.scope]
    for index, left in enumerate(work):
        for right in work[index + 1 :]:
            for a in left.scope:
                for b in right.scope:
                    if globs.overlaps(a, b):
                        issues.append(
                            LintIssue(
                                "error",
                                left.id,
                                f"scope trùng với {right.id} (`{a}` ~ `{b}`) - không thể quy diff về task nào",
                            )
                        )
    return issues


def has_errors(issues: list[LintIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def format_issues(issues: list[LintIssue]) -> str:
    if not issues:
        return "OK: contract hợp lệ"
    return "\n".join(repr(issue) for issue in issues)


def load_contract(path: str | Path | None, prompt: str | None = None) -> PlanBundle:
    """Load a contract from YAML, or parse a prompt with the rules planner."""
    if path:
        tasks = load_tasks(path)
        return PlanBundle(
            tasks=[t for t in tasks if t.kind == "work"],
            constraints=[t for t in tasks if t.kind != "work"],
        )
    if prompt is None:
        raise ValueError("cần --tasks hoặc --prompt")
    return parse_prompt(prompt)
