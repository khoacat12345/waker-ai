"""Optional JavaScript/TypeScript linter adapters.

The core gate stays Python-stdlib-only.  These adapters run an installed
``oxlint`` or ``eslint`` binary through the existing no-window subprocess
wrapper; no Node package is vendored and no Node runtime is required by Waker
itself.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .. import winproc
from .model import Finding

JS_EXTENSIONS = (
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
)

Runner = Callable[[list[str], Path, float], Any]


class ExternalAdapterError(ValueError):
    """Raised when an external linter returns an unusable payload."""


def _relative(repo: Path, value: Any) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    try:
        resolved = path.resolve() if path.is_absolute() else (repo / path).resolve()
        return resolved.relative_to(repo).as_posix()
    except (OSError, ValueError):
        return None


def _integer(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value) if value is not None else ""


@dataclass
class ExternalAdapter:
    """Small interface for an optional external linter.

    Subclasses provide ``parse`` and may override ``build_command``.  A custom
    adapter can be passed to :func:`run_external_linters` without changing the
    core scanner.
    """

    name: str = "external"
    command: tuple[str, ...] = ()
    extensions: tuple[str, ...] = JS_EXTENSIONS
    executable: str | None = None
    timeout: float = 60.0
    available_override: bool | None = None
    severity: str = "warning"
    suggestion: str = "Fix the reported JS/TS linter issue, then re-run the audit."

    def executable_name(self) -> str:
        if self.executable:
            return self.executable
        return self.command[0] if self.command else self.name

    def available(self) -> bool:
        if self.available_override is not None:
            return self.available_override
        return bool(shutil.which(self.executable_name()))

    def build_command(self, files: Sequence[str]) -> list[str]:
        return [*self.command, *files]

    def parse(self, payload: str, repo: Path) -> list[Finding]:
        raise NotImplementedError

    def make_finding(
        self,
        repo: Path,
        *,
        file: Any,
        line: Any,
        column: Any,
        rule: Any,
        message: Any,
        suggestion: str | None = None,
        severity: str | None = None,
    ) -> Finding | None:
        path = _relative(repo, file)
        if path is None:
            return None
        rule_id = _text(rule).strip() or "lint"
        return Finding(
            rule=f"{self.name}:{rule_id}",
            severity=severity or self.severity,
            path=path,
            line=_integer(line, 1),
            col=_integer(column, 1),
            message=_text(message).strip() or "External linter finding.",
            suggestion=suggestion or self.suggestion,
            family="external",
            confidence="likely",
        )


@dataclass
class EslintAdapter(ExternalAdapter):
    name: str = "eslint"
    command: tuple[str, ...] = ("eslint", "--format", "json")

    def parse(self, payload: str, repo: Path) -> list[Finding]:
        try:
            data = json.loads(payload or "[]")
        except json.JSONDecodeError as exc:
            raise ExternalAdapterError(f"{self.name}: invalid JSON: {exc}") from exc
        if isinstance(data, dict):
            data = data.get("results") or data.get("files") or []
        if not isinstance(data, list):
            raise ExternalAdapterError(f"{self.name}: expected a JSON list")
        findings: list[Finding] = []
        for result in data:
            if not isinstance(result, dict):
                continue
            file = result.get("filePath") or result.get("filename")
            for message in result.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                finding = self.make_finding(
                    repo,
                    file=file,
                    line=message.get("line"),
                    column=message.get("column"),
                    rule=message.get("ruleId") or "eslint",
                    message=message.get("message"),
                    suggestion=message.get("suggestion"),
                )
                if finding is not None:
                    findings.append(finding)
        return findings


@dataclass
class OxlintAdapter(ExternalAdapter):
    name: str = "oxlint"
    command: tuple[str, ...] = ("oxlint", "--format", "json")

    def _diagnostics(self, payload: str) -> list[Any]:
        try:
            data = json.loads(payload or "[]")
        except json.JSONDecodeError as exc:
            raise ExternalAdapterError(f"{self.name}: invalid JSON: {exc}") from exc
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            raise ExternalAdapterError(f"{self.name}: expected a JSON object/list")
        for key in ("diagnostics", "errors", "warnings", "results", "messages"):
            values = data.get(key)
            if isinstance(values, list):
                return values
        return []

    def parse(self, payload: str, repo: Path) -> list[Finding]:
        findings: list[Finding] = []
        for item in self._diagnostics(payload):
            if not isinstance(item, dict):
                continue
            # Some oxlint output groups messages by file, like ESLint.
            if isinstance(item.get("messages"), list):
                file = item.get("filename") or item.get("filePath") or item.get("path")
                for message in item["messages"]:
                    if isinstance(message, dict):
                        finding = self.make_finding(
                            repo,
                            file=file,
                            line=message.get("line"),
                            column=message.get("column"),
                            rule=message.get("ruleId") or message.get("code"),
                            message=message.get("message"),
                        )
                        if finding is not None:
                            findings.append(finding)
                continue

            labels = item.get("labels") or item.get("label") or []
            label = labels[0] if isinstance(labels, list) and labels else {}
            span = label.get("span") if isinstance(label, dict) else {}
            span = span or {}
            file = (
                item.get("filename")
                or item.get("filePath")
                or item.get("path")
                or item.get("file")
            )
            finding = self.make_finding(
                repo,
                file=file,
                line=item.get("line") or item.get("startLine") or span.get("line"),
                column=item.get("column") or span.get("column"),
                rule=item.get("code") or item.get("ruleId") or item.get("rule"),
                message=item.get("message") or item.get("description"),
            )
            if finding is not None:
                findings.append(finding)
        return findings


@dataclass
class ExternalResult:
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    adapters_run: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def _default_runner(command: list[str], cwd: Path, timeout: float):
    return winproc.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _normalise_files(repo: Path, files: Sequence[str | Path]) -> list[str]:
    result: set[str] = set()
    for raw in files:
        path = Path(raw)
        if not path.is_absolute():
            path = repo / path
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(repo).as_posix()
        except (OSError, ValueError):
            continue
        if resolved.is_file() and path.suffix.lower() in JS_EXTENSIONS:
            result.add(relative)
    return sorted(result)


def run_external_linters(
    repo: str | Path,
    files: Sequence[str | Path],
    *,
    adapters: Sequence[ExternalAdapter] | None = None,
    runner: Runner | None = None,
    timeout: float | None = None,
) -> ExternalResult:
    """Run optional external linters over JS/TS files.

    Missing binaries and malformed linter output are reported as non-fatal
    ``errors``; they never make Waker itself depend on Node or a linter package.
    """
    root = Path(repo).resolve()
    selected = _normalise_files(root, files)
    result = ExternalResult(files=selected)
    if not selected:
        return result
    chosen = list(adapters) if adapters is not None else [
        OxlintAdapter(),
        EslintAdapter(),
    ]
    execute = runner or _default_runner
    for adapter in chosen:
        matching = [
            path
            for path in selected
            if Path(path).suffix.lower() in adapter.extensions
        ]
        if not matching:
            continue
        if not adapter.available():
            result.errors.append(
                f"{adapter.name}: executable `{adapter.executable_name()}` is not installed"
            )
            continue
        command = adapter.build_command(matching)
        try:
            completed = execute(
                command,
                root,
                timeout if timeout is not None else adapter.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - optional adapter must be non-fatal
            result.errors.append(f"{adapter.name}: {exc}")
            continue
        stdout = getattr(completed, "stdout", "") or ""
        stderr = getattr(completed, "stderr", "") or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if not stdout and stderr:
            result.errors.append(f"{adapter.name}: {stderr.strip()[:300]}")
            continue
        try:
            result.findings.extend(adapter.parse(stdout, root))
        except ExternalAdapterError as exc:
            result.errors.append(str(exc))
            continue
        except Exception as exc:  # noqa: BLE001 - never trust external output shape
            result.errors.append(f"{adapter.name}: {exc}")
            continue
        result.adapters_run.append(adapter.name)
    return result


__all__ = [
    "ESLintAdapter",
    "EslintAdapter",
    "ExternalAdapter",
    "ExternalAdapterError",
    "ExternalResult",
    "JS_EXTENSIONS",
    "OxlintAdapter",
    "run_external_linters",
]

ESLintAdapter = EslintAdapter
