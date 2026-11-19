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

from . import winproc

import re
from pathlib import Path
from typing import Any

import yaml

from . import globs
from .budget import DEFAULT_PROFILE, resolve_profile, validate_phase_budget
from .models import PhaseSpec, PlanBundle, Question, Task

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
                    text=f"Needs clarification: {desc}",
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


def _task_dicts(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw_items = [*(raw.get("tasks") or []), *(raw.get("constraints") or [])]
    else:
        raw_items = raw or []
    if not isinstance(raw_items, list):
        raise ValueError("contract `tasks` must be a list")
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("each contract task must be a mapping")
        items.append(item)
    return items


def _parse_phases(raw: Any) -> list[PhaseSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("contract `phases` must be a list")
    if not raw:
        raise ValueError("contract `phases` must contain at least one phase")
    phases: list[PhaseSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each contract phase must be a mapping")
        phases.append(PhaseSpec.from_dict(item))
    return phases


def _assign_default_phase(tasks: list[Task]) -> None:
    """Assign P1 only when a task has no phase.

    A task that already uses a custom phase id (for example ``"1"`` from the
    prompt parser) keeps it. Explicit-phase contracts are checked later so a
    missing ``P1`` declaration is a lint error instead of silent guessing.
    """
    for task in tasks:
        if not task.phase:
            task.phase = "P1"


def _bundle_from_raw(raw: Any) -> PlanBundle:
    tasks = [Task.from_dict(item) for item in _task_dicts(raw)]
    phases = _parse_phases(raw.get("phases") if isinstance(raw, dict) else None)
    _assign_default_phase(tasks)
    profile = None
    if isinstance(raw, dict) and raw.get("profile") is not None:
        if not isinstance(raw["profile"], str) or not raw["profile"].strip():
            raise ValueError("contract `profile` must be a non-empty string")
        profile = raw["profile"].strip().lower()
    return PlanBundle(
        tasks=[task for task in tasks if task.kind == "work"],
        constraints=[task for task in tasks if task.kind != "work"],
        profile=profile,
        phases=phases,
    )


def _phase_hint(task: Task) -> str:
    if task.phase:
        return str(task.phase)
    for pattern in task.scope:
        parts = [
            part
            for part in pattern.replace("\\", "/").strip().split("/")
            if part and part not in ("*", "**")
        ]
        if not parts:
            continue
        if parts[0].lower() in {"src", "tests", "test", "docs", "app", "lib"} and len(parts) > 1:
            return parts[1]
        return parts[0]
    return "P1"


def _phase_name(hint: str, index: int) -> str:
    cleaned = re.sub(r"[_-]+", " ", hint).strip()
    if not cleaned or cleaned.lower() in {"p1", "1"}:
        return f"Phase {index}"
    return cleaned.title()


def _format_budget(seconds: int) -> str:
    if seconds > 0 and seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds > 0 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def propose_phases(
    bundle: PlanBundle,
    profile: str = DEFAULT_PROFILE,
) -> PlanBundle:
    """Build deterministic phase proposals from task phases/scopes.

    This is the rule-based ``--phases auto`` path. It never invents scope or
    verify; it only groups existing tasks and allocates a fraction of the
    profile's wall-clock budget to each group.
    """
    tasks = bundle.all_tasks()
    if not tasks:
        return bundle

    hints = [_phase_hint(task) for task in tasks]
    groups: dict[str, list[Task]] = {}
    for task, hint in zip(tasks, hints):
        groups.setdefault(hint, []).append(task)

    ordered = list(groups)
    if len(ordered) > 6:
        kept = ordered[:5]
        for hint in ordered[5:]:
            groups.setdefault("other", []).extend(groups.pop(hint))
        ordered = [*kept, "other"]

    resolved = resolve_profile(profile)
    available = max(0, int(resolved.max_wall_clock * (1 - 0.15)))
    total = len(tasks)
    phase_by_hint = {hint: f"P{index}" for index, hint in enumerate(ordered, 1)}
    phases: list[PhaseSpec] = []
    for index, hint in enumerate(ordered, 1):
        count = len(groups[hint])
        budget = int(available * count / total) if total else 0
        phases.append(
            PhaseSpec(
                id=phase_by_hint[hint],
                name=_phase_name(hint, index),
                budget=_format_budget(budget),
            )
        )

    for task, hint in zip(tasks, hints):
        target = "other" if hint not in phase_by_hint else hint
        task.phase = phase_by_hint.get(target, "P1")

    bundle.profile = resolved.name
    bundle.phases = phases
    return bundle


def apply_phase_mode(
    bundle: PlanBundle,
    mode: str,
    profile: str | None = None,
) -> PlanBundle:
    """Apply ``--phases none|manual|auto`` to a freshly parsed bundle."""
    if mode not in {"none", "manual", "auto"}:
        raise ValueError(f"unknown phase mode: {mode}")

    if mode == "auto":
        if bundle.phases:
            if profile:
                bundle.profile = profile
            _assign_default_phase(bundle.all_tasks())
            return bundle
        return propose_phases(bundle, profile or bundle.profile or DEFAULT_PROFILE)

    if mode == "none":
        bundle.phases = []
        for task in bundle.all_tasks():
            task.phase = "P1"
        if profile:
            bundle.profile = profile
        return bundle

    if profile:
        bundle.profile = profile
    _assign_default_phase(bundle.all_tasks())
    return bundle


def render_yaml(bundle: PlanBundle) -> str:
    payload: dict[str, Any] = {}
    if bundle.profile:
        payload["profile"] = bundle.profile
    if bundle.phases:
        payload["phases"] = [phase.to_dict() for phase in bundle.phases]
    payload["tasks"] = [t.to_dict() for t in bundle.all_tasks()]
    if bundle.preferences:
        payload["preferences"] = bundle.preferences
    if bundle.questions:
        payload["questions"] = [q.to_dict() for q in bundle.questions]
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def load_tasks(path: str | Path) -> list[Task]:
    """Load tasks from YAML. Accepts a list or a ``tasks:`` mapping.

    Legacy contracts without ``phases`` still load; tasks without a phase get
    the implicit ``P1`` default.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or []
    bundle = _bundle_from_raw(raw)
    return bundle.all_tasks()


def parse_contract_text(text: str) -> PlanBundle:
    """Parse a YAML document (as returned by an LLM planner)."""
    raw = yaml.safe_load(text) or []
    return _bundle_from_raw(raw)


def write_tasks(path: str | Path, bundle: PlanBundle) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(render_yaml(bundle), encoding="utf-8")


def _repo_files(repo: str | Path) -> list[str]:
    import subprocess

    root = Path(repo)
    try:
        tracked = winproc.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
        untracked = winproc.run(
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
            issues.append(LintIssue("error", task.id, "duplicate id"))
        seen[task.id] = task

        if task.kind == "work":
            if not task.scope:
                issues.append(
                    LintIssue("error", task.id, "missing `scope` (cannot tell which files belong to this task)")
                )
            if not task.verify:
                issues.append(
                    LintIssue("error", task.id, "missing `verify` (no command to prove completion)")
                )
        else:
            if not task.command:
                issues.append(
                    LintIssue("error", task.id, "constraint is missing `check` or `verify`")
                )

        if task.blind:
            if not isinstance(task.blind, dict):
                issues.append(LintIssue("error", task.id, "`blind` must be a mapping"))
            else:
                if not task.blind.get("suite"):
                    issues.append(LintIssue("error", task.id, "`blind.suite` is missing"))
                if task.blind.get("baseline", "red") not in ("red", "green"):
                    issues.append(
                        LintIssue("error", task.id, "`blind.baseline` must be red|green")
                    )
                if task.blind.get("leak", "message") not in ("minimal", "message"):
                    issues.append(
                        LintIssue("error", task.id, "`blind.leak` must be minimal|message")
                    )
                if not task.verify:
                    issues.append(
                        LintIssue(
                            "error",
                            task.id,
                            "blind task needs a public `verify` smoke test",
                        )
                    )

        command = (task.command or "").strip()
        if command:
            if command.lower() in TRIVIAL_VERIFY or command.lower().startswith("echo "):
                issues.append(
                    LintIssue(
                        "error",
                        task.id,
                        f"verify is too weak (`{command}`) - it checks nothing",
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
                                "no test files found in the repo",
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
                            f"scope matches no existing files: {checkable}",
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
                                f"scope overlaps with {right.id} (`{a}` ~ `{b}`) - cannot attribute the diff to a task",
                            )
                        )
    return issues


def _lint_phases(bundle: PlanBundle) -> list[LintIssue]:
    issues: list[LintIssue] = []
    phases = bundle.phases
    if len(phases) > 6:
        issues.append(LintIssue("error", None, "contract has more than 6 phases"))

    seen: set[str] = set()
    counts = {phase.id: 0 for phase in phases}
    valid_budgets: list[str | int | float] = []
    for phase in phases:
        if not phase.id or phase.id == "P?":
            issues.append(LintIssue("error", None, "phase is missing `id`"))
        elif phase.id in seen:
            issues.append(LintIssue("error", None, f"duplicate phase id `{phase.id}`"))
        else:
            seen.add(phase.id)

        if not phase.name.strip():
            issues.append(LintIssue("error", None, f"phase `{phase.id}` is missing `name`"))
        if phase.budget is None or phase.budget == "":
            issues.append(LintIssue("error", None, f"phase `{phase.id}` is missing `budget`"))
        else:
            try:
                phase.budget_seconds
            except ValueError as exc:
                issues.append(LintIssue("error", None, f"phase `{phase.id}`: {exc}"))
            else:
                valid_budgets.append(phase.budget)

    for task in bundle.all_tasks():
        if task.phase not in counts:
            issues.append(
                LintIssue(
                    "error",
                    task.id,
                    f"task phase `{task.phase}` is not declared in `phases`",
                )
            )
        else:
            counts[task.phase] += 1

    for phase in phases:
        if counts.get(phase.id, 0) == 0:
            issues.append(LintIssue("error", None, f"phase `{phase.id}` is empty"))

    if len(valid_budgets) == len(phases):
        try:
            validate_phase_budget(valid_budgets, bundle.profile or DEFAULT_PROFILE)
        except (TypeError, ValueError) as exc:
            issues.append(LintIssue("error", None, f"phase budget invalid: {exc}"))

    return issues


def lint_contract(
    bundle: PlanBundle,
    repo: str | Path | None = None,
) -> list[LintIssue]:
    """Validate tasks plus explicit phase metadata."""
    issues = lint_tasks(bundle.all_tasks(), repo=repo)
    if bundle.phases:
        issues.extend(_lint_phases(bundle))
    return issues


def has_errors(issues: list[LintIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def format_issues(issues: list[LintIssue]) -> str:
    if not issues:
        return "OK: contract is valid"
    return "\n".join(repr(issue) for issue in issues)


def load_contract(path: str | Path | None, prompt: str | None = None) -> PlanBundle:
    """Load a contract from YAML, or parse a prompt with the rules planner.

    Legacy YAML without ``phases`` loads unchanged; tasks without a phase are
    assigned the implicit ``P1``.
    """
    if path:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or []
        return _bundle_from_raw(raw)
    if prompt is None:
        raise ValueError("requires --tasks or --prompt")
    bundle = parse_prompt(prompt)
    _assign_default_phase(bundle.all_tasks())
    return bundle
