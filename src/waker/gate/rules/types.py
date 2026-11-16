"""Type-evidence rules: Any/cast/type-ignore escape hatches."""

from __future__ import annotations

import ast
import re

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding

_TYPE_IGNORE_RE = re.compile(r"#\s*(?:type|pyright):\s*ignore\b(?P<rest>.*)", re.I)


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _is_cast(call: ast.Call) -> bool:
    return isinstance(call, ast.Call) and _call_name(call) == "cast"


def _atoms(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Subscript):
        return _atoms(node.value) | _atoms(node.slice)
    if isinstance(node, (ast.Tuple, ast.List)):
        result: set[str] = set()
        for item in node.elts:
            result |= _atoms(item)
        return result
    if isinstance(node, ast.BinOp):
        return _atoms(node.left) | _atoms(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    return set()


def _is_bad(node: ast.AST | None) -> bool:
    return bool(_atoms(node) & {"Any", "object", "Unknown"})


def _is_unsafe_dict(node: ast.AST | None) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    names = _atoms(node.value)
    if not (names & {"dict", "Dict", "Mapping", "MutableMapping"}):
        return False
    value = node.slice
    if isinstance(value, ast.Tuple) and len(value.elts) >= 2:
        return _is_bad(value.elts[1])
    return False


def _decorator_name(decorator: ast.AST) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return f"{_decorator_name(target.value)}.{target.attr}".strip(".")
    return ""


def _has_decorator(node: ast.AST, name: str) -> bool:
    return any(
        _decorator_name(item) == name or _decorator_name(item).endswith("." + name)
        for item in getattr(node, "decorator_list", [])
    )


def _safety_comment(source: str, line: int) -> bool:
    lines = source.splitlines()
    for number in range(max(1, line - 1), min(len(lines), line + 1) + 1):
        if "safety:" in lines[number - 1].lower():
            return True
    return False


def type_findings(
    tree: ast.Module,
    path: str,
    source: str,
    config: AntiSlopConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def add(finding: Finding | None) -> None:
        if finding is None:
            return
        key = (finding.rule, finding.line, finding.col)
        if key not in seen:
            seen.add(key)
            findings.append(finding)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if _has_decorator(node, "overload"):
            continue
        is_type_guard = bool(_atoms(node.returns) & {"TypeGuard", "TypeIs"})
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        for arg in args:
            if arg.arg in {"self", "cls"}:
                continue
            if config.ban_any_parameters and not is_type_guard and _is_bad(arg.annotation):
                add(
                    make_finding(
                        "TYPE001",
                        config,
                        path,
                        getattr(arg, "lineno", node.lineno),
                        getattr(arg, "col_offset", 0) + 1,
                        f"Parameter `{arg.arg}` uses an evidence-free type "
                        f"(`{ast.unparse(arg.annotation) if arg.annotation else '?'}`).",
                        "Name the domain type or parse at the I/O boundary.",
                        symbol=name,
                    )
                )
        for arg in (node.args.vararg, node.args.kwarg):
            if arg is not None and config.ban_any_parameters and not is_type_guard and _is_bad(arg.annotation):
                add(
                    make_finding(
                        "TYPE001",
                        config,
                        path,
                        getattr(arg, "lineno", node.lineno),
                        getattr(arg, "col_offset", 0) + 1,
                        f"Variadic parameter `{arg.arg}` uses `Any`/`object`.",
                        "Use a typed mapping or a named payload type.",
                        symbol=name,
                    )
                )
        if config.ban_any_returns and _is_bad(node.returns):
            add(
                make_finding(
                    "TYPE002",
                    config,
                    path,
                    node.lineno,
                    node.col_offset + 1,
                    f"Function `{name}` returns `Any`/`object`.",
                    "Return a named type; parse untrusted input at the boundary.",
                    end_line=getattr(node, "end_lineno", None),
                    symbol=name,
                )
            )

        widened: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        annotation = getattr(child, "annotation", None)
                        if _is_bad(annotation) or (
                            isinstance(child.value, ast.Call) and _is_cast(child.value)
                        ):
                            widened.add(target.id)

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            call_name = _call_name(child)
            if call_name == "cast":
                if config.ban_chained_casts and len(child.args) >= 2 and isinstance(child.args[1], ast.Call) and _is_cast(child.args[1]):
                    add(
                        make_finding(
                            "TYPE004",
                            config,
                            path,
                            child.lineno,
                            child.col_offset + 1,
                            "Chained `cast()` calls fabricate evidence.",
                            "Remove the intermediate cast and validate the real value once.",
                            symbol=name,
                        )
                    )
                if (
                    config.ban_widen_then_cast
                    and len(child.args) >= 2
                    and isinstance(child.args[1], ast.Name)
                    and child.args[1].id in widened
                ):
                    add(
                        make_finding(
                            "TYPE005",
                            config,
                            path,
                            child.lineno,
                            child.col_offset + 1,
                            f"Value `{child.args[1].id}` was widened and is now cast back.",
                            "Delete the widening step; keep the value's named type.",
                            symbol=name,
                        )
                    )
                if config.require_safety_comment and not _safety_comment(source, child.lineno):
                    add(
                        make_finding(
                            "TYPE007",
                            config,
                            path,
                            child.lineno,
                            child.col_offset + 1,
                            "`cast()` has no nearby safety/invariant comment.",
                            "Add `# SAFETY: <why this invariant holds>` or remove the cast.",
                            confidence="likely",
                            symbol=name,
                        )
                    )
            if config.ban_adhoc_isinstance and call_name in {"isinstance", "issubclass"}:
                returns = _atoms(node.returns)
                if not (returns & {"TypeGuard", "TypeIs"}):
                    add(
                        make_finding(
                            "TYPE006",
                            config,
                            path,
                            child.lineno,
                            child.col_offset + 1,
                            "Ad-hoc `isinstance` narrowing outside a type guard.",
                            "Use a TypeGuard/TypeIs helper or parse at the boundary.",
                            confidence="likely",
                            symbol=name,
                        )
                    )
            if call_name in {"getattr", "setattr", "delattr"} and len(child.args) >= 2:
                if config.ban_string_attribute_access and isinstance(child.args[1], ast.Constant) and isinstance(child.args[1].value, str):
                    add(
                        make_finding(
                            "TYPE009",
                            config,
                            path,
                            child.lineno,
                            child.col_offset + 1,
                            f"`{call_name}` uses a string attribute name.",
                            "Use typed attribute access or a parsed boundary schema.",
                            confidence="likely",
                            symbol=name,
                        )
                    )

        isinstance_calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and _call_name(child) in {"isinstance", "issubclass"}
        ]
        if (
            config.ban_adhoc_isinstance
            and len(isinstance_calls) >= config.max_isinstance_checks
            and not (_atoms(node.returns) & {"TypeGuard", "TypeIs"})
        ):
            first = isinstance_calls[0]
            add(
                make_finding(
                    "TYPE012",
                    config,
                    path,
                    first.lineno,
                    first.col_offset + 1,
                    f"Function `{name}` uses {len(isinstance_calls)} manual "
                    "isinstance checks as a type switch.",
                    "Model the variants with a protocol/union and one parser.",
                    confidence="likely",
                    symbol=name,
                )
            )

    type_alias_node = getattr(ast, "TypeAlias", None)
    for node in ast.walk(tree):
        if type_alias_node is not None and isinstance(node, type_alias_node):
            if config.ban_any_aliases and _is_bad(node.value):
                add(
                    make_finding(
                        "TYPE003",
                        config,
                        path,
                        node.lineno,
                        node.col_offset + 1,
                        "Type alias resolves to `Any`/`object`.",
                        "Name the actual domain type.",
                    )
                )
            continue
        if isinstance(node, ast.AnnAssign):
            annotation = node.annotation
            if config.ban_any_aliases and _atoms(annotation) & {"TypeAlias"} and _is_bad(node.value):
                add(
                    make_finding(
                        "TYPE003",
                        config,
                        path,
                        node.lineno,
                        node.col_offset + 1,
                        "Type alias resolves to `Any`/`object`.",
                        "Name the actual domain type.",
                    )
                )
            if config.unsafe_dict_values and _is_unsafe_dict(annotation):
                add(
                    make_finding(
                        "TYPE011",
                        config,
                        path,
                        node.lineno,
                        node.col_offset + 1,
                        "Dictionary value type is `Any`/`object`.",
                        "Use a typed value model instead of an open dictionary.",
                    )
                )
            if config.ban_known_value_widening and _is_bad(annotation) and isinstance(node.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set)):
                add(
                    make_finding(
                        "TYPE010",
                        config,
                        path,
                        node.lineno,
                        node.col_offset + 1,
                        "Known value is widened to `Any`/`object`.",
                        "Keep the literal's inferred type or name a domain type.",
                    )
                )

    for number, line in enumerate(source.splitlines(), 1):
        match = _TYPE_IGNORE_RE.search(line)
        if not match:
            continue
        rest = match.group("rest")
        has_code = bool(re.search(r"\[[^\]]+\]", rest))
        has_reason = "reason=" in rest.lower() or "#" in rest
        if not has_code and not has_reason:
            add(
                make_finding(
                    "TYPE008",
                    config,
                    path,
                    number,
                    1,
                    "`type: ignore` / `pyright: ignore` has no code or reason.",
                    "Add a specific code and a reason, or fix the underlying type.",
                )
            )

    return findings
