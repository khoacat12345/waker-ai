from __future__ import annotations

from pathlib import Path

import pytest

from waker import evidence, planner
from waker.models import PhaseSpec, PlanBundle, Task


def test_four_buckets_are_separated():
    prompt = """
    Phase 1: module Auth, scope: src/auth/**, verify: pytest tests/auth -q
    Phase 2: module Payment
    đừng dùng tailwind
    giao diện phải đẹp và mượt
    deploy lên vercel
    """
    bundle = planner.parse_prompt(prompt)

    assert len(bundle.tasks) == 2
    assert bundle.tasks[0].phase == "1"
    assert bundle.tasks[0].scope == ["src/auth/**"]
    assert bundle.tasks[0].verify == "pytest tests/auth -q"
    assert bundle.tasks[1].verify is None

    assert len(bundle.constraints) == 1
    assert "tailwind" in (bundle.constraints[0].check or "")

    assert bundle.preferences
    assert bundle.questions
    assert bundle.questions[0].kind == "credential"


def test_prose_prompt_is_split_on_commas():
    bundle = planner.parse_prompt("làm login, làm giỏ hàng, viết docs")
    assert [t.desc for t in bundle.tasks] == ["làm login", "làm giỏ hàng", "viết docs"]


def test_meta_is_extracted_without_polluting_desc():
    bundle = planner.parse_prompt(
        "Phase 3: viết docs, scope: docs/**, verify: grep -q Auth docs/README.md"
    )
    task = bundle.tasks[0]
    assert task.desc == "viết docs"
    assert task.phase == "3"
    assert task.scope == ["docs/**"]
    assert task.verify.startswith("grep")


def test_generated_constraint_check_actually_runs(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"dependencies": {"tailwindcss": "1"}}', encoding="utf-8")
    check = planner.generate_constraint_check("tailwind")
    assert evidence.run_command(check, tmp_path, timeout=30).exit_code == 1

    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert evidence.run_command(check, tmp_path, timeout=30).exit_code == 0


def test_lint_flags_missing_scope_and_verify():
    issues = planner.lint_tasks([Task(id="T1", desc="x")])
    messages = " ".join(issue.message for issue in issues)
    assert "scope" in messages
    assert "verify" in messages
    assert planner.has_errors(issues)


def test_lint_flags_trivial_verify():
    issues = planner.lint_tasks([Task(id="T1", desc="x", scope=["src/**"], verify="true")])
    assert any("too weak" in issue.message for issue in issues)


def test_lint_flags_duplicate_ids():
    issues = planner.lint_tasks(
        [
            Task(id="T1", desc="a", scope=["src/a/**"], verify="pytest a"),
            Task(id="T1", desc="b", scope=["src/b/**"], verify="pytest b"),
        ]
    )
    assert any("duplicate id" in issue.message for issue in issues)


def test_lint_flags_overlapping_scopes():
    issues = planner.lint_tasks(
        [
            Task(id="T1", desc="a", scope=["src/**"], verify="pytest a"),
            Task(id="T2", desc="b", scope=["src/pay/**"], verify="pytest b"),
        ]
    )
    assert any("cannot attribute the diff" in issue.message for issue in issues)


def test_lint_does_not_warn_for_new_concrete_file(repo):
    issues = planner.lint_tasks(
        [Task(id="T1", desc="x", scope=["src/new.txt"], verify="pytest -q")], repo=repo
    )
    assert not any("matches no existing" in issue.message for issue in issues)


def test_plan_markdown_format_is_parsed():
    text = """
# Plan
## T1 — Auth (phase: 1)
- scope: src/auth/**, tests/auth/**
- verify: pytest tests/auth -q

## T2 — No tailwind
- type: constraint
- check: "python -c \\"import sys;sys.exit(0)\\""
"""
    bundle = planner.parse_plan_markdown(text)
    assert [t.id for t in bundle.tasks] == ["T1"]
    assert bundle.tasks[0].scope == ["src/auth/**", "tests/auth/**"]
    assert bundle.constraints[0].kind == "constraint"


def test_yaml_roundtrip(tmp_path: Path):
    bundle = planner.parse_prompt(
        "Phase 1: auth, scope: src/auth/**, verify: pytest tests/auth -q"
    )
    out = tmp_path / "tasks.yaml"
    planner.write_tasks(out, bundle)
    loaded = planner.load_tasks(out)
    assert loaded[0].id == "T1"
    assert loaded[0].verify == "pytest tests/auth -q"
    assert loaded[0].scope == ["src/auth/**"]


def test_load_tasks_accepts_utf8_bom(tmp_path: Path):
    path = tmp_path / "tasks.yaml"
    path.write_bytes(
        b"\xef\xbb\xbftasks:\n  - id: T1\n    desc: x\n    scope: [\"src/**\"]\n    verify: pytest -q\n"
    )
    tasks = planner.load_tasks(path)
    assert tasks[0].id == "T1"
    assert tasks[0].desc == "x"


