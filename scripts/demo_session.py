"""Deterministic 60-second demo for screen recording.

Uses the fake lazy agent (no model, 0 tokens): it does task 1, stops, gets
kicked, then finishes task 2. The supervisor output is the product.

Record with Xbox Game Bar (Win+G) or OBS/ShareX, then upload to YouTube/Loom.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fake_agent.py"
WAKER = shutil.which("waker") or str(ROOT / ".venv" / "Scripts" / "waker.exe")


def py(code: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-c", code])


def banner(text: str) -> None:
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def step(args, message: str = "Press Enter for the next step") -> None:
    if args.pause:
        input(f"\n>>> {message} ...")
    else:
        time.sleep(args.sleep)


def run(argv: list[str], cwd: Path) -> int:
    print("\n$ " + subprocess.list2cmdline(argv))
    sys.stdout.flush()
    result = subprocess.run(argv, cwd=str(cwd))
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pause", action="store_true", help="wait for Enter between steps")
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--dir", default=None)
    args = parser.parse_args()

    if args.dir:
        demo = Path(args.dir)
        if demo.exists():
            shutil.rmtree(demo)
    else:
        demo = Path(tempfile.mkdtemp(prefix="waker-demo-video-"))
    (demo / "src").mkdir(parents=True)
    (demo / "tests").mkdir()
    (demo / ".gitignore").write_text(".waker/\n.fake_state.json\n", encoding="utf-8")
    (demo / "tests" / "test_placeholder.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    for command in (
        ["git", "init", "-b", "main", str(demo)],
        ["git", "-C", str(demo), "config", "user.name", "demo"],
        ["git", "-C", str(demo), "config", "user.email", "demo@local"],
        ["git", "-C", str(demo), "add", "-A"],
        ["git", "-C", str(demo), "commit", "-q", "-m", "init"],
    ):
        subprocess.run(command, capture_output=True, check=False)

    exists_a = py("import os,sys; sys.exit(0 if os.path.exists('src/a.txt') else 1)")
    exists_b = py("import os,sys; sys.exit(0 if os.path.exists('src/b.txt') else 1)")
    prompt = "\n".join(
        [
            f"Phase 1: write src/a.txt, scope: src/a.txt, verify: {exists_a}",
            f"Phase 2: write src/b.txt, scope: src/b.txt, verify: {exists_b}",
        ]
    )

    banner("waker-ai · never let an AI coding agent sleep on the job")
    print("Demo: 2 tasks, a lazy fake agent (0 tokens).")
    step(args, "Start recording now, then press Enter")

    banner("1/5 · Plan: prompt -> mechanical contract")
    code = run(
        [WAKER, "plan", "--prompt", prompt, "--out", ".waker/tasks.yaml", "--repo", "."],
        demo,
    )
    if code != 0:
        print("plan failed")
        return code
    step(args)

    banner("2/5 · Lint: fail closed on missing scope/verify")
    run([WAKER, "lint", "--tasks", ".waker/tasks.yaml", "--repo", "."], demo)
    step(args)

    banner("3/5 · Supervise: the agent stops at Task 1, waker kicks it")
    agent = subprocess.list2cmdline(
        [sys.executable, str(FAKE), "--mode", "lazy", "--repo", "."]
    )
    run(
        [
            WAKER,
            "run",
            "--repo",
            ".",
            "--tasks",
            ".waker/tasks.yaml",
            "--agent",
            agent,
            "--max-kicks",
            "3",
            "--turn-timeout",
            "30",
            "--no-freeze-probe",
        ],
        demo,
    )
    step(args)

    banner("4/5 · Report: evidence on disk, not the agent's words")
    run([WAKER, "report", "--repo", "."], demo)
    step(args)

    banner("5/5 · Status: every task needs a diff in scope + verify exit 0")
    run([WAKER, "status", "--repo", "."], demo)

    print("\nDemo repository:", demo)
    print("GitHub: https://github.com/khoacat12345/waker-ai")
    print("PyPI  : https://pypi.org/project/waker-ai/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
