"""Detect the test runner a repository already uses."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Detection:
    command: str
    runner: str
    source: str
    confidence: int

    def to_dict(self) -> dict:
        return asdict(self)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def detect_test_commands(repo: str | Path) -> list[Detection]:
    root = Path(repo)
    found: list[Detection] = []

    def add(command: str, runner: str, source: str, confidence: int) -> None:
        found.append(Detection(command, runner, source, confidence))

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = _read(pyproject)
        if "pytest" in text.lower():
            add("pytest -q", "pytest", "pyproject.toml", 95)

    for name in ("pytest.ini", "tox.ini", "setup.cfg", "conftest.py"):
        if (root / name).exists():
            add("pytest -q", "pytest", name, 90)
            break

    if (root / "tests").is_dir() or (root / "test").is_dir():
        add("pytest -q", "pytest", "tests/ directory", 75)

    package = root / "package.json"
    if package.exists():
        try:
            payload = json.loads(_read(package) or "{}")
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and "test" in (payload.get("scripts") or {}):
            add("npm test", "npm", "package.json scripts.test", 95)

    if (root / "Cargo.toml").exists():
        add("cargo test", "cargo", "Cargo.toml", 95)
    if (root / "go.mod").exists():
        add("go test ./...", "go", "go.mod", 95)

    makefile = root / "Makefile"
    if makefile.exists() and re.search(r"^test\s*:", _read(makefile), re.MULTILINE):
        add("make test", "make", "Makefile test target", 70)

    # Deduplicate by command, keep the highest confidence.
    best: dict[str, Detection] = {}
    for item in found:
        current = best.get(item.command)
        if current is None or item.confidence > current.confidence:
            best[item.command] = item
    return sorted(best.values(), key=lambda item: (-item.confidence, item.command))
