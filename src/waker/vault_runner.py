"""Low-level runner for hidden vault suites.

Copies the suite to a temp directory outside the repo, runs pytest with the repo
on ``PYTHONPATH``, and deletes the temp directory afterwards. Phase B uses this
for validation; Phase C adds sanitized grading on top.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import winproc
from .vault import Vault

FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)
LOCATION_RE = re.compile(r"^(\S+\.py:\d+:\s+.+)$", re.MULTILINE)
SUSPECT_TOKENS = (
    "importerror",
    "modulenotfounderror",
    "attributeerror",
    "no module named",
    "error collecting",
    "errors during collection",
    "syntaxerror",
)


@dataclass
class SuiteRun:
    exit_code: int | None
    output: str
    duration: float
    timed_out: bool
    nodeids: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    suspect: bool = False


def copy_suite(vault: Vault, suite: str) -> Path:
    source = vault.suite_dir(suite)
    if not source.is_dir():
        raise FileNotFoundError(f"suite {suite} không tồn tại trong vault")
    temp = Path(tempfile.mkdtemp(prefix="waker-vault-"))
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        destination = temp / item.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, destination)
    return temp


def _env(repo: str | Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    root = str(Path(repo).resolve())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")
    env["WAKER_REPO"] = root
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if extra:
        env.update(extra)
    return env


def collect_nodeids(output: str) -> list[str]:
    ids: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if "::" in stripped and not stripped.startswith(("=", "FAILED", "ERROR")):
            ids.append(stripped)
    return sorted(set(ids))


def parse_failures(output: str) -> list[str]:
    failures = [match.group(1) for match in FAILED_RE.finditer(output)]
    if not failures:
        failures = [match.group(1).strip() for match in LOCATION_RE.finditer(output)]
    return failures


def looks_suspect(output: str, failures: list[str]) -> bool:
    lowered = output.lower()
    if "error collecting" in lowered or "errors during collection" in lowered:
        return True
    summary = "\n".join(
        line
        for line in output.splitlines()
        if line.startswith(("FAILED ", "ERROR "))
    ).lower()
    if summary:
        return any(token in summary for token in SUSPECT_TOKENS)
    if not failures:
        return any(token in lowered for token in SUSPECT_TOKENS)
    text = " ".join(failures).lower()
    return any(token in text for token in SUSPECT_TOKENS)


def run_suite(
    vault: Vault,
    suite: str,
    repo: str | Path,
    timeout: float = 120.0,
    extra_env: dict[str, str] | None = None,
) -> SuiteRun:
    temp = copy_suite(vault, suite)
    started = time.time()
    try:
        collect_cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(temp),
            "--collect-only",
            "-q",
            "--disable-warnings",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(temp),
        ]
        collected = winproc.run(
            collect_cmd,
            cwd=str(temp),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_env(repo, extra_env),
        )
        nodeids = collect_nodeids((collected.stdout or "") + (collected.stderr or ""))

        run_cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(temp),
            "-q",
            "--tb=line",
            "--disable-warnings",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(temp),
        ]
        result = winproc.run(
            run_cmd,
            cwd=str(temp),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_env(repo, extra_env),
        )
        output = (result.stdout or "") + (result.stderr or "")
        failures = parse_failures(output)
        return SuiteRun(
            exit_code=result.returncode,
            output=output,
            duration=time.time() - started,
            timed_out=False,
            nodeids=nodeids,
            failures=failures,
            suspect=looks_suspect(output, failures),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return SuiteRun(
            exit_code=None,
            output=stdout + stderr,
            duration=time.time() - started,
            timed_out=True,
        )
    finally:
        shutil.rmtree(temp, ignore_errors=True)
