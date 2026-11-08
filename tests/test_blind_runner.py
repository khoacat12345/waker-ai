from __future__ import annotations

from pathlib import Path

import pytest

from waker import vault_runner
from waker.blind_runner import GradeResult, grade_suite, grade_vault, summarize
from waker.vault import Vault


def make_vault(tmp_path: Path) -> tuple[Path, Vault]:
    repo = tmp_path / "repo"
    repo.mkdir()
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    return repo, vault


def add_code(
    tmp_path: Path,
    vault: Vault,
    code: str,
    leak: str = "message",
    name: str = "test_hidden.py",
) -> None:
    source = tmp_path / name
    source.write_text(code, encoding="utf-8")
    vault.add_suite(
        "auth",
        [str(source)],
        task="T1",
        baseline="red",
        timeout=30,
        leak=leak,
    )


def test_grade_pass(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "def test_a():\n    assert True\n\ndef test_b():\n    assert 1 == 1\n",
    )
    result = grade_suite(vault, "auth", repo)
    assert result.ok is True
    assert result.total == 2
    assert result.passed == 2
    assert result.failed == 0


def test_grade_fail_is_sanitized(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "import os\n\n"
        "def test_ok():\n    assert True\n\n"
        "def test_fail():\n"
        "    assert False, f'boom {os.getcwd()}'\n",
    )
    result = grade_suite(vault, "auth", repo)
    assert result.ok is False
    assert result.total == 2
    assert result.passed == 1
    assert result.failed == 1
    assert len(result.failures) == 1
    text = result.failures[0]
    assert text.startswith("hidden://auth/test_")
    assert "waker-vault" not in text
    assert str(repo) not in text
    assert str(vault.path) not in text


def test_nodeid_mapping_is_stable(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "def test_a():\n    assert True\n\n"
        "def test_b():\n    assert False\n\n"
        "def test_c():\n    assert True\n",
    )
    result = grade_suite(vault, "auth", repo)
    assert result.failed == 1
    assert result.failures[0].startswith("hidden://auth/test_2")


def test_minimal_leak_hides_assertion(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "def test_a():\n    assert False, 'SECRET_ASSERTION_TEXT'\n",
        leak="minimal",
    )
    result = grade_suite(vault, "auth", repo)
    assert result.failed == 1
    assert result.failures == ["hidden://auth/test_1 failed"]
    assert "SECRET_ASSERTION_TEXT" not in result.failures[0]


def test_import_error_is_suspect(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "import module_that_does_not_exist_xyz\n\ndef test_a():\n    assert True\n",
    )
    result = grade_suite(vault, "auth", repo)
    assert result.ok is False
    assert result.suspect is True


def test_temp_dir_is_removed(tmp_path: Path, monkeypatch):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert True\n")
    temp = tmp_path / "waker-vault-fake"
    temp.mkdir()
    monkeypatch.setattr(vault_runner.tempfile, "mkdtemp", lambda **kwargs: str(temp))

    grade_suite(vault, "auth", repo)
    assert not temp.exists()


def test_grade_vault_and_summary(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert True\n")
    results = grade_vault(vault, repo)
    assert set(results) == {"auth"}
    summary = summarize(results)
    assert summary["ok"] is True
    assert summary["total"] == 1
    assert summary["passed"] == 1
    assert summary["failed"] == 0


def test_grade_result_to_dict(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert False\n")
    result = grade_suite(vault, "auth", repo)
    payload = result.to_dict()
    assert payload["suite"] == "auth"
    assert payload["failed"] == 1
    assert payload["ok"] is False
    assert "failures" in payload