def test_blind_task_roundtrip(tmp_path: Path):
    task = Task(
        id="T1",
        desc="auth",
        scope=["src/auth/**"],
        verify="pytest tests/auth -q",
        public_api=["login(name, password) -> token"],
        blind={"suite": "auth", "baseline": "red", "timeout": 60, "leak": "message"},
    )
    out = tmp_path / "tasks.yaml"
    planner.write_tasks(out, planner.PlanBundle(tasks=[task]))
    loaded = planner.load_tasks(out)[0]
    assert loaded.blind["suite"] == "auth"
    assert loaded.blind["baseline"] == "red"
    assert loaded.public_api == ["login(name, password) -> token"]


def test_lint_rejects_blind_without_verify():
    issues = planner.lint_tasks(
        [
            Task(
                id="T1",
                desc="x",
                scope=["src/**"],
                blind={"suite": "auth"},
            )
        ]
    )
    assert planner.has_errors(issues)
    assert any("smoke" in issue.message for issue in issues)


def test_legacy_yaml_without_phases_defaults_to_p1(tmp_path: Path):
    path = tmp_path / "legacy.yaml"
    path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    desc: core\n"
        "    scope: [\"src/core/**\"]\n"
        "    verify: pytest tests/core -q\n",
        encoding="utf-8",
    )

    bundle = planner.load_contract(path)
    assert bundle.phases == []
    assert bundle.profile is None
    assert bundle.tasks[0].phase == "P1"

    out = tmp_path / "roundtrip.yaml"
    planner.write_tasks(out, bundle)
    loaded = planner.load_contract(out)
    assert loaded.tasks[0].phase == "P1"


def test_phases_yaml_roundtrip(tmp_path: Path):
    path = tmp_path / "phased.yaml"
    path.write_text(
        "profile: small\n"
        "phases:\n"
        "  - id: P1\n"
        "    name: Core\n"
        "    budget: 5m\n"
        "  - id: P2\n"
        "    name: Docs\n"
        "    budget: 10m\n"
        "tasks:\n"
        "  - id: T1\n"
        "    desc: core\n"
        "    phase: P1\n"
        "    scope: [\"src/core/**\"]\n"
        "    verify: pytest tests/core -q\n"
        "  - id: T2\n"
        "    desc: docs\n"
        "    phase: P2\n"
        "    scope: [\"docs/**\"]\n"
        "    verify: grep -q core docs/README.md\n",
        encoding="utf-8",
    )

    bundle = planner.load_contract(path)
    assert bundle.profile == "small"
    assert [phase.id for phase in bundle.phases] == ["P1", "P2"]
    assert bundle.phases[0].budget == "5m"
    assert [task.phase for task in bundle.tasks] == ["P1", "P2"]
    assert not planner.has_errors(planner.lint_contract(bundle))

    out = tmp_path / "roundtrip.yaml"
    planner.write_tasks(out, bundle)
    loaded = planner.load_contract(out)
    assert loaded.profile == "small"
    assert loaded.phases == bundle.phases
    assert [task.phase for task in loaded.tasks] == ["P1", "P2"]
    assert planner.render_yaml(loaded).startswith("profile: small\nphases:\n")


def test_phase_validation_rejects_unknown_empty_and_over_budget():
    tasks = [
        Task(id="T1", desc="core", phase="P1", scope=["src/**"], verify="pytest -q"),
        Task(id="T2", desc="other", phase="P2", scope=["docs/**"], verify="pytest -q"),
    ]
    phases = [
        PhaseSpec("P1", "Core", "10m"),
        PhaseSpec("P2", "Docs", "10m"),
    ]
    bundle = PlanBundle(tasks=tasks, phases=phases, profile="small")
    messages = " ".join(issue.message for issue in planner.lint_contract(bundle))
    assert "exceed max_wall_clock" in messages

    unknown = PhaseSpec("P1", "Core", "5m")
    unknown_task = Task(
        id="T3", desc="orphan", phase="P2", scope=["src/orphan/**"], verify="pytest -q"
    )
    unknown_bundle = PlanBundle(tasks=[unknown_task], phases=[unknown], profile="small")
    assert any("not declared" in issue.message for issue in planner.lint_contract(unknown_bundle))

    empty = PlanBundle(
        tasks=[tasks[0]],
        phases=[PhaseSpec("P1", "Core", "5m"), PhaseSpec("P2", "Docs", "5m")],
        profile="small",
    )
    assert any("is empty" in issue.message for issue in planner.lint_contract(empty))


def test_empty_phases_list_is_rejected(tmp_path: Path):
    path = tmp_path / "empty-phases.yaml"
    path.write_text("phases: []\ntasks: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at least one phase"):
        planner.load_contract(path)


def test_phase_validation_rejects_missing_fields_and_duplicates():
    bundle = PlanBundle(
        tasks=[Task(id="T1", desc="x", phase="P1", scope=["src/**"], verify="pytest -q")],
        phases=[
            PhaseSpec("P1", "", "5m"),
            PhaseSpec("P1", "Duplicate", None),
        ],
    )
    messages = " ".join(issue.message for issue in planner.lint_contract(bundle))
    assert "missing `name`" in messages
    assert "duplicate phase id" in messages
    assert "missing `budget`" in messages
