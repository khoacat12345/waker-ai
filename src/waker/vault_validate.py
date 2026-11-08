"""Validate a hidden test suite before a blind run starts.

Rules (see docs/BLIND_EVALUATION_SPEC.md):
- collect-only must succeed;
- ``baseline: red`` must fail on the current code; ``green`` must pass;
- no skip/xfail;
- at least one test;
- two runs must agree (no flaky).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .state import utcnow
from .vault import Vault
from .vault_runner import SuiteRun, run_suite

SKIP_MARKERS = (
    "pytest.mark.skip",
    "pytest.mark.xfail",
    "pytest.skip(",
    "@pytest.mark.skipif",
)


@dataclass
class ValidationResult:
    suite: str
    ok: bool
    tests: int = 0
    baseline: str = "red"
    flaky: bool = False
    suspect: bool = False
    messages: list[str] = field(default_factory=list)
    runs: list[SuiteRun] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suite": self.suite,
            "ok": self.ok,
            "tests": self.tests,
            "baseline": self.baseline,
            "flaky": self.flaky,
            "suspect": self.suspect,
            "messages": self.messages,
        }


def _suite_source(vault: Vault, suite: str) -> str:
    source = vault.suite_dir(suite)
    text = ""
    for item in source.rglob("*.py"):
        text += item.read_text(encoding="utf-8", errors="ignore")
    return text


def validate_suite(
    vault: Vault,
    suite: str,
    repo: str | Path,
    runs: int = 2,
) -> ValidationResult:
    entry = vault.suites.get(suite)
    if not entry:
        return ValidationResult(suite, False, messages=["suite không tồn tại"])

    result = ValidationResult(
        suite=suite,
        ok=False,
        baseline=entry.get("baseline", "red"),
    )

    source = _suite_source(vault, suite)
    for marker in SKIP_MARKERS:
        if marker in source:
            result.messages.append(f"đề chứa skip/xfail: {marker}")
            return result

    outcomes: list[SuiteRun] = []
    for index in range(max(2, runs)):
        outcome = run_suite(
            vault,
            suite,
            repo,
            timeout=float(entry.get("timeout", 120)),
            extra_env={"WAKER_VALIDATE_RUN": str(index + 1)},
        )
        outcomes.append(outcome)
        if outcome.timed_out:
            result.messages.append("đề chạy quá timeout")
            result.runs = outcomes
            return result
        if outcome.exit_code == 5:
            result.messages.append("đề không có test nào")
            result.runs = outcomes
            return result
        if outcome.exit_code in (2, 3, 4):
            result.messages.append(
                f"pytest exit {outcome.exit_code} (collect/usage error)"
            )
            result.runs = outcomes
            return result
        if not outcome.nodeids and not outcome.failures:
            result.messages.append("đề không có test nào")
            result.runs = outcomes
            return result
        if outcome.suspect and result.baseline == "red":
            result.messages.append("đề fail vì import/attribute/collection error")
            result.runs = outcomes
            return result

    result.runs = outcomes
    result.tests = max((len(outcome.nodeids) for outcome in outcomes), default=0)
    if result.tests == 0:
        result.messages.append("đề không có test nào")
        return result

    red_results = [outcome.exit_code != 0 for outcome in outcomes]
    if result.baseline == "red":
        if not all(red_results):
            result.messages.append("đề pass trên baseline (không chứng minh được gì)")
            return result
    else:
        if any(red_results):
            result.messages.append("đề fail trên baseline (baseline: green)")
            return result

    if len(set(red_results)) > 1:
        result.flaky = True
        result.messages.append("đề flaky: kết quả 2 lần chạy khác nhau")
        return result

    failure_sets = {
        tuple(sorted(outcome.failures)) for outcome in outcomes if outcome.exit_code != 0
    }
    if len(failure_sets) > 1:
        result.flaky = True
        result.messages.append("đề flaky: tập failure khác nhau giữa 2 lần chạy")
        return result

    result.ok = True
    return result


def validate_vault(
    vault: Vault,
    repo: str | Path,
    suite: str | None = None,
    runs: int = 2,
) -> list[ValidationResult]:
    names = [suite] if suite else sorted(vault.suites)
    results: list[ValidationResult] = []
    for name in names:
        result = validate_suite(vault, name, repo, runs=runs)
        results.append(result)
        if result.ok and name in vault.suites:
            vault.suites[name]["validated_at"] = utcnow()
            vault.suites[name]["tests"] = result.tests
            vault.save()
    return results
