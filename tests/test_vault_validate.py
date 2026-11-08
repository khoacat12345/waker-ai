from __future__ import annotations

import json
from pathlib import Path

from waker.cli import main
from waker.vault import Vault
from waker.vault_validate import validate_suite, validate_vault


def make_vault(tmp_path: Path) -> tuple[Path, Vault]:
    repo = tmp_path / "repo"
    repo.mkdir()
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    return repo, vault


def add_code(tmp_path: Path, vault: Vault, code: str, name: str = "test_hidden.py") -> None:
    source = tmp_path / name
    source.write_text(code, encoding="utf-8")
    vault.add_suite("auth", [str(source)], task="T1", baseline="red", timeout=30)


def test_red_suite_is_valid(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert False\n")

    result = validate_suite(vault, "auth", repo)
    assert result.ok is True
    assert result.tests == 1
    assert result.baseline == "red"


def test_green_suite_is_rejected(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert True\n")

    result = validate_suite(vault, "auth", repo)
    assert result.ok is False
    assert any("pass trên baseline" in message for message in result.messages)


def test_import_error_is_rejected(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "import module_that_does_not_exist_xyz\n\ndef test_a():\n    assert True\n")

    result = validate_suite(vault, "auth", repo)
    assert result.ok is False


def test_skip_marker_is_rejected(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "import pytest\n\n@pytest.mark.skip(reason='no')\ndef test_a():\n    assert False\n",
    )

    result = validate_suite(vault, "auth", repo)
    assert result.ok is False
    assert any("skip/xfail" in message for message in result.messages)


def test_flaky_suite_is_rejected(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(
        tmp_path,
        vault,
        "import os\n\n"
        "def test_a():\n"
        "    assert os.environ.get('WAKER_VALIDATE_RUN') == '2'\n\n"
        "def test_b():\n"
        "    assert os.environ.get('WAKER_VALIDATE_RUN') == '1'\n",
    )

    result = validate_suite(vault, "auth", repo)
    assert result.ok is False
    assert result.flaky is True or any("flaky" in message for message in result.messages)


def test_empty_suite_is_rejected(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "X = 1\n")

    result = validate_suite(vault, "auth", repo)
    assert result.ok is False
    assert any("không có test" in message for message in result.messages)


def test_validate_vault_marks_manifest(tmp_path: Path):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert False\n")

    results = validate_vault(vault, repo)
    assert results[0].ok is True
    reloaded = Vault.load(vault.vault_id, base_dir=tmp_path / "vaults")
    assert reloaded.suites["auth"]["validated_at"]
    assert reloaded.suites["auth"]["tests"] == 1


def test_cli_vault_validate_success(tmp_path: Path, capsys):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert False\n")

    code = main(
        [
            "vault",
            "validate",
            "--vault",
            vault.vault_id,
            "--repo",
            str(repo),
            "--vault-dir",
            str(tmp_path / "vaults"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["results"][0]["tests"] == 1


def test_cli_vault_validate_failure(tmp_path: Path, capsys):
    repo, vault = make_vault(tmp_path)
    add_code(tmp_path, vault, "def test_a():\n    assert True\n")

    code = main(
        [
            "vault",
            "validate",
            "--vault",
            vault.vault_id,
            "--repo",
            str(repo),
            "--vault-dir",
            str(tmp_path / "vaults"),
        ]
    )
    assert code == 1
    assert "FAIL" in capsys.readouterr().out
