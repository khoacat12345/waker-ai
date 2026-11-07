from __future__ import annotations

from pathlib import Path

from waker import evidence
from waker.models import Failure, Task
from waker.state import git_head


def test_changed_files_sees_untracked(repo: Path):
    (repo / "src" / "a.txt").write_text("a", encoding="utf-8")
    files = evidence.changed_files(repo, git_head(repo))
    assert "src/a.txt" in files


def test_changed_files_sees_tracked_edit(repo: Path):
    (repo / "tests" / "test_all.py").write_text(
        "def test_real():\n    assert False\n# edited\n", encoding="utf-8"
    )
    files = evidence.changed_files(repo, git_head(repo))
    assert "tests/test_all.py" in files


def test_lines_changed_counts(repo: Path):
    (repo / "src" / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    assert evidence.lines_changed(repo, git_head(repo)) >= 2


def test_hash_globs_detects_tamper_and_restore(repo: Path):
    baseline = git_head(repo)
    before = evidence.hash_globs(repo, ["tests/**"])
    (repo / "tests" / "test_all.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    assert evidence.hash_globs(repo, ["tests/**"]) != before

    restored = evidence.restore_globs(repo, ["tests/**"], baseline)
    assert "tests/test_all.py" in restored
    assert evidence.hash_globs(repo, ["tests/**"]) == before


def test_parse_failures_from_pytest_output():
    output = (
        "FAILED tests/test_x.py::test_a - AssertionError: nope\n"
        "FAILED tests/test_y.py::test_b - KeyError: 'e4'\n"
    )
    failures = evidence.parse_failures(output)
    assert len(failures) == 2
    assert failures[0].label() == "tests/test_x.py::test_a"
    assert "nope" in failures[0].message


def test_suspect_test_detects_broken_test():
    broken = [Failure(file="tests/t.py", name="test_a", message="ModuleNotFoundError: No module named 'x'")]
    assert evidence.suspect_test(broken, "E   ModuleNotFoundError")
    real = [Failure(file="tests/t.py", name="test_a", message="AssertionError: 1 != 2")]
    assert not evidence.suspect_test(real, "AssertionError: 1 != 2")


def test_claimed_done_and_blocked():
    assert evidence.claimed_done("All tasks completed!")
    assert evidence.claimed_done("Đã xong hết rồi")
    assert not evidence.claimed_done("Em mới làm xong Task 1 thôi")
    assert evidence.parse_blocked("BLOCKED: cần token") == "cần token"
    assert evidence.parse_blocked("nothing") is None


def test_scope_hits_and_unscoped(repo: Path):
    tasks = [
        Task(id="T1", desc="a", scope=["src/a/**"]),
        Task(id="T2", desc="b", scope=["src/b/**"]),
    ]
    files = ["src/a/x.py", "docs/readme.md"]
    hits = evidence.scope_hits(tasks, files)
    assert hits == {"T1": ["src/a/x.py"]}
    assert evidence.unscoped_files(tasks, files) == ["docs/readme.md"]


def test_all_tasks_done_requires_hit_and_green():
    tasks = [Task(id="T1", desc="a", scope=["src/**"])]
    hit = {"T1": ["src/a.py"]}
    green = {"T1": evidence.RequirementResult("T1", 0)}
    red = {"T1": evidence.RequirementResult("T1", 1)}
    assert evidence.all_tasks_done(tasks, hit, green)
    assert not evidence.all_tasks_done(tasks, {}, green)
    assert not evidence.all_tasks_done(tasks, hit, red)


def test_blocking_constraint_can_fail_the_gate():
    work = [Task(id="T1", desc="a", scope=["src/**"], verify="true")]
    constraint = Task(id="C1", desc="no tailwind", kind="constraint", check="true")
    hits = {"T1": ["src/a.py"]}
    green = {"T1": evidence.RequirementResult("T1", 0)}
    assert evidence.all_tasks_done(work, hits, green, [constraint], {"C1": evidence.RequirementResult("C1", 0)})
    assert not evidence.all_tasks_done(work, hits, green, [constraint], {"C1": evidence.RequirementResult("C1", 1)})
