from __future__ import annotations

from pathlib import Path

import pytest

from waker import llm_plan, planner

YAML = """tasks:
  - id: T1
    desc: auth
    scope: ["src/auth/**"]
    verify: "pytest tests/auth -q"
  - id: C1
    desc: no tailwind
    kind: constraint
    check: "python -c \\"import sys;sys.exit(0)\\""
"""


def test_extract_yaml_from_fence():
    text = "Sure, here is the plan:\n```yaml\n" + YAML + "```\nDone."
    extracted = llm_plan.extract_yaml(text)
    assert extracted.startswith("tasks:")
    assert "T1" in extracted


def test_extract_yaml_plain_text():
    extracted = llm_plan.extract_yaml("Here you go:\n" + YAML)
    assert extracted.startswith("tasks:")


def test_extract_yaml_missing_raises():
    with pytest.raises(ValueError):
        llm_plan.extract_yaml("I cannot help with that")


def test_generate_contract_with_fake_runner(repo: Path):
    bundle = llm_plan.generate_contract(
        "làm module auth",
        repo,
        runner=lambda meta: "```yaml\n" + YAML + "```",
    )
    assert [task.id for task in bundle.tasks] == ["T1"]
    assert bundle.tasks[0].scope == ["src/auth/**"]
    assert bundle.constraints[0].kind == "constraint"
    issues = planner.lint_tasks(bundle.all_tasks(), repo=repo)
    assert not planner.has_errors(issues)


def test_generate_contract_rejects_empty(repo: Path):
    with pytest.raises(ValueError):
        llm_plan.generate_contract("x", repo, runner=lambda meta: "no plan here")


def test_meta_prompt_contains_prompt_and_repo(repo: Path):
    meta = llm_plan.build_meta_prompt("làm điều gì đó", repo)
    assert "làm điều gì đó" in meta
    assert str(repo.resolve()) in meta
    assert "scope" in meta.lower()
