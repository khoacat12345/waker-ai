"""Duplicate symbols and copy-pasted functions."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding


@dataclass
class Definition:
    scope: tuple[str, ...]
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass
class Block:
    path: str
    line: int
    end_line: int
    digest: str
    statements: int
    lines: int


def _decorator_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _is_overload(node: ast.AST) -> bool:
    return "overload" in _decorator_names(node)


def _is_property_accessor(node: ast.AST) -> bool:
    names = _decorator_names(node)
    return bool(names & {"property", "setter", "getter", "deleter"})


def _collect_definitions(tree: ast.Module) -> list[Definition]:
    definitions: list[Definition] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _is_overload(node):
                definitions.append(Definition(scope=scope, name=node.name, node=node))
            child_scope = (*scope, node.name)
            for child in node.body:
                visit(child, child_scope)
            return
        if isinstance(node, ast.If):
            branch = ast.unparse(node.test)[:80]
            for child in node.body:
                visit(child, (*scope, f"if:{branch}"))
            for child in node.orelse:
                visit(child, (*scope, f"else:{branch}"))
            return
        if isinstance(node, ast.Try):
            for child in node.body:
                visit(child, (*scope, "try"))
            for handler in node.handlers:
                label = ast.unparse(handler.type)[:40] if handler.type else "bare"
                for child in handler.body:
                    visit(child, (*scope, f"except:{label}"))
            for child in node.orelse:
                visit(child, (*scope, "else"))
            for child in node.finalbody:
                visit(child, (*scope, "finally"))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    for child in tree.body:
        visit(child, ("module",))
    return definitions


def duplicate_symbol_findings(
    tree: ast.Module, path: str, config: AntiSlopConfig
) -> list[Finding]:
    if not config.ban_duplicate_symbols:
        return []
    grouped: dict[tuple[tuple[str, ...], str], list[Definition]] = {}
    for definition in _collect_definitions(tree):
        grouped.setdefault((definition.scope, definition.name), []).append(definition)

    findings: list[Finding] = []
    for (_, name), definitions in grouped.items():
        if len(definitions) < 2:
            continue
        if any(_is_property_accessor(item.node) for item in definitions):
            continue
        first = definitions[0]
        for duplicate in definitions[1:]:
            finding = make_finding(
                "SLOP001",
                config,
                path,
                duplicate.node.lineno,
                duplicate.node.col_offset + 1,
                f"Duplicate definition `{name}` (first at line {first.node.lineno}).",
                "Merge or rename the duplicate; if intentional, add a "
                "waker suppression with a reason.",
                end_line=getattr(duplicate.node, "end_lineno", None),
                symbol=name,
            )
            if finding:
                findings.append(finding)
    return findings


def _is_trivial_body(body: list[ast.stmt]) -> bool:
    return all(
        isinstance(stmt, ast.Pass)
        or (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
        for stmt in body
    )


def collect_blocks(
    tree: ast.Module, path: str, config: AntiSlopConfig
) -> list[Block]:
    blocks: list[Block] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            span = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
            if (
                len(body) >= config.duplicate_block_min_statements
                and span >= config.duplicate_block_min_lines
                and not _is_trivial_body(body)
            ):
                normalized = "\n".join(
                    ast.dump(stmt, annotate_fields=False, include_attributes=False)
                    for stmt in body
                )
                digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                blocks.append(
                    Block(
                        path=path,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                        digest=digest,
                        statements=len(body),
                        lines=span,
                    )
                )
            for child in body:
                visit(child)
            return
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                visit(child)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for child in tree.body:
        visit(child)
    return blocks


def copy_paste_findings(blocks: list[Block], config: AntiSlopConfig) -> list[Finding]:
    grouped: dict[str, list[Block]] = {}
    for block in blocks:
        grouped.setdefault(block.digest, []).append(block)

    findings: list[Finding] = []
    for group in grouped.values():
        paths = {block.path for block in group}
        if len(paths) < 2:
            continue
        first = group[0]
        for duplicate in group[1:]:
            if duplicate.path == first.path:
                continue
            finding = make_finding(
                "SLOP006",
                config,
                duplicate.path,
                duplicate.line,
                1,
                f"Copy-pasted {duplicate.statements}-statement block "
                f"(also at {first.path}:{first.line}).",
                "Extract a shared helper or use a parameterized implementation.",
                end_line=duplicate.end_line,
                confidence="likely",
            )
            if finding:
                findings.append(finding)
    return findings
