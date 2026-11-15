"""Best-effort update notifier.

The check must never block a command or break it. A small on-disk cache is
read synchronously; a stale cache starts a daemon thread that refreshes the
cache for the next invocation. Only interactive terminals see the banner, and
CI / ``WAKER_UPDATE_CHECK=0`` disable it.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__

PYPI_URL = "https://pypi.org/pypi/waker-ai/json"
CACHE_TTL = 6 * 60 * 60
_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}


def cache_file() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "waker" / "update-check.json"


def enabled() -> bool:
    if "NO_UPDATE_NOTIFIER" in os.environ:
        return False
    value = os.environ.get("WAKER_UPDATE_CHECK", "").strip().lower()
    if value in _FALSE:
        return False
    if value in _TRUE:
        return True
    if os.environ.get("CI"):
        return False
    return True


def should_check(stream=None) -> bool:
    stream = stream or sys.stderr
    if not enabled():
        return False
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001 - exotic stream must never break the CLI
        return False


def _parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", value or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer(latest: str, current: str) -> bool:
    latest_tuple = _parse_version(latest)
    current_tuple = _parse_version(current)
    return bool(latest_tuple and current_tuple and latest_tuple > current_tuple)


def _read_cache(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return {
            "checked_at": float(payload.get("checked_at") or 0),
            "latest": str(payload.get("latest") or ""),
        }
    except Exception:  # noqa: BLE001 - a broken cache is just a cache miss
        return None


def _write_cache(path: Path, latest: str, now: float) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"checked_at": now, "latest": latest}), encoding="utf-8"
        )
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - cache writes are best-effort
        pass


def fetch_latest(timeout: float = 1.5) -> str | None:
    request = urllib.request.Request(
        PYPI_URL, headers={"User-Agent": f"waker/{__version__}"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    latest = payload.get("info", {}).get("version")
    return str(latest) if latest else None


def _refresh(path: Path, fetcher=fetch_latest) -> None:
    try:
        latest = fetcher()
    except Exception:  # noqa: BLE001 - offline is fine
        return
    if latest:
        _write_cache(path, latest, time.time())


def format_notice(current: str, latest: str) -> str:
    line1 = f"Update available: {current} \u2192 {latest}"
    line2 = "Run: pip install --upgrade waker-ai"
    width = max(len(line1), len(line2)) + 2
    top = "\u256d" + "\u2500" * (width + 2) + "\u256e"
    bottom = "\u2570" + "\u2500" * (width + 2) + "\u256f"
    row1 = "\u2502 " + line1.ljust(width) + " \u2502"
    row2 = "\u2502 " + line2.ljust(width) + " \u2502"
    return "\n".join([top, row1, row2, bottom])


def check_for_update(
    *,
    cache_path: str | Path | None = None,
    current: str | None = None,
    now: float | None = None,
    ttl: float = CACHE_TTL,
    fetcher=fetch_latest,
    background: bool = True,
) -> str | None:
    current = current or __version__
    path = Path(cache_path) if cache_path else cache_file()
    now = time.time() if now is None else now
    cached = _read_cache(path)
    notice = None
    if cached and is_newer(cached["latest"], current):
        notice = format_notice(current, cached["latest"])
    if cached and now - cached["checked_at"] < ttl:
        return notice
    if background:
        threading.Thread(target=_refresh, args=(path, fetcher), daemon=True).start()
        return notice
    _refresh(path, fetcher)
    cached = _read_cache(path)
    if cached and is_newer(cached["latest"], current):
        return format_notice(current, cached["latest"])
    return None


def print_notice(notice: str, stream=None, force: bool = False) -> None:
    stream = stream or sys.stderr
    if not notice:
        return
    if not force:
        try:
            if not stream.isatty():
                return
        except Exception:  # noqa: BLE001
            return
    color = "" if "NO_COLOR" in os.environ else "\033[93m"
    reset = "" if not color else "\033[0m"
    try:
        stream.write(f"{color}{notice}{reset}\n")
    except UnicodeEncodeError:
        ascii_notice = (
            notice.replace("\u256d", "+")
            .replace("\u256e", "+")
            .replace("\u2570", "+")
            .replace("\u256f", "+")
            .replace("\u2500", "-")
            .replace("\u2502", "|")
            .replace("\u2192", "->")
        )
        stream.write(f"{ascii_notice}\n")
    try:
        stream.flush()
    except Exception:  # noqa: BLE001
        pass
