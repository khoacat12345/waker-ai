"""OpenCode JSON stream + session usage parsing.

Verified against OpenCode v2.0.32:

* ``opencode run --format json`` emits JSONL with ``type`` / ``sessionID`` /
  ``part`` (``step_start``, ``text``, tool events...). It does **not** emit cost.
* ``opencode session export <id>`` returns ``{"info": {"cost": float,
  "tokens": {"input": .., "output": .., ...}}, "messages": [...]}``.

So cost/token accounting reads the export before and after each turn.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Usage:
    cost_usd: float = 0.0
    tokens: int = 0
    ok: bool = False


def resolve_opencode_binary(binary: str = "opencode") -> str:
    """Resolve the real executable.

    On Windows the npm shim (``opencode.cmd``) cannot be launched without a
    shell, and shell quoting mangles prompts that contain quotes/backslashes.
    Prefer ``opencode.exe`` so the adapter can pass an argv list safely.
    """
    env_bin = os.environ.get("WAKER_OPENCODE_BIN")
    if env_bin:
        return env_bin
    if binary and binary != "opencode":
        return binary

    found = shutil.which("opencode.exe")
    if found:
        return found
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = (
                Path(appdata)
                / "npm"
                / "node_modules"
                / "@opencode"
                / "cli"
                / "bin"
                / "opencode.exe"
            )
            if candidate.exists():
                return str(candidate)
    found = shutil.which("opencode")
    return found or binary


def parse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "type" in event:
            events.append(event)
    return events


def event_session(events: list[dict]) -> str | None:
    for event in reversed(events):
        value = event.get("sessionID") or (event.get("part") or {}).get("sessionID")
        if value:
            return str(value)
    return None


def event_text(events: list[dict]) -> str:
    parts: list[str] = []
    for event in events:
        part = event.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            parts.append(str(part["text"]))
    return "\n".join(parts)


def usage_from_export(payload: dict) -> Usage:
    info = payload.get("info") or {}
    try:
        cost = float(info.get("cost") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    tokens = info.get("tokens") or {}
    total = 0
    for key in ("input", "output", "reasoning"):
        try:
            total += int(tokens.get(key) or 0)
        except (TypeError, ValueError):
            continue
    cache = tokens.get("cache") or {}
    for key in ("read", "write"):
        try:
            total += int(cache.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return Usage(cost_usd=cost, tokens=total, ok=True)


def read_session_usage(
    session_id: str, cwd: str, binary: str = "opencode", timeout: float = 60.0
) -> Usage:
    executable = resolve_opencode_binary(binary)
    try:
        result = subprocess.run(
            [executable, "session", "export", session_id],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Usage()
    if result.returncode != 0:
        return Usage()
    text = (result.stdout or "").strip()
    start = text.find("{")
    if start < 0:
        return Usage()
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError:
        return Usage()
    if not isinstance(payload, dict):
        return Usage()
    return usage_from_export(payload)
