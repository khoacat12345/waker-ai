"""Symbol tables for dead-code analysis."""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .config import AntiSlopConfig
from ..globs import normalize


@dataclass
class Symbol:
    name: str
    path: str
    line: int
    col: int
    kind: str  # function | class
    private: bool
    decorated: bool


@dataclass
class ImportRecord:
    local: str
    full: str
    path: str
    line: int
    col: int
    star: bool = False
    relative: bool = False


@dataclass
class ModuleSymbols:
    module: str
    path: str
    definitions: list[Symbol] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    references: set[str] = field(default_factory=set)
    exports: set[str] = field(default_factory=set)
    dynamic: bool = False


def _string_refs(node: ast.AST) -> set[str]:
    refs: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id in {"getattr", "setattr", "delattr"} and len(child.args) >= 2:
                if isinstance(child.args[1], ast.Constant) and isinstance(child.args[1].value, str):
                    refs.add(child.args[1].value)
    return refs


def module_name(path: str) -> str:
    value = normalize(path)
    if value.startswith("src/"):
        value = value[4:]
    if value.endswith(".py"):
        value = value[:-3]
    parts = [part for part in value.split("/") if part]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def parse_entry_points(repo: str | Path) -> set[str]:
    path = Path(repo) / "pyproject.toml"
    if not path.exists():
        return set()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    names: set[str] = set()
    project = data.get("project") or {}
    for section in ("scripts", "gui-scripts"):
        for value in (project.get(section) or {}).values():
            if isinstance(value, str):
                names.add(value.split(":")[-1].split(".")[-1])
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for value in (poetry.get("scripts") or {}).values():
        if isinstance(value, str):
            names.add(value.split(":")[-1].split(".")[-1])
    return names


def analyze_module(tree: ast.Module, path: str, config: AntiSlopConfig) -> ModuleSymbols:
    symbols = ModuleSymbols(module=module_name(path), path=path)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            private = name.startswith("_") and not name.startswith("__")
            symbols.definitions.append(
                Symbol(
                    name=name,
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    kind="class" if isinstance(node, ast.ClassDef) else "function",
                    private=private,
                    decorated=bool(getattr(node, "decorator_list", [])),
                )
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                symbols.imports.append(
                    ImportRecord(
                        local=local,
                        full=alias.name,
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    symbols.imports.append(
                        ImportRecord(
                            local="*",
                            full=(node.module or ""),
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            star=True,
                            relative=node.level > 0,
                        )
                    )
                    continue
                local = alias.asname or alias.name
                full = f"{node.module}.{alias.name}" if node.module else alias.name
                symbols.imports.append(
                    ImportRecord(
                        local=local,
                        full=full,
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        relative=node.level > 0,
                    )
                )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    value = node.value
                    if isinstance(value, (ast.List, ast.Tuple)):
                        for item in value.elts:
                            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                                symbols.exports.add(item.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            symbols.references.add(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            symbols.references.add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"globals", "vars", "locals"}:
                symbols.dynamic = True
    symbols.references |= _string_refs(tree)
    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__"
        for node in tree.body
    ):
        symbols.dynamic = True
    return symbols


def analyze_files(
    repo: str | Path,
    files: list[Path],
    config: AntiSlopConfig,
) -> dict[str, ModuleSymbols]:
    root = Path(repo).resolve()
    modules: dict[str, ModuleSymbols] = {}
    for path in files:
        relative = normalize(str(path.resolve().relative_to(root)))
        try:
            source = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(source, filename=relative)
        except (OSError, SyntaxError):
            continue
        module = analyze_module(tree, relative, config)
        modules[module.path] = module
    return modules


__all__ = [
    "ImportRecord",
    "ModuleSymbols",
    "Symbol",
    "analyze_files",
    "analyze_module",
    "module_name",
    "parse_entry_points",
]
