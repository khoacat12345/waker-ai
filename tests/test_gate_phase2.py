from __future__ import annotations

import json
from pathlib import Path

from waker.cli import main
from waker.gate import AntiSlopConfig, scan_paths


def write_file(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scan(root: Path, **overrides):
    config = AntiSlopConfig(
        enable_tests=True,
        enable_types=True,
        enable_comments=True,
        enable_core=False,
        **overrides,
    )
    return scan_paths(
        root,
        config=config,
        changed_only=False,
        baseline_ref="",
        use_baseline=False,
    )


def rules(result) -> set[str]:
    return {finding.rule for finding in result.findings}


def test_test_integrity_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "tests/test_fake.py",
        "import pytest\n\n"
        "def test_empty():\n"
        "    pass\n\n"
        "def test_true():\n"
        "    assert True\n\n"
        "@pytest.mark.skip(reason='later')\n"
        "def test_skipped():\n"
        "    assert 1 == 1\n\n"
        "def test_swallowed():\n"
        "    try:\n"
        "        assert 1 == 2\n"
        "    except AssertionError:\n"
        "        pass\n",
    )
    result = scan(tmp_path)
    found = rules(result)
    assert {"TEST001", "TEST002", "TEST004", "TEST005"}.issubset(found)


def test_test_integrity_clean(tmp_path: Path) -> None:
    write_file(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
    write_file(
        tmp_path,
        "tests/test_clean.py",
        "from clean import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
    )
    result = scan(tmp_path)
    assert not (rules(result) & {"TEST001", "TEST002", "TEST004", "TEST005"})


def test_mock_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "tests/test_charge.py",
        "from unittest.mock import patch\n\n"
        "@patch('app.charge.charge_card')\n"
        "def test_charge_card(mock_charge):\n"
        "    mock_charge.return_value = 5\n"
        "    assert mock_charge() == 5\n\n"
        "def test_mock_assertion():\n"
        "    m = object()\n"
        "    assert m.assert_called_once\n",
    )
    result = scan(tmp_path)
    assert "TEST003" in rules(result)


def test_type_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "types_bad.py",
        "from typing import Any, cast\n\n"
        "def bad(x: Any) -> Any:\n"
        "    raw: Any = x\n"
        "    return cast(str, raw)\n\n"
        "def ignored():\n"
        "    value = 1  # type: ignore\n"
        "    return value\n",
    )
    result = scan(tmp_path)
    assert {"TYPE001", "TYPE002", "TYPE005", "TYPE007", "TYPE008"}.issubset(rules(result))


def test_type_safe_patterns(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "types_safe.py",
        "from typing import TypeGuard, cast\n\n"
        "def is_int(x: object) -> TypeGuard[int]:\n"
        "    return isinstance(x, int)\n\n"
        "def value(x: int) -> int:\n"
        "    return cast(int, x)  # SAFETY: caller guarantees int\n\n"
        "def ignored() -> int:\n"
        "    value = 1  # type: ignore[attr-defined]\n"
        "    return value\n",
    )
    result = scan(tmp_path)
    assert not (rules(result) & {"TYPE001", "TYPE006", "TYPE007", "TYPE008"})


def test_extra_type_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "types_extra.py",
        "from typing import Any, TypeAlias, cast\n\n"
        "Alias: TypeAlias = Any\n\n"
        "def extra(x):\n"
        "    chained = cast(str, cast(Any, x))\n"
        "    getattr(x, 'name')\n"
        "    known: Any = 1\n"
        "    payload: dict[str, Any] = {}\n"
        "    if isinstance(x, int) or isinstance(x, str) or isinstance(x, float):\n"
        "        return 1\n"
        "    return chained\n",
    )
    result = scan(tmp_path)
    found = rules(result)
    assert {"TYPE003", "TYPE004", "TYPE009", "TYPE010", "TYPE011", "TYPE012"}.issubset(found)


def test_test_warning_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "tests/test_mocks.py",
        "from unittest.mock import Mock, patch\n\n"
        "@patch('app.one')\n"
        "@patch('app.two')\n"
        "def test_many_mocks(m1, m2):\n"
        "    m1.return_value = Mock()\n"
        "    m2.return_value = Mock()\n"
        "    assert m1() is not None\n\n"
        "import pytest\n\n"
        "def test_broad():\n"
        "    with pytest.raises(Exception):\n"
        "        int('x')\n",
    )
    write_file(tmp_path, "tests/test_orphan.py", "def test_orphan():\n    assert 1 == 2\n")
    result = scan(tmp_path)
    found = rules(result)
    assert {"TEST006", "TEST007", "TEST008"}.issubset(found)


def test_comment_and_stub_rules(tmp_path: Path) -> None:
    write_file(
        tmp_path,
        "comments.py",
        "def stub():\n"
        "    ...\n\n"
        "def placeholder():\n"
        "    # TODO: implement later\n"
        "    pass\n\n"
        "# This function handles the request\n"
        "def obvious():\n"
        "    return 1\n\n"
        "# Step 1: validate\n"
        "def step():\n"
        "    return 2\n\n"
        "# noqa\n"
        "def suppressed():\n"
        "    return 3\n",
    )
    result = scan(tmp_path)
    found = rules(result)
    assert {"STUB001", "COMMENT001", "COMMENT002", "COMMENT003", "SUPPRESS001"}.issubset(found)


def test_phase2_cli_all_gates(tmp_path: Path, capsys) -> None:
    write_file(
        tmp_path,
        "tests/test_fake.py",
        "def test_empty():\n    pass\n",
    )
    write_file(
        tmp_path,
        "types_bad.py",
        "from typing import Any\n\ndef bad(x: Any) -> Any:\n    return x\n",
    )
    code = main(
        [
            "audit",
            "--all",
            "--repo",
            str(tmp_path),
            "--tests",
            "--types",
            "--comments",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert {"TEST001", "TYPE001", "TYPE002"}.issubset(
        {finding["rule"] for finding in payload["findings"]}
    )
    assert payload["score"] < 100


def test_phase2_clean_all_gates(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
    write_file(
        tmp_path,
        "tests/test_clean.py",
        "from clean import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
    )
    code = main(
        [
            "audit",
            "--all",
            "--repo",
            str(tmp_path),
            "--tests",
            "--types",
            "--comments",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "0 finding(s)" in out
    assert "Cleanliness: 100/100 (A)" in out


def test_cli_all_gates_flag(tmp_path: Path, capsys) -> None:
    write_file(tmp_path, "tests/test_fake.py", "def test_empty():\n    pass\n")
    code = main(
        [
            "audit",
            "--all",
            "--repo",
            str(tmp_path),
            "--all-gates",
            "--format",
            "badge",
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "img.shields.io" in out
