"""Silent and broad exception handlers."""

from __future__ import annotations

import ast

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding

_BROAD_NAMES = {"Exception", "BaseException", "BaseExceptionGroup"}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in _BROAD_NAMES
    if isinstance(handler.type, ast.Attribute):
        return handler.type.attr in _BROAD_NAMES
    if isinstance(handler.type, ast.Tuple):
        return any(
            isinstance(item, ast.Name) and item.id in _BROAD_NAMES
            for item in handler.type.elts
        )
    return False


def _is_noop(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Return):
        return stmt.value is None or (
            isinstance(stmt.value, ast.Constant) and stmt.value.value is None
        )
    return False


def silent_exception_findings(
    tree: ast.Module, path: str, config: AntiSlopConfig
) -> list[Finding]:
    if not (config.ban_broad_except or config.ban_silent_except):
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_broad(node) or not all(_is_noop(stmt) for stmt in node.body):
            continue
        finding = make_finding(
            "SLOP002",
            config,
            path,
            node.lineno,
            node.col_offset + 1,
            "Silent broad exception handler.",
            "Catch a specific exception; if recovery is impossible, log the "
            "error and re-raise.",
            end_line=getattr(node, "end_lineno", None),
        )
        if finding:
            findings.append(finding)
    return findings
