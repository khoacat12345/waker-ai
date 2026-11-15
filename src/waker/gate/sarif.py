"""SARIF 2.1.0 export for anti-slop findings."""

from __future__ import annotations

from typing import Any

from .model import ScanResult

_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


def to_sarif(result: ScanResult, *, include_baseline: bool = False) -> dict[str, Any]:
    findings = [
        finding
        for finding in result.findings
        if include_baseline or not finding.baseline
    ]
    rule_ids = sorted({finding.rule for finding in findings})
    rules = [
        {
            "id": rule,
            "name": rule,
            "shortDescription": {"text": rule},
            "helpUri": "https://github.com/khoacat12345/waker-ai/blob/main/docs/ANTI_SLOP_SPEC.md",
        }
        for rule in rule_ids
    ]
    results: list[dict[str, Any]] = []
    for finding in findings:
        region: dict[str, Any] = {
            "startLine": max(1, finding.line),
            "startColumn": max(1, finding.col),
        }
        if finding.end_line:
            region["endLine"] = finding.end_line
        sarif_result = {
            "ruleId": finding.rule,
            "level": _LEVEL.get(finding.severity, "warning"),
            "message": {"text": finding.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": finding.path},
                        "region": region,
                    }
                }
            ],
            "partialFingerprints": {"waker/v1": finding.fingerprint},
            "properties": {
                "family": finding.family,
                "confidence": finding.confidence,
                "suggestion": finding.suggestion,
            },
        }
        results.append(sarif_result)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "waker-anti-slop",
                        "version": "2.0.0",
                        "rules": rules,
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "properties": {
                            "score": result.score,
                            "grade": result.grade,
                            "filesScanned": result.files_scanned,
                            "baselineSuppressed": result.baseline_suppressed,
                        },
                    }
                ],
                "results": results,
            }
        ],
    }
