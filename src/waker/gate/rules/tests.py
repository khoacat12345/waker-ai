"""Test-integrity rules: fake green tests and mock abuse."""

from __future__ import annotations

import ast
from pathlib import Path

from ..config import AntiSlopConfig
from ..model import Finding
from .common import make_finding

_ASSERT_ATTRS = {"raises", "warns", "deprecated_call"}


def _walk(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield child
        yield from _walk(child)


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _is_assertion(node: ast.AST) -> bool:
    if isinstance(node, ast.Assert):
        return True
    if not isinstance(node, ast.Call):
        return False
    name = _call_name(node)
    if name in _ASSERT_ATTRS:
        return True
    if name.startswith("assert"):
        return True
    return False


def _assertions(node: ast.AST) -> list[ast.AST]:
    return [child for child in _walk(node) if _is_assertion(child)]


def _is_trivial_assert(node: ast.Assert) -> bool:
    test = node.test
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.Tuple):
        return bool(test.elts)
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and ast.dump(test.left, include_attributes=False)
        == ast.dump(test.comparators[0], include_attributes=False)
    ):
        return True
    return False


def _decorator_name(decorator: ast.AST) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return f"{_decorator_name(target.value)}.{target.attr}".strip(".")
    return ""


def _has_decorator(node: ast.AST, *names: str) -> bool:
    for decorator in getattr(node, "decorator_list", []):
        rendered = _decorator_name(decorator)
        if any(rendered == name or rendered.endswith("." + name) for name in names):
            return True
    return False


def _is_skip(node: ast.AST) -> bool:
    if _has_decorator(node, "skip", "xfail", "skipIf", "skipUnless"):
        return True
    for child in _walk(node):
        if isinstance(child, ast.Call) and _call_name(child) in {"skip", "xfail", "skipTest"}:
            return True
    return False


def _call_arg(call: ast.Call, index: int = 0) -> ast.AST | None:
    if len(call.args) > index:
        return call.args[index]
    for keyword in call.keywords:
        if keyword.arg == "condition":
            return keyword.value
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _patch_targets(node: ast.AST) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = []
    for child in _walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = _call_name(child)
        if name in {"patch", "setattr"}:
            target = _literal_string(_call_arg(child))
            if target:
                targets.append((target, child.lineno))
    return targets


def _test_tokens(path: str, function: str) -> set[str]:
    stem = Path(path).stem
    if stem.startswith("test_"):
        stem = stem[5:]
    if stem.endswith("_test"):
        stem = stem[:-5]
    tokens = {part for part in stem.split("_") if part}
    if function.startswith("test_"):
        function = function[5:]
    tokens.update(part for part in function.split("_") if part)
    return {token for token in tokens if len(token) > 2}


def _target_tokens(target: str) -> set[str]:
    return {part for part in target.replace(":", ".").split(".") if part}


def _call_last(call: ast.Call) -> str:
    return _call_name(call)


def _mock_ratio(node: ast.AST, path: str, config: AntiSlopConfig) -> list[Finding]:
    calls = [child for child in _walk(node) if isinstance(child, ast.Call)]
    if len(calls) < 3:
        return []
    mock_calls = 0
    for call in calls:
        name = _call_name(call)
        if name in {"Mock", "MagicMock", "patch", "setattr", "return_value", "assert_called", "assert_called_once"}:
            mock_calls += 1
        elif name.startswith("assert_"):
            mock_calls += 1
    ratio = mock_calls / len(calls)
    if ratio <= config.max_mock_ratio:
        return []
    finding = make_finding(
        "TEST006",
        config,
        path,
        getattr(node, "lineno", 1),
        1,
        f"Mock-related calls are {round(ratio * 100)}% of this test "
        f"(limit {round(config.max_mock_ratio * 100)}%).",
        "Mock external boundaries; exercise the real unit under test.",
        confidence="likely",
    )
    return [finding] if finding else []


