"""Hidden Test Vault (blind evaluation, v1.1 Phase A).

Storage lives outside the repository so the worker never sees the tests in its
working tree, git history, or prompt. Only the random ``vault_id`` travels into
the run configuration.

Phase A implements: create, add (merge), list, remove, hashes.
Validation (baseline red / collect / flaky) is Phase B; the blind pytest runner
is Phase C.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .state import utcnow, write_json_atomic

VAULT_ID_RE = re.compile(r"^[a-f0-9]{12}$")
SUITE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
BASELINES = ("red", "green")
LEAK_LEVELS = ("minimal", "message")
DEFAULT_TIMEOUT = 120


def vault_root(override: str | None = None) -> Path:
    """Return the directory that holds all vaults (never inside the repo)."""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("WAKER_VAULT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "waker" / "vault"


def new_vault_id() -> str:
    return hashlib.sha256(os.urandom(16)).hexdigest()[:12]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def suite_hash(files: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda entry: entry["name"]):
        digest.update(item["name"].encode("utf-8"))
        digest.update(item["sha256"].encode("utf-8"))
    return digest.hexdigest()


@dataclass
class Vault:
    vault_id: str
    path: Path
    manifest: dict

    @property
    def suites(self) -> dict:
        return self.manifest.get("suites", {})

    @classmethod
    def create(
        cls,
        repo: str | Path,
        vault_id: str | None = None,
        base_dir: str | Path | None = None,
    ) -> "Vault":
        vault_id = vault_id or new_vault_id()
        if not VAULT_ID_RE.match(vault_id):
            raise ValueError("vault_id phải là 12 ký tự hex thường")
        path = vault_root(str(base_dir) if base_dir else None) / vault_id
        if path.exists():
            raise FileExistsError(f"vault {vault_id} đã tồn tại: {path}")
        (path / "suites").mkdir(parents=True, exist_ok=False)
        if os.name != "nt":
            try:
                path.chmod(0o700)
            except OSError:
                pass
        manifest = {
            "vault_id": vault_id,
            "repo": str(Path(repo).resolve()),
            "created_at": utcnow(),
            "suites": {},
        }
        vault = cls(vault_id, path, manifest)
        vault.save()
        return vault

    @classmethod
    def load(cls, vault_id: str, base_dir: str | Path | None = None) -> "Vault":
        if not VAULT_ID_RE.match(vault_id or ""):
            raise ValueError("invalid vault id")
        path = vault_root(str(base_dir) if base_dir else None) / vault_id
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"vault {vault_id} không tồn tại: {path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("vault_id") != vault_id:
            raise ValueError("manifest vault_id mismatch")
        return cls(vault_id, path, manifest)

    def save(self) -> None:
        write_json_atomic(self.path / "manifest.json", self.manifest)

    def suite_dir(self, suite: str) -> Path:
        if not SUITE_RE.match(suite or ""):
            raise ValueError("invalid suite name")
        return self.path / "suites" / suite

    def add_suite(
        self,
        suite: str,
        files: list[str],
        task: str | None = None,
        baseline: str = "red",
        timeout: int = DEFAULT_TIMEOUT,
        leak: str = "message",
    ) -> dict:
        """Copy files into the suite and merge with existing files by name."""
        if baseline not in BASELINES:
            raise ValueError(f"baseline must be one of {BASELINES}")
        if leak not in LEAK_LEVELS:
            raise ValueError(f"leak must be one of {LEAK_LEVELS}")
        target = self.suite_dir(suite)
        target.mkdir(parents=True, exist_ok=True)

        existing = {
            item["name"]: item
            for item in self.suites.get(suite, {}).get("files", [])
        }
        for file_name in files:
            source = Path(file_name).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(f"không tìm thấy file: {source}")
            destination = target / source.name
            shutil.copyfile(source, destination)
            existing[source.name] = {
                "name": source.name,
                "sha256": _sha256_file(destination),
            }

        file_list = sorted(existing.values(), key=lambda item: item["name"])
        entry = {
            "task": task,
            "files": file_list,
            "hash": suite_hash(file_list),
            "baseline": baseline,
            "validated_at": None,
            "tests": 0,
            "timeout": int(timeout),
            "leak": leak,
        }
        self.manifest.setdefault("suites", {})[suite] = entry
        self.save()
        return entry

    def remove_suite(self, suite: str) -> bool:
        if suite not in self.suites:
            return False
        shutil.rmtree(self.suite_dir(suite), ignore_errors=True)
        del self.manifest["suites"][suite]
        self.save()
        return True

    def vault_hash(self) -> str:
        payload = {
            name: entry["hash"]
            for name, entry in sorted(self.suites.items())
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def summary(self) -> list[dict]:
        return [
            {
                "suite": name,
                "task": entry.get("task"),
                "files": len(entry.get("files", [])),
                "hash": entry.get("hash", "")[:16],
                "baseline": entry.get("baseline"),
                "validated": bool(entry.get("validated_at")),
                "tests": entry.get("tests", 0),
                "leak": entry.get("leak"),
            }
            for name, entry in sorted(self.suites.items())
        ]
