"""Blind grading: run hidden suites and return only sanitized diagnostics.

The worker never sees the test source, the vault path, the temp path, or raw
locals. Failures are mapped to opaque ids (``test_1``...), and paths are
redacted before they reach a wake prompt or the ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .vault import Vault
from .vault_runner import LOCATION_RE, SuiteRun, run_suite

MAX_FAILURES = 5
MAX_MESSAGE = 300
PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\s:]+|/[^\s:]+)")


@dataclass
class GradeResult:
    suite: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)
    suspect: bool = False
    timed_out: bool = False
    exit_code: int | None = None
    leak: str = "message"
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.failed == 0

    def to_dict(self) -> dict:
        return {
            "suite": self.suite,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "failures": self.failures,
            "suspect": self.suspect,
            "timed_out": self.timed_out,
            "exit_code": self.exit_code,
            "leak": self.leak,
            "ok": self.ok,
        }


def _nodeid_map(run: SuiteRun) -> dict[str, str]:
    return {
        nodeid: f"test_{index + 1}"
        for index, nodeid in enumerate(sorted(set(run.nodeids)))
    }


def _failure_message(output: str, nodeid: str) -> str:
    for line in output.splitlines():
        if nodeid in line and " - " in line:
            return line.split(" - ", 1)[1].strip()
    for match in LOCATION_RE.finditer(output):
        return match.group(1).strip()
    return ""


def _clean_message(text: str) -> str:
    text = PATH_RE.sub("<path>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_MESSAGE]


def sanitize(run: SuiteRun, suite: str, leak: str) -> list[str]:
    mapping = _nodeid_map(run)
    results: list[str] = []
    for index, nodeid in enumerate(run.failures[:MAX_FAILURES]):
        test_id = mapping.get(nodeid) or f"test_{index + 1}"
        if leak == "minimal":
            results.append(f"hidden://{suite}/{test_id} failed")
            continue
        message = _clean_message(_failure_message(run.output, nodeid))
        if message:
            results.append(f"hidden://{suite}/{test_id}: {message}")
        else:
            results.append(f"hidden://{suite}/{test_id} failed")
    return results


def grade_suite(
    vault: Vault,
    suite: str,
    repo: str | Path,
    timeout: float | None = None,
    extra_env: dict[str, str] | None = None,
) -> GradeResult:
    entry = vault.suites.get(suite, {})
    leak = entry.get("leak", "message")
    effective_timeout = float(timeout or entry.get("timeout", 120))

    run = run_suite(vault, suite, repo, timeout=effective_timeout, extra_env=extra_env)
    nodeids = sorted(set(run.nodeids))
    total = len(nodeids)
    failed = len(run.failures)
    result = GradeResult(
        suite=suite,
        total=total,
        passed=max(0, total - failed),
        failed=failed,
        failures=sanitize(run, suite, leak),
        suspect=run.suspect,
        timed_out=run.timed_out,
        exit_code=run.exit_code,
        leak=leak,
        duration=run.duration,
    )
    return result


def grade_vault(
    vault: Vault,
    repo: str | Path,
    suites: list[str] | None = None,
) -> dict[str, GradeResult]:
    names = suites if suites is not None else sorted(vault.suites)
    return {name: grade_suite(vault, name, repo) for name in names}


def summarize(results: dict[str, GradeResult]) -> dict:
    total = sum(result.total for result in results.values())
    passed = sum(result.passed for result in results.values())
    failed = sum(result.failed for result in results.values())
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "ok": bool(results) and all(result.ok for result in results.values()),
        "suspect": any(result.suspect for result in results.values()),
        "timed_out": any(result.timed_out for result in results.values()),
    }
