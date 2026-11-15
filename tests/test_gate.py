from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from waker.cli import main
from waker.gate import (
    AntiSlopConfig,
    badge_markdown,
    baseline_path,
    scan_paths,
    score_findings,
    write_baseline,
)
from waker.gate.model import Finding, grade_for

FIXTURES = Path(__file__).parent / "fixtures" / "anti_slop"


def test_static_clean_fixture(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "clean", tmp_path / "repo")
    result = scan(tmp_path / "repo")
    assert result.findings == []
    assert result.score == 100


def test_static_bad_fixture(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "bad", tmp_path / "repo")
    result = scan(tmp_path / "repo", max_function_lines=3)
    rules = {finding.rule for finding in result.findings}
    assert {"SLOP001", "SLOP002", "SLOP004", "SLOP006"}.issubset(rules)
    assert result.errors_count >= 4


def write_file(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scan(root: Path, **overrides):
    config = AntiSlopConfig(**overrides)
    return scan_paths(
        root,
        config=config,
        changed_only=False,
        baseline_ref="",
        use_baseline=False,
    )


def test_clean_file_scores_100(tmp_path: Path) -> None:
    write_file(tmp_path, "clean.py", "def add(x: int) -> int:\n    return x + 1\n")
    result = scan(tmp_path)
    assert result.findings == []
    assert result.score == 100
    assert result.grade == "A"
    assert result.badge.startswith("![waker anti-slop]")


def test_duplicate_symbols(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "dupe.py",
        "def parse(x):\n    return x\n\n\ndef parse(y):\n    return y\n",
    )
    result = scan(tmp_path)
    assert any(f.rule == "SLOP001" for f in result.findings)
    assert result.errors_count == 1


def test_property_setter_is_not_a_duplicate(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "prop.py",
        "class A:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return self._value\n"
        "\n"
        "    @value.setter\n"
        "    def value(self, value):\n"
        "        self._value = value\n",
    )
    result = scan(tmp_path)
    assert not any(f.rule == "SLOP001" for f in result.findings)


def test_overloads_are_not_duplicates(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "overloads.py",
        "from typing import overload\n\n"
        "@overload\n"
        "def parse(x: int) -> int: ...\n\n"
        "@overload\n"
        "def parse(x: str) -> str: ...\n\n"
        "def parse(x):\n"
        "    return x\n",
    )
    result = scan(tmp_path)
    assert not any(f.rule == "SLOP001" for f in result.findings)


def test_silent_broad_exception(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "excepts.py",
        "def bad():\n"
        "    try:\n"
        "        return 1 / 0\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "def ok():\n"
        "    try:\n"
        "        return 1 / 0\n"
        "    except ZeroDivisionError:\n"
        "        return 0\n",
    )
    result = scan(tmp_path)
    findings = [f for f in result.findings if f.rule == "SLOP002"]
    assert len(findings) == 1
    assert findings[0].line == 4


def test_function_and_module_limits(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "long_func.py",
        "def long():\n"
        "    a = 1\n"
        "    b = 2\n"
        "    c = 3\n"
        "    d = 4\n"
        "    return a + b + c + d\n",
    )
    result = scan(tmp_path, max_function_lines=3, max_module_lines=100)
    assert any(f.rule == "SLOP004" for f in result.findings)


def test_module_limit(tmp_path: Path) -> None:
    write_file(tmp_path, "long_module.py", "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n")
    result = scan(tmp_path, max_module_lines=3, max_function_lines=100)
    assert any(f.rule == "SLOP005" for f in result.findings)


def test_complexity_limit(tmp_path: Path) -> None:
    body = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(20))
    write_file(tmp_path, "complex.py", f"def choose(x):\n{body}    return -1\n")
    result = scan(tmp_path, max_cyclomatic_complexity=10, max_function_lines=100)
    assert any(f.rule == "SLOP003" for f in result.findings)


def test_copy_paste_across_files(tmp_path: Path) -> None:
    body = "".join(f"    value += {i}\n" for i in range(20))
    source = f"def process():\n    value = 0\n{body}    return value\n"
    write_file(tmp_path, "a.py", source)
    write_file(tmp_path, "b.py", source)
    result = scan(
        tmp_path,
        duplicate_block_min_statements=5,
        duplicate_block_min_lines=10,
    )
    assert any(f.rule == "SLOP006" for f in result.findings)


