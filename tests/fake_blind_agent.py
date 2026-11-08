"""Fake worker for blind-evaluation CLI tests. Writes src/a.py with VALUE."""

from __future__ import annotations

import argparse
import pathlib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="good")
    args = parser.parse_args()
    repo = pathlib.Path.cwd()
    (repo / "src").mkdir(exist_ok=True)
    value = 42 if args.mode == "good" else 0
    (repo / "src" / "a.py").write_text(f"VALUE = {value}\n", encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
