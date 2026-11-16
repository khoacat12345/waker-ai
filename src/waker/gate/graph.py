"""Module import graph and architecture rules."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .. import globs
from .config import AntiSlopConfig
from .model import Finding
from .rules.common import make_finding


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    path: str
    line: int
    col: int
    type_only: bool = False
    dynamic: bool = False


@dataclass
class ModuleGraph:
    modules: dict[str, str] = field(default_factory=dict)  # module -> path
    edges: list[ImportEdge] = field(default_factory=list)
    dynamic_warnings: list[tuple[str, int, int, str]] = field(default_factory=list)

    @property
    def local_edges(self) -> list[ImportEdge]:
        return [edge for edge in self.edges if edge.target in self.modules]

    def edges_by_source(self) -> dict[str, list[ImportEdge]]:
        result: dict[str, list[ImportEdge]] = {}
        for edge in self.local_edges:
            result.setdefault(edge.source, []).append(edge)
        return result


def module_name(path: str) -> str:
    value = globs.normalize(path)
    if value.startswith("src/"):
        value = value[4:]
    if value.endswith(".py"):
        value = value[:-3]
    parts = [part for part in value.split("/") if part]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(
    current: str,
    module: str | None,
    level: int,
    *,
    is_package: bool = False,
) -> str | None:
    if level <= 0:
        return module or ""
    parts = current.split(".") if current else []
    package = parts if is_package else parts[:-1]
    if level > len(package) + 1:
        return None
    base = package[: max(0, len(package) - level + 1)] if level > 1 else package
    if module:
        base = [*base, *module.split(".")]
    return ".".join(part for part in base if part)


def _target_candidates(base: str, name: str, modules: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    if base and name and name != "*":
        candidates.append(f"{base}.{name}")
    if base:
        candidates.append(base)
    for candidate in candidates:
        if candidate in modules:
            return [candidate]
    return candidates[:1] if candidates else []


def _is_type_checking(test: ast.AST) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def build_graph(repo: str | Path, files: list[Path], config: AntiSlopConfig) -> ModuleGraph:
    root = Path(repo).resolve()
    graph = ModuleGraph()
    for path in files:
        relative = globs.normalize(str(path.resolve().relative_to(root)))
        graph.modules[module_name(relative)] = relative

    def visit(
        node: ast.AST,
        source: str,
        path: str,
        type_only: bool = False,
        is_package: bool = False,
    ) -> None:
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.body:
                visit(child, source, path, True, is_package)
            for child in node.orelse:
                visit(child, source, path, True, is_package)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                if target in graph.modules:
                    graph.edges.append(
                        ImportEdge(source, target, path, node.lineno, node.col_offset + 1, type_only)
                    )
                else:
                    top = target.split(".")[0]
                    if top in graph.modules:
                        graph.edges.append(
                            ImportEdge(source, top, path, node.lineno, node.col_offset + 1, type_only)
                        )
            return
        if isinstance(node, ast.ImportFrom):
            base = _resolve_relative(
                source, node.module, node.level, is_package=is_package
            )
            if base is not None:
                for alias in node.names:
                    candidates = _target_candidates(base, alias.name, graph.modules)
                    target = candidates[0] if candidates else base
                    if target in graph.modules:
                        graph.edges.append(
                            ImportEdge(source, target, path, node.lineno, node.col_offset + 1, type_only)
                        )
            return
        if isinstance(node, ast.Call):
            target = node.func
            fname = target.id if isinstance(target, ast.Name) else (
                target.attr if isinstance(target, ast.Attribute) else ""
            )
            if fname in {"__import__", "import_module"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    target_name = arg.value
                    if target_name in graph.modules:
                        graph.edges.append(
                            ImportEdge(
                                source, target_name, path, node.lineno,
                                node.col_offset + 1, type_only, dynamic=True,
                            )
                        )
                else:
                    graph.dynamic_warnings.append(
                        (path, node.lineno, node.col_offset + 1, ast.unparse(arg)[:80])
                    )
        for child in ast.iter_child_nodes(node):
            visit(child, source, path, type_only, is_package)

    for module, relative in graph.modules.items():
        path = root / relative
        try:
            source = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(source, filename=relative)
        except (OSError, SyntaxError):
            continue
        is_package = relative.endswith("/__init__.py")
        for child in tree.body:
            visit(child, module, relative, False, is_package)
    return graph


def tarjan_scc(nodes: list[str], adjacency: dict[str, list[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency.get(node, []):
            if target not in indices:
                strongconnect(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.discard(item)
                component.append(item)
                if item == node:
                    break
            components.append(component)

    for node in nodes:
        if node not in indices:
            strongconnect(node)
    return components


def _layer_for(path: str, config: AntiSlopConfig) -> str | None:
    for layer, patterns in config.layers.items():
        if globs.matches_any(path, patterns):
            return layer
    return None


def architecture_findings(
    graph: ModuleGraph,
    config: AntiSlopConfig,
    only_paths: set[str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []

    def selected(path: str) -> bool:
        return only_paths is None or path in only_paths

    adjacency: dict[str, list[str]] = {}
    for edge in graph.local_edges:
        if edge.type_only and config.type_checking == "ignore":
            continue
        adjacency.setdefault(edge.source, []).append(edge.target)

    if config.layers:
        for edge in graph.local_edges:
            if not selected(edge.path):
                continue
            source_layer = _layer_for(edge.path, config)
            target_path = graph.modules.get(edge.target)
            target_layer = _layer_for(target_path, config) if target_path else None
            if not source_layer or not target_layer or source_layer == target_layer:
                continue
            allowed = set(config.allow_imports.get(source_layer, ()))
            if target_layer not in allowed:
                finding = make_finding(
                    "ARCH001",
                    config,
                    edge.path,
                    edge.line,
                    edge.col,
                    f"Layer inversion: `{source_layer}` imports `{target_layer}` "
                    f"via `{edge.target}`.",
                    f"Move the dependency behind a {source_layer} interface or "
                    "route it through an allowed layer.",
                )
                if finding:
                    findings.append(finding)

    if config.detect_cycles and adjacency:
        components = tarjan_scc(sorted(adjacency), adjacency)
        edge_by_pair = {(edge.source, edge.target): edge for edge in graph.local_edges}
        for component in components:
            members = set(component)
            if len(component) < 2 and not any(
                edge.source == edge.target for edge in graph.local_edges if edge.source in members
            ):
                continue
            cycle_edges = [
                edge
                for edge in graph.local_edges
                if edge.source in members and edge.target in members
            ]
            if not any(selected(edge.path) for edge in cycle_edges):
                continue
            first = cycle_edges[0]
            cycle = " -> ".join([*component, component[0]])
            finding = make_finding(
                "ARCH002",
                config,
                first.path,
                first.line,
                first.col,
                f"Import cycle: {cycle}.",
                "Break the cycle with a protocol, an event, or a lower-level module.",
            )
            if finding:
                findings.append(finding)

    by_source = graph.edges_by_source()
    for source, edges in by_source.items():
        targets = {edge.target for edge in edges}
        if len(targets) <= config.max_fan_out:
            continue
        first = edges[0]
        if not selected(first.path):
            continue
        finding = make_finding(
            "ARCH003",
            config,
            first.path,
            first.line,
            first.col,
            f"Module imports {len(targets)} local modules (fan-out limit "
            f"{config.max_fan_out}).",
            "Introduce a focused adapter/collaborator instead of importing the world.",
            confidence="likely",
        )
        if finding:
            findings.append(finding)

    for path, line, col, expression in graph.dynamic_warnings:
        if not selected(path):
            continue
        finding = make_finding(
            "ARCH004",
            config,
            path,
            line,
            col,
            f"Dynamic import target is not statically resolvable: `{expression}`.",
            "Use a constant module name or an explicit registry.",
            confidence="likely",
        )
        if finding:
            findings.append(finding)
    return findings
