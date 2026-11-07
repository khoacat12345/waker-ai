"""Fake AI agents used by the test-suite.

Each mode reproduces one of the four classic failures:

* ``lazy``    - does task 1, stops, honestly reports partial work
* ``liar``    - does nothing, claims everything is done
* ``tamper``  - does the work but edits the exam
* ``freeze``  - hangs forever
* ``blocked`` - declares a legitimate blocker
* ``good``    - does the work in one turn
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="lazy")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    mode = args.mode

    state_file = repo / ".fake_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {"turns": 0}
    state["turns"] += 1
    if mode != "freeze":
        state_file.write_text(json.dumps(state), encoding="utf-8")
    turn = state["turns"]

    src = repo / "src"
    src.mkdir(parents=True, exist_ok=True)

    if mode == "lazy":
        if turn == 1:
            (src / "a.txt").write_text("a", encoding="utf-8")
            print("Em mới làm xong Task 1 thôi nhé!")
        else:
            (src / "b.txt").write_text("b", encoding="utf-8")
            print("Đã xong Task 2.")
    elif mode == "liar":
        print("All tasks completed! Everything is done.")
    elif mode == "tamper":
        (src / "a.txt").write_text("a", encoding="utf-8")
        (src / "b.txt").write_text("b", encoding="utf-8")
        tests = repo / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_all.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        print("All tasks completed.")
    elif mode == "freeze":
        print("working...", flush=True)
        time.sleep(30)
    elif mode == "blocked":
        print("BLOCKED: cần credential Vercel")
    elif mode == "good":
        (src / "a.txt").write_text("a", encoding="utf-8")
        (src / "b.txt").write_text("b", encoding="utf-8")
        print("All tasks completed.")
    else:  # pragma: no cover - defensive
        raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main()
