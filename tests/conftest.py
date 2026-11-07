from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from waker.models import Task

FAKE_AGENT = Path(__file__).parent / "fake_agent.py"


def py(code: str) -> str:
    """Build a shell-safe `python -c "<code>"` command."""
    return subprocess.list2cmdline([sys.executable, "-c", code])


def py_script(script: Path, *args: str) -> str:
    return subprocess.list2cmdline([sys.executable, str(script), *args])


def fake_agent(mode: str) -> str:
    return py_script(FAKE_AGENT, "--mode", mode, "--repo", ".")


def exists_cmd(*paths: str) -> str:
    checks = " and ".join(f"os.path.exists({p!r})" for p in paths)
    return py(f"import os,sys; sys.exit(0 if {checks} else 1)")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=False)
    git(path, "config", "user.name", "test")
    git(path, "config", "user.email", "test@local")
    (path / ".gitignore").write_text(".waker/\n.fake_state.json\n", encoding="utf-8")
    (path / "src").mkdir(exist_ok=True)
    (path / "tests").mkdir(exist_ok=True)
    (path / "tests" / "test_all.py").write_text(
        "def test_real():\n    assert False\n", encoding="utf-8"
    )
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path / "repo")


@pytest.fixture()
def tasks() -> list[Task]:
    return [
        Task(id="T1", desc="write a", scope=["src/a.txt"], verify=exists_cmd("src/a.txt")),
        Task(id="T2", desc="write b", scope=["src/b.txt"], verify=exists_cmd("src/b.txt")),
    ]
