"""Security guard rules."""

from __future__ import annotations

import ast
import re

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_SENSITIVE_NAME = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)",
    re.I,
)
_PLACEHOLDER = re.compile(r"(?:example|changeme|dummy|placeholder|xxx|<[^>]+>)", re.I)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _safe_loader(value: ast.AST | None) -> bool:
    if value is None:
        return False
    dotted = _dotted(value)
    return dotted.endswith("SafeLoader") or dotted in {"SafeLoader", "yaml.SafeLoader"}


def _mask(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return f"{value[:4]}…"


def _secret_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def security_findings(
    tree: ast.Module,
    path: str,
    source: str,
    config: AntiSlopConfig,
) -> list[Finding]:
    findings: list[Finding] = []

    def add(
        rule: str,
        node: ast.AST,
        message: str,
        suggestion: str,
    ) -> None:
        finding = make_finding(
            rule,
            config,
            path,
            getattr(node, "lineno", 1),
            getattr(node, "col_offset", 0) + 1,
            message,
            suggestion,
            end_line=getattr(node, "end_lineno", None),
        )
        if finding:
            findings.append(finding)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            short = dotted.split(".")[-1]
            if config.ban_eval and dotted in {
                "eval",
                "exec",
                "compile",
                "builtins.eval",
                "builtins.exec",
                "builtins.compile",
            }:
                add(
                    "SEC001",
                    node,
                    f"Dynamic code execution via `{dotted}()`.",
                    "Parse data or use an explicit dispatch table; never eval untrusted input.",
                )
            if config.ban_pickle and (
                dotted in {"pickle.loads", "pickle.load", "marshal.loads", "marshal.load"}
            ):
                add(
                    "SEC002",
                    node,
                    f"Unsafe deserialization via `{dotted}()`.",
                    "Use JSON or a schema-validated format, not pickle/marshal.",
                )
            if config.ban_shell:
                if dotted in {"os.system", "os.popen"}:
                    add(
                        "SEC003",
                        node,
                        f"Shell execution via `{dotted}()`.",
                        "Use an argv list with subprocess and validate each argument.",
                    )
                if dotted in {
                    "subprocess.run",
                    "subprocess.Popen",
                    "subprocess.call",
                    "subprocess.check_call",
                    "subprocess.check_output",
                }:
                    shell = _kw(node, "shell")
                    if isinstance(shell, ast.Constant) and shell.value is True:
                        add(
                            "SEC003",
                            node,
                            f"`shell=True` in `{dotted}()`.",
                            "Pass an argv list and keep shell=False.",
                        )
            if config.ban_yaml_load and dotted in {"yaml.load", "yaml.unsafe_load"}:
                loader = _kw(node, "Loader") or _kw(node, "loader")
                if not _safe_loader(loader):
                    add(
                        "SEC004",
                        node,
                        f"`{dotted}()` without a SafeLoader.",
                        "Use `yaml.safe_load()` or `Loader=yaml.SafeLoader`.",
                    )
            if config.ban_verify_false and dotted.startswith(("requests.", "httpx.")):
                verify = _kw(node, "verify")
                if isinstance(verify, ast.Constant) and verify.value is False:
                    add(
                        "SEC005",
                        node,
                        f"TLS verification disabled in `{dotted}()`.",
                        "Remove verify=False; fix the certificate/trust store instead.",
                    )
            if short in {"execute", "executemany"} and node.args:
                first = node.args[0]
                dynamic = isinstance(first, ast.JoinedStr) or (
                    isinstance(first, ast.BinOp)
                    and isinstance(first.op, (ast.Mod, ast.Add))
                ) or (
                    isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute)
                    and first.func.attr == "format"
                )
                if dynamic:
                    add(
                        "SEC007",
                        node,
                        "SQL query is built with string interpolation.",
                        "Use parameterized queries; never concatenate user input.",
                    )

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = _secret_string(node.value)
        if not value or _PLACEHOLDER.search(value):
            continue
        names = [
            target.id
            for target in targets
            if isinstance(target, ast.Name)
        ]
        looks_secret = any(_SENSITIVE_NAME.search(name) for name in names)
        matched = any(pattern.search(value) for pattern in _SECRET_PATTERNS)
        if config.ban_secrets and (looks_secret or matched) and len(value) >= 8:
            add(
                "SEC006",
                node,
                f"Hardcoded secret in `{names[0] if names else 'value'}` "
                f"(value {_mask(value)}).",
                "Load secrets from environment/keychain; rotate the exposed value.",
            )
    return findings
