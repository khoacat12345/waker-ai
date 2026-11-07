from __future__ import annotations

import json
from pathlib import Path

from waker import detect


def test_detect_pytest_from_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
    )
    results = detect.detect_test_commands(tmp_path)
    assert results
    assert results[0].command == "pytest -q"
    assert results[0].confidence >= 90


def test_detect_pytest_from_tests_dir(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    results = detect.detect_test_commands(tmp_path)
    assert results[0].command == "pytest -q"
    assert results[0].confidence == 75


def test_detect_npm(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8"
    )
    results = detect.detect_test_commands(tmp_path)
    assert results[0].command == "npm test"


def test_detect_cargo_and_go(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    commands = {item.command for item in detect.detect_test_commands(tmp_path)}
    assert {"cargo test", "go test ./..."} <= commands


def test_detect_makefile(tmp_path: Path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    results = detect.detect_test_commands(tmp_path)
    assert results[0].command == "make test"


def test_detect_empty_repo(tmp_path: Path):
    assert detect.detect_test_commands(tmp_path) == []
