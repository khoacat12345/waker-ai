"""Complexity, function/module length, and nesting guards."""

from __future__ import annotations

import ast
import io
import tokenize

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding

_SKIP_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}


def _code_lines(source: str) -> set[int]:
    lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in _SKIP_TOKENS:
                lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError):
        for number, line in enumerate(source.splitlines(), 1):
            if line.strip() and not line.lstrip().startswith("#"):
                lines.add(number)
    return lines


def _count_lines(lines: set[int], start: int, end: int) -> int:
    return sum(1 for line in lines if start <= line <= end)


def _complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    total = 1
    match_case = getattr(ast, "match_case", None)

    def walk(current: ast.AST) -> None:
        nonlocal total
        if current is not node and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(current, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
            total += 1
        elif match_case is not None and isinstance(current, match_case):
            total += 1
        elif isinstance(current, ast.IfExp):
            total += 1
        elif isinstance(current, ast.BoolOp):
            total += max(0, len(current.values) - 1)
        elif isinstance(current, ast.comprehension):
            total += 1 + len(current.ifs)
        for child in ast.iter_child_nodes(current):
            walk(child)

    for child in node.body:
        walk(child)
    return total


def _nesting(node: ast.AST, depth: int = 0) -> int:
    maximum = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(
            child,
            (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith),
        ) or (hasattr(ast, "Match") and isinstance(child, ast.Match)):
            maximum = max(maximum, _nesting(child, depth + 1))
        else:
            maximum = max(maximum, _nesting(child, depth))
    return maximum


def _parameter_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    count = len(positional) + len(args.kwonlyargs)
    if positional and positional[0].arg in {"self", "cls"}:
        count -= 1
    if args.vararg:
        count += 1
    if args.kwarg:
        count += 1
    return count


def complexity_findings(
    tree: ast.Module, path: str, source: str, config: AntiSlopConfig
) -> list[Finding]:
    lines = _code_lines(source)
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        complexity = _complexity(node)
        if complexity > config.max_cyclomatic_complexity:
            finding = make_finding(
                "SLOP003",
                config,
                path,
                node.lineno,
                node.col_offset + 1,
                f"Function `{name}` has cyclomatic complexity {complexity} "
                f"(limit {config.max_cyclomatic_complexity}).",
                "Split branches into named helpers or use a data-driven mapping.",
                end_line=getattr(node, "end_lineno", None),
                symbol=name,
            )
            if finding:
                findings.append(finding)

        if node.body:
            start = node.body[0].lineno
            end = getattr(node, "end_lineno", start) or start
            length = _count_lines(lines, start, end)
            if length > config.max_function_lines:
                finding = make_finding(
                    "SLOP004",
                    config,
                    path,
                    node.lineno,
                    node.col_offset + 1,
                    f"Function `{name}` is {length} logical lines "
                    f"(limit {config.max_function_lines}).",
                    "Extract cohesive steps into named helpers.",
                    end_line=end,
                    symbol=name,
                )
                if finding:
                    findings.append(finding)

        depth = _nesting(node)
        params = _parameter_count(node)
        if depth > config.max_nesting_depth:
            finding = make_finding(
                "SLOP008",
                config,
                path,
                node.lineno,
                node.col_offset + 1,
                f"Function `{name}` nests {depth} levels "
                f"(limit {config.max_nesting_depth}).",
                "Use early returns/guard clauses and extract nested blocks.",
                end_line=getattr(node, "end_lineno", None),
                confidence="likely",
                symbol=name,
            )
            if finding:
                findings.append(finding)
        if params > config.max_parameters:
            finding = make_finding(
                "SLOP008",
                config,
                path,
                node.lineno,
                node.col_offset + 1,
                f"Function `{name}` has {params} parameters "
                f"(limit {config.max_parameters}).",
                "Group related values into a dataclass/typed object.",
                end_line=getattr(node, "end_lineno", None),
                confidence="likely",
                symbol=name,
            )
            if finding:
                findings.append(finding)

    module_lines = len(lines)
    if module_lines > config.max_module_lines:
        finding = make_finding(
            "SLOP005",
            config,
            path,
            1,
            1,
            f"Module has {module_lines} logical lines "
            f"(limit {config.max_module_lines}).",
            "Split the module by responsibility.",
            end_line=len(source.splitlines()) or 1,
        )
        if finding:
            findings.append(finding)
    return findings
