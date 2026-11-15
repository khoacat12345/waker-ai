from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from waker.gate.autofix import fix_file, fix_paths, fix_source
from waker.gate.external import (
    EslintAdapter,
    OxlintAdapter,
    run_external_linters,
)
from waker.gate.model import Finding


@dataclass
class Proc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def write_file(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def finding(rule: str, path: str, line: int, col: int = 1) -> Finding:
    return Finding(rule, "error", path, line, col, f"{rule} problem")


def test_eslint_adapter_normalizes_findings_and_filters_python(tmp_path: Path) -> None:
    write_file(tmp_path, "src/app.ts", "const value = 1;\n")
    write_file(tmp_path, "src/old.py", "x = 1\n")
    calls: list[tuple[list[str], Path, float]] = []

    def runner(command, cwd, timeout):
        calls.append((command, cwd, timeout))
        return Proc(
            returncode=1,
            stdout=(
                '[{"filePath":"'
                + str(tmp_path / "src" / "app.ts").replace("\\", "\\\\")
                + '","messages":[{"ruleId":"no-eval","severity":2,'
                '"message":"eval is forbidden","line":4,"column":2}]}]'
            ),
        )

    adapter = EslintAdapter(available_override=True)
    result = run_external_linters(
        tmp_path,
        ["src/app.ts", "src/old.py"],
        adapters=[adapter],
        runner=runner,
    )

    assert len(calls) == 1
    assert calls[0][0] == ["eslint", "--format", "json", "src/app.ts"]
    assert calls[0][1] == tmp_path.resolve()
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.rule == "eslint:no-eval"
    assert finding.path == "src/app.ts"
    assert (finding.line, finding.col) == (4, 2)
    assert finding.severity == "warning"
    assert finding.family == "external"
    assert result.adapters_run == ["eslint"]


def test_oxlint_adapter_understands_diagnostics_shape(tmp_path: Path) -> None:
    write_file(tmp_path, "src/app.js", "debugger;\n")
    payload = (
        '{"diagnostics":[{"filename":"src/app.js",'
        '"code":"no-debugger","message":"Unexpected debugger",'
        '"labels":[{"span":{"line":7,"column":3}}]}]}'
    )
    adapter = OxlintAdapter(available_override=True)
    result = run_external_linters(
        tmp_path,
        ["src/app.js"],
        adapters=[adapter],
        runner=lambda command, cwd, timeout: Proc(returncode=1, stdout=payload),
    )

    assert len(result.findings) == 1
    item = result.findings[0]
    assert item.rule == "oxlint:no-debugger"
    assert (item.line, item.col) == (7, 3)
    assert item.path == "src/app.js"


def test_external_adapter_missing_binary_is_non_fatal(tmp_path: Path) -> None:
    write_file(tmp_path, "src/app.ts", "const x = 1;\n")
    called = False

    def runner(command, cwd, timeout):
        nonlocal called
        called = True
        return Proc()

    result = run_external_linters(
        tmp_path,
        ["src/app.ts"],
        adapters=[EslintAdapter(available_override=False)],
        runner=runner,
    )

    assert called is False
    assert result.findings == []
    assert result.errors
    assert "not installed" in result.errors[0]


def test_external_adapter_bad_json_is_reported(tmp_path: Path) -> None:
    write_file(tmp_path, "src/app.ts", "const x = 1;\n")
    result = run_external_linters(
        tmp_path,
        ["src/app.ts"],
        adapters=[EslintAdapter(available_override=True)],
        runner=lambda command, cwd, timeout: Proc(returncode=1, stdout="not json"),
    )

    assert result.findings == []
    assert result.errors
    assert "invalid JSON" in result.errors[0]


def test_external_adapter_skips_when_no_js_files(tmp_path: Path) -> None:
    result = run_external_linters(
        tmp_path,
        ["src/only.py"],
        adapters=[EslintAdapter(available_override=True)],
    )
    assert result.findings == []
    assert result.errors == []
    assert result.adapters_run == []


def test_autofix_adds_safety_comment_to_cast() -> None:
    source = (
        "from typing import cast\n"
        "def read(value):\n"
        "    return cast(int, value)\n"
    )
    result = fix_source(
        source,
        "src/app.py",
        [finding("TYPE007", "src/app.py", 3)],
    )

    assert result.changed is True
    assert result.applied == ["TYPE007"]
    assert "cast(int, value)  # SAFETY: review this cast" in result.source
    ast.parse(result.source)


def test_autofix_removes_only_a_safe_single_import() -> None:
    source = "import os\n\nVALUE = 1\n"
    result = fix_source(
        source,
        "src/app.py",
        [finding("DEAD002", "src/app.py", 1)],
    )

    assert result.changed is True
    assert result.applied == ["DEAD002"]
    assert "import os" not in result.source
    assert "VALUE = 1" in result.source
    ast.parse(result.source)


def test_autofix_skips_ambiguous_import_and_existing_safety() -> None:
    source = (
        "import os, sys\n"
        "from typing import cast\n"
        "def f(x):\n"
        "    return cast(int, x)  # SAFETY: already reviewed\n"
    )
    result = fix_source(
        source,
        "src/app.py",
        [
            finding("DEAD002", "src/app.py", 1),
            finding("TYPE007", "src/app.py", 4),
        ],
    )

    assert result.changed is False
    assert result.applied == []
    assert result.skipped


def test_autofix_rejects_unparseable_source() -> None:
    result = fix_source(
        "def broken(:\n",
        "src/app.py",
        [finding("TYPE007", "src/app.py", 1)],
    )
    assert result.changed is False
    assert result.skipped


def test_autofix_file_dry_run_and_write(tmp_path: Path) -> None:
    path = write_file(
        tmp_path,
        "src/app.py",
        "import os\nVALUE = 1\n",
    )
    findings = [finding("DEAD002", "src/app.py", 1)]

    dry = fix_file(path, findings, dry_run=True, display_path="src/app.py")
    assert dry.changed is True
    assert "import os" in path.read_text(encoding="utf-8")

    written = fix_file(path, findings, display_path="src/app.py")
    assert written.changed is True
    assert "import os" not in path.read_text(encoding="utf-8")


def test_autofix_paths_preserves_unrelated_files(tmp_path: Path) -> None:
    write_file(tmp_path, "src/app.py", "import os\nVALUE = 1\n")
    write_file(tmp_path, "src/keep.py", "KEEP = 1\n")
    results = fix_paths(
        tmp_path,
        [finding("DEAD002", "src/app.py", 1)],
    )

    assert len(results) == 1
    assert results[0].path == "src/app.py"
    assert "import os" not in (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    assert (tmp_path / "src" / "keep.py").read_text(encoding="utf-8") == "KEEP = 1\n"


def test_cli_audit_fix_and_dry_run(tmp_path: Path, capsys) -> None:
    from waker.cli import main

    path = write_file(tmp_path, "app.py", "import os\nVALUE = 1\n")

    dry_code = main(
        ["audit", "--all", "--all-gates", "--fix", "--dry-run", "--repo", str(tmp_path)]
    )
    assert dry_code == 2
    assert "import os" in path.read_text(encoding="utf-8")

    code = main(
        ["audit", "--all", "--all-gates", "--fix", "--repo", str(tmp_path)]
    )
    assert code == 0
    assert "import os" not in path.read_text(encoding="utf-8")