def test_findings(
    tree: ast.Module,
    path: str,
    source: str,
    config: AntiSlopConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    test_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    for node in test_functions:
        if not _assertions(node):
            if not _is_skip(node):
                finding = make_finding(
                    "TEST001",
                    config,
                    path,
                    node.lineno,
                    node.col_offset + 1,
                    f"Test `{node.name}` has no assertion.",
                    "Assert the observable behavior, or use pytest.raises for an error contract.",
                    end_line=getattr(node, "end_lineno", None),
                    symbol=node.name,
                )
                if finding:
                    findings.append(finding)

        for child in _walk(node):
            if isinstance(child, ast.Assert) and _is_trivial_assert(child):
                finding = make_finding(
                    "TEST002",
                    config,
                    path,
                    child.lineno,
                    child.col_offset + 1,
                    "Always-true / tautological assertion.",
                    "Assert the result against an independent expected value.",
                    symbol=node.name,
                )
                if finding:
                    findings.append(finding)

        if _is_skip(node):
            finding = make_finding(
                "TEST005",
                config,
                path,
                node.lineno,
                node.col_offset + 1,
                f"Test `{node.name}` is unconditionally skipped or xfailed.",
                "Remove the skip/xfail or make it conditional with a tracked reason.",
                end_line=getattr(node, "end_lineno", None),
                symbol=node.name,
            )
            if finding:
                findings.append(finding)

        tokens = _test_tokens(path, node.name)
        for target, line in _patch_targets(node):
            target_parts = _target_tokens(target)
            if tokens & target_parts and not any(
                _call_last(call) in target_parts
                for call in _walk(node)
                if isinstance(call, ast.Call)
            ):
                finding = make_finding(
                    "TEST003",
                    config,
                    path,
                    line,
                    1,
                    f"Test patches the apparent system under test `{target}`.",
                    "Patch an external boundary; let the real unit run.",
                    confidence="likely",
                    symbol=node.name,
                )
                if finding:
                    findings.append(finding)

        for child in _walk(node):
            if isinstance(child, ast.Assert) and isinstance(child.test, ast.Attribute):
                if child.test.attr.startswith("assert_"):
                    finding = make_finding(
                        "TEST003",
                        config,
                        path,
                        child.lineno,
                        child.col_offset + 1,
                        "Mock assertion is referenced without calling it "
                        f"(`{child.test.attr}` needs `()`).",
                        "Call the assertion method; a bare reference is always truthy.",
                        symbol=node.name,
                    )
                    if finding:
                        findings.append(finding)

        findings.extend(_mock_ratio(node, path, config))

        # Mock tautology: configure return_value, then assert that same mock's
        # configured value without exercising the real unit.
        configured: set[str] = set()
        for child in _walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == "return_value":
                        base = target.value
                        if isinstance(base, ast.Name):
                            configured.add(base.id)
        for child in _walk(node):
            if not isinstance(child, ast.Assert):
                continue
            test = child.test
            if not isinstance(test, ast.Compare):
                continue
            sides = [test.left, *test.comparators]
            for side in sides:
                if isinstance(side, ast.Call) and isinstance(side.func, ast.Name) and side.func.id in configured:
                    finding = make_finding(
                        "TEST003",
                        config,
                        path,
                        child.lineno,
                        child.col_offset + 1,
                        "Mock tautology: the test asserts the value it configured on a mock.",
                        "Call the real unit and assert its observable result.",
                        confidence="likely",
                        symbol=node.name,
                    )
                    if finding:
                        findings.append(finding)
                    break
                if isinstance(side, ast.Attribute) and side.attr == "return_value" and isinstance(side.value, ast.Name) and side.value.id in configured:
                    finding = make_finding(
                        "TEST003",
                        config,
                        path,
                        child.lineno,
                        child.col_offset + 1,
                        "Mock tautology: the test asserts the value it configured on a mock.",
                        "Call the real unit and assert its observable result.",
                        confidence="likely",
                        symbol=node.name,
                    )
                    if finding:
                        findings.append(finding)
                    break

        for child in _walk(node):
            if isinstance(child, ast.Call) and _call_name(child) == "raises":
                first = _call_arg(child)
                if isinstance(first, (ast.Name, ast.Attribute)):
                    name = first.id if isinstance(first, ast.Name) else first.attr
                    if name in {"Exception", "BaseException"}:
                        finding = make_finding(
                            "TEST007",
                            config,
                            path,
                            child.lineno,
                            child.col_offset + 1,
                            f"`pytest.raises({name})` is too broad.",
                            "Raise/assert a specific exception type and a message match.",
                            confidence="likely",
                            symbol=node.name,
                        )
                        if finding:
                            findings.append(finding)

    # Swallowed / unreachable assertions.
    def visit(node: ast.AST, swallowed: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node not in test_functions:
            return
        if isinstance(node, ast.Try):
            bad = any(
                isinstance(stmt, (ast.Pass, ast.Continue, ast.Break))
                or (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is Ellipsis
                )
                for handler in node.handlers
                for stmt in handler.body
            )
            for stmt in node.body:
                visit(stmt, swallowed or bad)
            for handler in node.handlers:
                for stmt in handler.body:
                    visit(stmt, swallowed)
            return
        if isinstance(node, ast.Assert) and swallowed:
            finding = make_finding(
                "TEST004",
                config,
                path,
                node.lineno,
                node.col_offset + 1,
                "Assertion is swallowed by an exception handler.",
                "Remove the assertion from the try block or re-raise the failure.",
            )
            if finding:
                findings.append(finding)
        for child in ast.iter_child_nodes(node):
            visit(child, swallowed)

    for node in test_functions:
        visit(node)

    stem = Path(path).stem
    target = stem[5:] if stem.startswith("test_") else ""
    if target and test_functions:
        imported: set[str] = set()
        for child in ast.walk(tree):
            if isinstance(child, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                imported.update(alias.name for alias in child.names)
                if child.module:
                    imported.add(child.module.split(".")[0])
        called = {
            _call_name(child)
            for child in ast.walk(tree)
            if isinstance(child, ast.Call)
        }
        target_tokens = {part for part in target.split("_") if len(part) > 2}
        if target_tokens and not (target_tokens & {item.lower() for item in imported}) and not (
            target_tokens & {item.lower() for item in called}
        ):
            finding = make_finding(
                "TEST008",
                config,
                path,
                1,
                1,
                f"Test file `{Path(path).name}` does not appear to import or call `{target}`.",
                "Import the unit under test; avoid testing a local fake.",
                confidence="likely",
            )
            if finding:
                findings.append(finding)

    return findings
