"""Dependency and package allowlist rules."""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import packages_distributions
from pathlib import Path

from ... import globs, winproc
from ..config import AntiSlopConfig
from ..model import Finding
from ..symbols import ModuleSymbols
from .common import make_finding

_DEP_RE = re.compile(r"^\s*(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(?P<spec>.*?)\s*$")


def _norm(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).strip().lower()


@dataclass
class Dependency:
    name: str
    spec: str
    path: str
    line: int
    raw: str


def _parse_requirement(line: str) -> tuple[str, str] | None:
    value = line.split("#", 1)[0].strip()
    if not value or value.startswith(("-", "git+", "http://", "https://")):
        return None
    match = _DEP_RE.match(value)
    if not match:
        return None
    name = match.group("name")
    if name.lower() in {"python", "pip", "setuptools", "wheel"}:
        return None
    return name, match.group("spec")


def _requirements(path: Path, relative: str) -> list[Dependency]:
    result: list[Dependency] = []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return result
    for number, line in enumerate(lines, 1):
        parsed = _parse_requirement(line)
        if parsed:
            result.append(Dependency(parsed[0], parsed[1], relative, number, line.strip()))
    return result


def _pyproject(path: Path, relative: str) -> list[Dependency]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    result: list[Dependency] = []
    project = data.get("project") or {}
    entries: list[tuple[str, int]] = []
    for value in project.get("dependencies") or []:
        entries.append((str(value), 1))
    for group in (project.get("optional-dependencies") or {}).values():
        for value in group or []:
            entries.append((str(value), 1))
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name, value in (poetry.get("dependencies") or {}).items():
        if str(name).lower() == "python":
            continue
        if isinstance(value, str):
            entries.append((f"{name}{value}" if value and value[0] in "<>=!~" else f"{name}=={value}", 1))
        elif isinstance(value, dict) and value.get("version"):
            entries.append((f"{name}=={value['version']}", 1))
        else:
            entries.append((str(name), 1))
    for raw, line in entries:
        parsed = _parse_requirement(raw)
        if parsed:
            result.append(Dependency(parsed[0], parsed[1], relative, line, raw))
    return result


def _manifest_files(repo: Path, config: AntiSlopConfig) -> list[Path]:
    files: list[Path] = []
    for pattern in config.manifest_paths:
        if any(char in pattern for char in "*?["):
            files.extend(repo.rglob(pattern))
        else:
            path = repo / pattern
            if path.exists():
                files.append(path)
    return sorted({path.resolve() for path in files if path.is_file()})


def _dependencies(repo: Path, config: AntiSlopConfig) -> list[Dependency]:
    result: list[Dependency] = []
    for path in _manifest_files(repo, config):
        relative = globs.normalize(str(path.resolve().relative_to(repo.resolve())))
        if path.name == "pyproject.toml":
            result.extend(_pyproject(path, relative))
        elif path.name.startswith("requirements") and path.suffix == ".txt":
            result.extend(_requirements(path, relative))
    return result


def _baseline_dependencies(repo: Path, relative: str, ref: str) -> list[Dependency]:
    result = winproc.run(
        ["git", "-C", str(repo), "show", f"{ref}:{relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    source = result.stdout.decode("utf-8-sig", errors="replace")
    if relative.endswith("pyproject.toml"):
        try:
            data = tomllib.loads(source)
        except tomllib.TOMLDecodeError:
            return []
        result: list[Dependency] = []
        for value in (data.get("project") or {}).get("dependencies") or []:
            parsed = _parse_requirement(str(value))
            if parsed:
                result.append(Dependency(parsed[0], parsed[1], relative, 1, str(value)))
        return result
    return [
        Dependency(parsed[0], parsed[1], relative, 1, line)
        for line in source.splitlines()
        for parsed in [_parse_requirement(line)]
        if parsed
    ]


def package_findings(
    repo: str | Path,
    modules: dict[str, ModuleSymbols],
    config: AntiSlopConfig,
    baseline_ref: str = "HEAD",
    only_paths: set[str] | None = None,
) -> list[Finding]:
    root = Path(repo).resolve()
    findings: list[Finding] = []
    current = _dependencies(root, config)
    declared = {_norm(dep.name) for dep in current}
    approved = {_norm(item) for item in config.dependency_allow}
    allowed = approved | declared
    stdlib = {name.lower() for name in sys.stdlib_module_names}
    first_party = {module.split(".")[0].lower() for module in modules}
    mapping = {
        key.lower(): {_norm(item) for item in values}
        for key, values in packages_distributions().items()
    }

    for module in modules.values():
        if only_paths is not None and module.path not in only_paths:
            continue
        if config.is_test_path(module.path):
            continue
        for imported in module.imports:
            if imported.star or imported.full.startswith("__future__") or imported.local.startswith("."):
                continue
            top = imported.full.split(".")[0]
            if top.lower() in stdlib or top.lower() in first_party:
                continue
            distributions = mapping.get(top.lower(), set())
            if not distributions:
                if _norm(top) in approved:
                    continue
                finding = make_finding(
                    "PKG004",
                    config,
                    imported.path,
                    imported.line,
                    imported.col,
                    f"Cannot map import `{top}` to an installed distribution.",
                    "Declare the dependency or correct the import name.",
                    confidence="likely",
                )
                if finding:
                    findings.append(finding)
                continue
            if not (distributions & allowed):
                finding = make_finding(
                    "PKG001",
                    config,
                    imported.path,
                    imported.line,
                    imported.col,
                    f"Import `{top}` ({', '.join(sorted(distributions))}) is outside the allowlist.",
                    "Add the distribution to dependency_allow only after approval.",
                )
                if finding:
                    findings.append(finding)

    if config.check_manifests:
        baseline_names: set[str] = set()
        for manifest in _manifest_files(root, config):
            relative = globs.normalize(str(manifest.resolve().relative_to(root)))
            for dep in _baseline_dependencies(root, relative, baseline_ref):
                baseline_names.add(_norm(dep.name))
        for dep in current:
            name = _norm(dep.name)
            pinned = "==" in dep.spec
            if not pinned:
                finding = make_finding(
                    "PKG003",
                    config,
                    dep.path,
                    dep.line,
                    1,
                    f"Dependency `{dep.name}` is not pinned.",
                    "Pin an exact version (or use a lock file) before shipping.",
                    confidence="likely",
                )
                if finding:
                    findings.append(finding)
            if (
                baseline_ref
                and name not in baseline_names
                and name not in approved
                and not config.allow_new_dependencies
            ):
                finding = make_finding(
                    "PKG002",
                    config,
                    dep.path,
                    dep.line,
                    1,
                    f"New dependency `{dep.name}` is not approved.",
                    "Add it to dependency_allow or revert the manifest change.",
                )
                if finding:
                    findings.append(finding)
    return findings
