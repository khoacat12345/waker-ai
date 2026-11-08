"""Environment inspection and adapter capability detection for ``waker doctor``."""

from __future__ import annotations

from . import winproc

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from .adapters import pty as pty_adapter
from .adapters.base import TurnContext

TOOLS = {
    "opencode": ("T1", "run --session <id> --format json (verified v2.0.32)"),
    "claude": ("T1", "-p --resume <id> --output-format stream-json"),
    "aider": ("T2", "--message non-interactive; no session id to resume"),
    "codex": ("T2", "exec mode; resume support depends on version"),
    "gemini": ("T2", "-p non-interactive"),
}


@dataclass
class ToolReport:
    name: str
    found: bool
    path: str | None
    version: str
    tier: str
    reason: str


@dataclass
class EnvReport:
    python: str
    platform: str
    git: str
    pty_available: bool
    pty_detail: str
    shell: str


def _version(name: str, path: str) -> str:
    command = f'"{path}" --version' if " " in path else f"{path} --version"
    try:
        result = winproc.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    text = (result.stdout or "") + (result.stderr or "")
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:120]


def _which(name: str) -> str | None:
    for candidate in (name, f"{name}.exe", f"{name}.cmd", f"{name}.ps1"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def detect_tools() -> list[ToolReport]:
    reports: list[ToolReport] = []
    for name, (tier, reason) in TOOLS.items():
        path = _which(name)
        reports.append(
            ToolReport(
                name=name,
                found=bool(path),
                path=path,
                version=_version(name, path) if path else "",
                tier=tier if path else "-",
                reason=reason,
            )
        )
    reports.append(
        ToolReport(
            name="any-text-cli",
            found=pty_adapter.AVAILABLE,
            path=None,
            version="pywinpty" if pty_adapter.AVAILABLE else "",
            tier="T3" if pty_adapter.AVAILABLE else "-",
            reason=(
                "PTY keystroke injection (ConPTY + pyte)"
                if pty_adapter.AVAILABLE
                else pty_adapter.IMPORT_ERROR
            ),
        )
    )
    return reports


def environment() -> EnvReport:
    git_path = _which("git")
    git_version = _version("git", git_path) if git_path else "not found"
    return EnvReport(
        python=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()}",
        git=git_version,
        pty_available=pty_adapter.AVAILABLE,
        pty_detail=(
            "pywinpty + pyte ready (ConPTY)"
            if pty_adapter.AVAILABLE
            else pty_adapter.IMPORT_ERROR
        ),
        shell=os.environ.get("COMSPEC", "/bin/sh") if os.name == "nt" else os.environ.get("SHELL", "/bin/sh"),
    )


def injection_self_test(timeout: float = 15.0) -> tuple[bool, str]:
    """Drive a harmless shell in the PTY and check the marker comes back.

    This never touches an AI session and costs nothing: it proves the injector
    (spawn -> screen parse -> keystroke -> screen parse) works on this machine.
    """
    if not pty_adapter.AVAILABLE:
        return False, pty_adapter.IMPORT_ERROR
    shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else "/bin/sh"
    prompt = re.compile(r"[>\u276f$#]\s*$")
    adapter = pty_adapter.PtyAdapter(
        [shell],
        idle_seconds=0.4,
        prompt_pattern=prompt.pattern,
        auto_approve=False,
    )
    try:
        ctx = TurnContext(repo=os.getcwd(), run_id="doctor", session_id="doctor", kick=0, timeout=timeout)
        result = adapter.run_turn("echo WAKER_INJECT_OK", ctx)
        ok = "WAKER_INJECT_OK" in result.output
        return ok, "marker seen" if ok else "marker not seen on screen"
    except Exception as exc:  # noqa: BLE001 - doctor must never crash
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        adapter.close()


def render_text(env: EnvReport, tools: list[ToolReport], inject: tuple[bool, str] | None = None) -> str:
    lines = [
        "waker doctor",
        "=" * 60,
        f"python   : {env.python}",
        f"platform : {env.platform}",
        f"git      : {env.git}",
        f"pty      : {'OK' if env.pty_available else 'NO'} - {env.pty_detail}",
        f"shell    : {env.shell}",
        "",
        "adapters",
        "-" * 60,
    ]
    for tool in tools:
        mark = "OK " if tool.found else "-- "
        version = f" ({tool.version})" if tool.version else ""
        lines.append(f"{mark}{tool.name:<14} tier {tool.tier:<3}{version}")
        lines.append(f"    {tool.reason}")
    if inject is not None:
        ok, detail = inject
        lines.append("")
        lines.append(f"injector self-test: {'PASS' if ok else 'FAIL'} - {detail}")
    return "\n".join(lines)


def report(as_json: bool = False, inject_test: bool = False) -> int:
    env = environment()
    tools = detect_tools()
    inject = injection_self_test() if inject_test else None
    if as_json:
        print(
            json.dumps(
                {
                    "environment": asdict(env),
                    "tools": [asdict(tool) for tool in tools],
                    "injector": (
                        None
                        if inject is None
                        else {"ok": inject[0], "detail": inject[1]}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_text(env, tools, inject))
    if inject is not None and not inject[0]:
        return 1
    return 0
