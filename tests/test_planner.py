from __future__ import annotations

from pathlib import Path

from waker import evidence, planner
from waker.models import Task


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
