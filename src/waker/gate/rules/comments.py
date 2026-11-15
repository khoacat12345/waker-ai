"""Comment, suppression, and stub slop rules."""

from __future__ import annotations

import ast
import io
import re
import tokenize

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding

_PLACEHOLDER_RE = re.compile(
    r"\b(?:rest of (?:the )?code|omitted for brevity|implement(?:ed)? later|"
    r"replace (?:this|me)|your code here|quick hack|good enough|for now|"
    r"not implemented|todo:\s*implement)\b",
    re.I,
)
_STEP_RE = re.compile(r"^(?:step\s*\d+|step\s*[:\-]|[-=*]{3,}|#{3,})", re.I)
_OBVIOUS_RE = re.compile(
    r"^(?:this (?:function|method|class|module|code)|the (?:function|method|class)|"
    r"returns?\b|initialize|set\b)",
    re.I,
)
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK)\b", re.I)
_NOQA_RE = re.compile(r"#\s*noqa\b(?P<rest>.*)", re.I)
_TYPE_IGNORE_RE = re.compile(r"#\s*(?:type|pyright):\s*ignore\b", re.I)


def _comments(source: str):
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                yield token.start[0], token.string
    except (tokenize.TokenError, IndentationError):
        for number, line in enumerate(source.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                yield number, stripped


def _is_abstract(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name in {"abstractmethod", "overload"}:
            return True
    return False


def _is_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if _is_abstract(node) or not node.body:
        return False
    for stmt in node.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
            target = stmt.exc.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if name == "NotImplementedError":
                continue
        return False
    return True


def _suppress_finding(
    path: str,
    number: int,
    text: str,
    config: AntiSlopConfig,
) -> Finding | None:
    if _TYPE_IGNORE_RE.search(text):
        return None  # TYPE008 owns type/pyright ignore.
    match = _NOQA_RE.search(text)
    if not match:
        return None
    rest = match.group("rest")
    has_code = bool(re.search(r"\[[^\]]+\]", rest)) or bool(re.match(r":\s*\S+", rest))
    has_reason = "reason=" in rest.lower() or "#" in rest
    if not has_code and config.require_suppression_code and not has_reason:
        return make_finding(
            "SUPPRESS001",
            config,
            path,
            number,
            1,
            "`# noqa` has no rule code or reason.",
            "Use `# noqa: E501  # reason: ...`, or fix the issue.",
            confidence="certain",
        )
    if not has_reason and config.require_suppression_reason and not has_code:
        return make_finding(
            "SUPPRESS002",
            config,
            path,
            number,
            1,
            "Suppression has no reason.",
            "Add a short reason after the directive.",
            confidence="certain",
        )
    return None


def comment_findings(
    tree: ast.Module,
    path: str,
    source: str,
    config: AntiSlopConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    for number, raw in _comments(source):
        text = raw.lstrip("#").strip()
        if not text or text.startswith("!"):
            continue
        lowered = text.lower()

        suppression = _suppress_finding(path, number, raw, config)
        if suppression:
            findings.append(suppression)
            continue

        if lowered.startswith(("waker:", "type:", "pyright:", "noqa", "pytest:", "safety:")):
            continue

        finding: Finding | None = None
        if config.ban_placeholder_comments and _PLACEHOLDER_RE.search(text):
            finding = make_finding(
                "COMMENT003",
                config,
                path,
                number,
                1,
                "Placeholder/apologetic comment instead of finished code.",
                "Implement the behavior or remove the comment.",
            )
        elif config.ban_step_comments and _STEP_RE.match(text):
            finding = make_finding(
                "COMMENT002",
                config,
                path,
                number,
                1,
                "Step/section comment suggests the function needs splitting.",
                "Extract each step into a named helper.",
                confidence="likely",
            )
        elif config.ban_obvious_comments and _OBVIOUS_RE.match(text):
            finding = make_finding(
                "COMMENT001",
                config,
                path,
                number,
                1,
                "Comment restates what the code already says.",
                "Explain why or remove it; rename the code instead.",
                confidence="likely",
            )
        elif _TODO_RE.search(text) and not re.search(r"#\d+|@\w+|20\d\d", text):
            finding = make_finding(
                "COMMENT004",
                config,
                path,
                number,
                1,
                "TODO/FIXME/HACK has no owner, ticket, or date.",
                "Attach an owner/ticket or remove the note.",
                confidence="likely",
            )
        if finding:
            findings.append(finding)

    policy = config.stub_policy
    if policy != "off":
        severity = "error" if policy == "error" else "warning"
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("test_"):
                continue
            if not _is_stub(node):
                continue
            finding = make_finding(
                "STUB001",
                config,
                path,
                node.lineno,
                node.col_offset + 1,
                f"Function `{node.name}` is a stub (`pass`/`...`/NotImplementedError).",
                "Implement the function or mark it abstract/protocol-only.",
                end_line=getattr(node, "end_lineno", None),
                confidence="certain",
                severity=severity,
            )
            if finding:
                findings.append(finding)
    return findings
