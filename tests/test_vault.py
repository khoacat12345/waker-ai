from __future__ import annotations

import json
from pathlib import Path

import pytest

from waker.cli import main
from waker.vault import VAULT_ID_RE, Vault, suite_hash


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def write_test(path: Path, marker: str = "ok") -> Path:
    path.write_text(
        "def test_hidden():\n"
        f"    assert {marker!r}\n",
        encoding="utf-8",
    )
    return path


def test_create_outside_repo(tmp_path: Path):
    repo = make_repo(tmp_path)
    base = tmp_path / "vaults"
    vault = Vault.create(repo, base_dir=base)

    assert VAULT_ID_RE.match(vault.vault_id)
    assert vault.path.is_relative_to(base)
    assert not vault.path.is_relative_to(repo)
    assert (vault.path / "manifest.json").exists()
    assert vault.manifest["repo"] == str(repo.resolve())
    assert vault.manifest["suites"] == {}


def test_add_merges_files_and_hashes(tmp_path: Path):
    repo = make_repo(tmp_path)
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    first = write_test(tmp_path / "test_a.py", "a")
    second = write_test(tmp_path / "test_b.py", "b")

    entry = vault.add_suite("auth", [str(first)], task="T1")
    assert [item["name"] for item in entry["files"]] == ["test_a.py"]
    assert (vault.path / "suites" / "auth" / "test_a.py").exists()
    assert entry["hash"] == suite_hash(entry["files"])
    assert entry["baseline"] == "red"
    assert entry["validated_at"] is None

    entry = vault.add_suite("auth", [str(second)], task="T1")
    assert [item["name"] for item in entry["files"]] == ["test_a.py", "test_b.py"]
    assert entry["hash"] == suite_hash(entry["files"])


def test_hash_changes_when_content_changes(tmp_path: Path):
    repo = make_repo(tmp_path)
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    source = write_test(tmp_path / "test_a.py", "one")
    first = vault.add_suite("auth", [str(source)], task="T1")
    vault_hash = vault.vault_hash()

    source.write_text("def test_hidden():\n    assert 'two'\n", encoding="utf-8")
    second = vault.add_suite("auth", [str(source)], task="T1")

    assert first["hash"] != second["hash"]
    assert vault_hash != vault.vault_hash()


def test_remove_suite(tmp_path: Path):
    repo = make_repo(tmp_path)
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    source = write_test(tmp_path / "test_a.py")
    vault.add_suite("auth", [str(source)], task="T1")
    assert vault.remove_suite("auth") is True
    assert "auth" not in vault.suites
    assert not (vault.path / "suites" / "auth").exists()
    assert vault.remove_suite("auth") is False


def test_invalid_vault_id_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        Vault.load("../evil", base_dir=tmp_path / "vaults")


def test_manifest_does_not_store_source(tmp_path: Path):
    repo = make_repo(tmp_path)
    vault = Vault.create(repo, base_dir=tmp_path / "vaults")
    secret = "SECRET_ASSERTION_MARKER_42"
    source = tmp_path / "test_a.py"
    source.write_text(
        "def test_hidden():\n"
        f"    assert 'x' == '{secret}'\n",
        encoding="utf-8",
    )
    vault.add_suite("auth", [str(source)], task="T1")
    manifest = (vault.path / "manifest.json").read_text(encoding="utf-8")
    assert secret not in manifest
    assert "assert" not in manifest


def test_cli_vault_flow(tmp_path: Path, capsys):
    repo = make_repo(tmp_path)
    base = tmp_path / "vaults"
    source = write_test(tmp_path / "test_a.py")

    code = main(
        ["vault", "init", "--repo", str(repo), "--vault-dir", str(base), "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    vault_id = payload["vault_id"]
    assert payload["repo"] == str(repo.resolve())

    code = main(
        [
            "vault",
            "add",
            "--vault",
            vault_id,
            "--suite",
            "auth",
            "--task",
            "T1",
            str(source),
            "--vault-dir",
            str(base),
            "--json",
        ]
    )
    assert code == 0
    added = json.loads(capsys.readouterr().out)
    assert added["suite"] == "auth"
    assert added["files"] == ["test_a.py"]
    assert added["validated"] is False

    code = main(
        ["vault", "list", "--vault", vault_id, "--vault-dir", str(base), "--json"]
    )
    assert code == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["suites"][0]["suite"] == "auth"
    assert listed["suites"][0]["task"] == "T1"

    code = main(
        [
            "vault",
            "rm",
            "--vault",
            vault_id,
            "--suite",
            "auth",
            "--yes",
            "--vault-dir",
            str(base),
        ]
    )
    assert code == 0
    capsys.readouterr()

    code = main(
        ["vault", "list", "--vault", vault_id, "--vault-dir", str(base), "--json"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["suites"] == []


def test_cli_rm_requires_yes(tmp_path: Path, capsys):
    repo = make_repo(tmp_path)
    base = tmp_path / "vaults"
    vault = Vault.create(repo, base_dir=base)
    source = write_test(tmp_path / "test_a.py")
    vault.add_suite("auth", [str(source)], task="T1")

    code = main(
        ["vault", "rm", "--vault", vault.vault_id, "--suite", "auth", "--vault-dir", str(base)]
    )
    assert code == 2
    assert "yes" in capsys.readouterr().err


def test_cli_invalid_vault_id(tmp_path: Path, capsys):
    code = main(["vault", "list", "--vault", "../evil", "--vault-dir", str(tmp_path)])
    assert code == 1
    assert "invalid vault id" in capsys.readouterr().err
