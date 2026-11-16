"""Dead symbol and unused-import rules."""

from __future__ import annotations

from ..config import AntiSlopConfig
from ..graph import ModuleGraph
from ..model import Finding
from ..symbols import ModuleSymbols
from .common import make_finding

_FRAMEWORK = {
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setup",
    "teardown",
    "__init__",
    "__enter__",
    "__exit__",
    "__call__",
    "__repr__",
    "__str__",
    "__iter__",
}


def _selected(path: str, only_paths: set[str] | None) -> bool:
    return only_paths is None or path in only_paths


def dead_code_findings(
    modules: dict[str, ModuleSymbols],
    config: AntiSlopConfig,
    entry_points: set[str] | None = None,
    graph: ModuleGraph | None = None,
    only_paths: set[str] | None = None,
) -> list[Finding]:
    entry_points = entry_points or set()
    references: set[str] = set()
    for module in modules.values():
        references |= module.references
        for imported in module.imports:
            if imported.star or imported.local not in module.references:
                continue
            if imported.full:
                references.add(imported.full.rsplit(".", 1)[-1])

    imported_by: dict[str, set[str]] = {}
    if graph is not None:
        for edge in graph.local_edges:
            target_path = graph.modules.get(edge.target)
            if target_path:
                imported_by.setdefault(target_path, set()).add(edge.source)

    findings: list[Finding] = []
    for module in modules.values():
        if not _selected(module.path, only_paths):
            continue
        if config.dead_unused_imports and not module.dynamic:
            for imported in module.imports:
                if imported.star or imported.full.startswith("__future__"):
                    continue
                if imported.local in {"*", "__all__"}:
                    continue
                if imported.local in module.references or imported.local in module.exports:
                    continue
                finding = make_finding(
                    "DEAD002",
                    config,
                    imported.path,
                    imported.line,
                    imported.col,
                    f"Import `{imported.local}` is not used.",
                    "Remove the import or use it in a real reference.",
                )
                if finding:
                    findings.append(finding)

        if module.dynamic:
            continue
        for symbol in module.definitions:
            if symbol.name in entry_points or symbol.name in _FRAMEWORK:
                continue
            if symbol.name.startswith("pytest_") or symbol.name.startswith("test_"):
                continue
            if symbol.name in module.exports or symbol.decorated:
                continue
            used = symbol.name in references
            if used:
                continue
            if symbol.private:
                finding = make_finding(
                    "DEAD001",
                    config,
                    symbol.path,
                    symbol.line,
                    symbol.col,
                    f"Private {symbol.kind} `{symbol.name}` has no reference.",
                    "Remove it or wire it into a real call path.",
                    confidence="certain",
                    symbol=symbol.name,
                )
                if finding:
                    findings.append(finding)
            else:
                level = config.dead_public_severity
                if level == "off":
                    continue
                finding = make_finding(
                    "DEAD003",
                    config,
                    symbol.path,
                    symbol.line,
                    symbol.col,
                    f"Public {symbol.kind} `{symbol.name}` has no reference.",
                    "Export it deliberately or remove the speculative API.",
                    confidence="likely",
                    symbol=symbol.name,
                    severity=level,
                )
                if finding:
                    findings.append(finding)

    if graph is not None and config.dead_public_severity != "off":
        for module in modules.values():
            if module.path.endswith("__init__.py") or module.path.endswith("__main__.py"):
                continue
            if module.dynamic or not _selected(module.path, only_paths):
                continue
            if imported_by.get(module.path):
                continue
            public = [
                symbol
                for symbol in module.definitions
                if not symbol.private and symbol.name not in module.exports
            ]
            if not public:
                continue
            first = public[0]
            finding = make_finding(
                "DEAD004",
                config,
                first.path,
                first.line,
                first.col,
                f"Module `{module.module}` is not imported anywhere and exposes public symbols.",
                "Remove it, make it an entry point, or document it as a plugin module.",
                confidence="likely",
                severity="warning",
            )
            if finding:
                findings.append(finding)
    return findings
