"""End-to-end proof: plan -> lint -> blind vault -> kick -> DONE.

Prints every command and its output. Uses the fake lazy agent (0 tokens), so it
is deterministic and safe to run anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fake_agent.py"
WAKER = shutil.which("waker") or str(ROOT / ".venv" / "Scripts" / "waker.exe")
PY = sys.executable


def force_rmtree(path: Path) -> None:
    def on_exc(func, target, exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onexc=on_exc)


def banner(text: str) -> None:
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def py(code: str) -> str:
    return subprocess.list2cmdline([PY, "-c", code])


def exists(*paths: str) -> str:
    checks = " and ".join(f"os.path.exists({p!r})" for p in paths)
    return py(f"import os,sys; sys.exit(0 if {checks} else 1)")


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    print("\n$ " + subprocess.list2cmdline(argv))
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(output.rstrip())
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=None)
    args = parser.parse_args()

    demo = Path(args.dir or tempfile.mkdtemp(prefix="waker-proof-"))
    if demo.exists():
        force_rmtree(demo)
    (demo / "src").mkdir(parents=True)
    (demo / "tests").mkdir()
    (demo / ".gitignore").write_text(".waker/\n.fake_state.json\n", encoding="utf-8")
    (demo / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    for command in (
        ["git", "init", "-b", "main", str(demo)],
        ["git", "-C", str(demo), "config", "user.name", "proof"],
        ["git", "-C", str(demo), "config", "user.email", "proof@local"],
        ["git", "-C", str(demo), "add", "-A"],
        ["git", "-C", str(demo), "commit", "-q", "-m", "init"],
    ):
        subprocess.run(command, capture_output=True, check=False)

    banner("STEP 1 · create hidden vault outside the repo: suite a for T1, suite b for T2")
    vault_base = demo.parent / (demo.name + "-vaults")
    init = run(
        [WAKER, "vault", "init", "--repo", str(demo), "--vault-dir", str(vault_base), "--json"],
        demo,
    )
    vault_id = json.loads(init.stdout)["vault_id"]
    hidden_a = demo.parent / "test_hidden_a.py"
    hidden_a.write_text(
        "import os\n"
        "from pathlib import Path\n\n"
        "def test_a():\n"
        "    repo = Path(os.environ['WAKER_REPO'])\n"
        "    assert (repo / 'src' / 'a.txt').read_text(encoding='utf-8') == 'a'\n",
        encoding="utf-8",
    )
    hidden_b = demo.parent / "test_hidden_b.py"
    hidden_b.write_text(
        "import os\n"
        "from pathlib import Path\n\n"
        "def test_b():\n"
        "    repo = Path(os.environ['WAKER_REPO'])\n"
        "    assert (repo / 'src' / 'b.txt').read_text(encoding='utf-8') == 'b'\n",
        encoding="utf-8",
    )
    run(
        [WAKER, "vault", "add", "--vault", vault_id, "--suite", "a",
         "--task", "T1", str(hidden_a), "--vault-dir", str(vault_base), "--json"],
        demo,
    )
    run(
        [WAKER, "vault", "add", "--vault", vault_id, "--suite", "b",
         "--task", "T2", str(hidden_b), "--vault-dir", str(vault_base), "--json"],
        demo,
    )
    run(
        [WAKER, "vault", "validate", "--vault", vault_id, "--repo", str(demo),
         "--vault-dir", str(vault_base)],
        demo,
    )

    banner("STEP 2 · the contract: 2 tasks, each with public verify + blind suite")
    tasks = {
        "tasks": [
            {
                "id": "T1",
                "desc": "write src/a.txt",
                "scope": ["src/a.txt"],
                "verify": exists("src/a.txt"),
                "blind": {"suite": "a", "baseline": "red", "timeout": 30, "leak": "message"},
            },
            {
                "id": "T2",
                "desc": "write src/b.txt",
                "scope": ["src/b.txt"],
                "verify": exists("src/b.txt"),
                "blind": {"suite": "b", "baseline": "red", "timeout": 30, "leak": "message"},
            },
        ]
    }
    (demo / "tasks.yaml").write_text(
        yaml.safe_dump(tasks, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print((demo / "tasks.yaml").read_text(encoding="utf-8"))
    run([WAKER, "lint", "--tasks", "tasks.yaml", "--repo", "."], demo)

    banner("STEP 3 · run: lazy agent does T1, stops; waker catches it and wakes it")
    agent = subprocess.list2cmdline(
        [PY, str(FAKE), "--mode", "lazy", "--repo", "."]
    )
    result = run(
        [WAKER, "run", "--repo", ".", "--tasks", "tasks.yaml",
         "--agent", agent, "--vault", vault_id, "--vault-dir", str(vault_base),
         "--max-kicks", "3", "--turn-timeout", "30", "--no-freeze-probe"],
        demo,
    )
    print("\nrun exit code:", result.returncode)

    banner("STEP 4 · what was recorded (status + report)")
    run([WAKER, "status", "--repo", "."], demo)
    run([WAKER, "report", "--repo", "."], demo)

    banner("STEP 5 · audit trail + the wake prompt that named the missing task")
    runs_dir = demo / ".waker" / "runs"
    run_id = max(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime).name
    events = runs_dir / run_id / "events.jsonl"
    for line in events.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("t") in {"turn_start", "turn_end", "diagnose", "checkpoint"}:
            print(json.dumps(record, ensure_ascii=False))
    wake = runs_dir / run_id / "kick-1" / "prompt.txt"
    if wake.exists():
        print("\n--- kick-1/prompt.txt (the wake-up message) ---")
        print(wake.read_text(encoding="utf-8"))
    print("\n--- git checkpoints ---")
    log = subprocess.run(
        ["git", "-C", str(demo), "log", "--oneline", "-5"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(log.stdout.rstrip())

    banner("DONE")
    print("demo repo :", demo)
    print("vault base:", vault_base)
    print("run id    :", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