def test_growth_against_git_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=False)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@local"], check=False)
    source = "".join(f"value_{i} = {i}\n" for i in range(100))
    write_file(repo, "grow.py", source)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=False)
    write_file(repo, "grow.py", source + "".join(f"extra_{i} = {i}\n" for i in range(40)))
    config = AntiSlopConfig(track_file_growth=0.15, growth_min_lines=30)
    result = scan_paths(
        repo,
        config=config,
        changed_only=False,
        baseline_ref="HEAD",
        use_baseline=False,
    )
    assert any(f.rule == "SLOP007" for f in result.findings)


def test_suppression_comment(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "suppressed.py",
        "def optional():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:  # waker: ignore[SLOP002] reason=\"optional import\"\n"
        "        pass\n",
    )
    result = scan(tmp_path)
    assert not any(f.rule == "SLOP002" for f in result.findings)


def test_baseline_suppresses_legacy_findings(tmp_path: Path) -> None:
    write_file(tmp_path, "bad.py", "def parse(x):\n    return x\n\ndef parse(y):\n    return y\n")
    config = AntiSlopConfig()
    first = scan_paths(tmp_path, config=config, changed_only=False, baseline_ref="", use_baseline=False)
    target = baseline_path(tmp_path, config)
    assert target is not None
    write_baseline(target, first.findings)
    second = scan_paths(tmp_path, config=config, changed_only=False, baseline_ref="", use_baseline=True)
    assert second.baseline_suppressed >= 1
    assert second.score == 100
    assert second.errors_count == 0


def test_score_and_badge() -> None:
    assert score_findings([]) == 100
    assert score_findings([Finding("X", "error", "a.py", 1, 1, "x")]) == 90
    assert score_findings([Finding("X", "warning", "a.py", 1, 1, "x")]) == 97
    assert grade_for(90) == "A"
    assert grade_for(80) == "B"
    assert "brightgreen" in badge_markdown(95)
    assert "red" in badge_markdown(10)


def test_cli_audit_clean(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "clean.py", "def add(x: int) -> int:\n    return x + 1\n")
    code = main(["audit", "--all", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Cleanliness: 100/100 (A)" in out
    assert "img.shields.io" in out


def test_cli_audit_findings_and_json(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "bad.py", "def parse(x):\n    return x\n\ndef parse(y):\n    return y\n")
    code = main(["audit", "--all", "--repo", str(tmp_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["score"] == 90
    assert payload["errors"] == 1
    assert payload["findings"][0]["rule"] == "SLOP001"


def test_cli_audit_badge(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "clean.py", "def add(x: int) -> int:\n    return x + 1\n")
    code = main(["audit", "--all", "--repo", str(tmp_path), "--format", "badge"])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out.startswith("![waker anti-slop]")


def test_cli_audit_badge_fails_on_findings(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "bad.py", "def parse(x):\n    return x\n\ndef parse(y):\n    return y\n")
    code = main(["audit", "--all", "--repo", str(tmp_path), "--format", "badge"])
    out = capsys.readouterr().out.strip()
    assert code == 2
    assert "anti--slop-90%2F100-" in out


def test_cli_audit_anti_slop_flag_and_badge(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "clean.py", "def add(x: int) -> int:\n    return x + 1\n")
    code = main(
        ["audit", "--anti-slop", "--all", "--repo", str(tmp_path), "--badge"]
    )
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out.startswith("![waker anti-slop]")


def test_cli_write_baseline_then_clean(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "bad.py", "def parse(x):\n    return x\n\ndef parse(y):\n    return y\n")
    code = main(["audit", "--all", "--repo", str(tmp_path), "--write-baseline"])
    capsys.readouterr()
    assert code == 0
    assert (tmp_path / ".waker" / "anti-slop-baseline.json").exists()
    code = main(["audit", "--all", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Baseline:" in out
    assert "Cleanliness: 100/100 (A)" in out


def test_cli_strict_turns_warning_into_failure(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "many_params.py", "def add(a, b):\n    return a + b\n")
    code = main(
        ["audit", "--all", "--repo", str(tmp_path), "--max-parameters", "1"]
    )
    capsys.readouterr()
    assert code == 0
    code = main(
        [
            "audit",
            "--all",
            "--repo",
            str(tmp_path),
            "--max-parameters",
            "1",
            "--strict",
        ]
    )
    capsys.readouterr()
    assert code == 2
