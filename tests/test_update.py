from __future__ import annotations

import io
import json
from pathlib import Path

from waker import update


def test_is_newer() -> None:
    assert update.is_newer("1.2.0", "1.1.3")
    assert update.is_newer("2.0.0", "1.9.9")
    assert not update.is_newer("1.1.3", "1.1.3")
    assert not update.is_newer("1.1.2", "1.1.3")
    assert not update.is_newer("not-a-version", "1.1.3")


def test_fresh_cache_returns_notice_without_fetch(tmp_path: Path) -> None:
    now = 1_700_000_000.0
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps({"checked_at": now, "latest": "1.2.0"}), encoding="utf-8"
    )
    calls: list[int] = []

    def fetcher() -> str:
        calls.append(1)
        return "9.9.9"

    notice = update.check_for_update(
        cache_path=cache, current="1.1.3", now=now, ttl=100, fetcher=fetcher
    )
    assert notice is not None
    assert "1.1.3" in notice
    assert "1.2.0" in notice
    assert calls == []


def test_fresh_cache_same_version_has_no_notice(tmp_path: Path) -> None:
    now = 1_700_000_000.0
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps({"checked_at": now, "latest": "1.1.3"}), encoding="utf-8"
    )
    notice = update.check_for_update(
        cache_path=cache, current="1.1.3", now=now, ttl=100
    )
    assert notice is None


def test_stale_cache_refreshes_and_returns_newer(tmp_path: Path) -> None:
    now = 1_700_000_000.0
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps({"checked_at": now - 1000, "latest": "1.2.0"}), encoding="utf-8"
    )

    def fetcher() -> str:
        return "1.3.0"

    notice = update.check_for_update(
        cache_path=cache,
        current="1.1.3",
        now=now,
        ttl=100,
        fetcher=fetcher,
        background=False,
    )
    assert notice is not None
    assert "1.3.0" in notice
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["latest"] == "1.3.0"


def test_fetch_failure_is_silent(tmp_path: Path) -> None:
    def fetcher() -> str:
        raise RuntimeError("offline")

    notice = update.check_for_update(
        cache_path=tmp_path / "missing.json",
        current="1.1.3",
        fetcher=fetcher,
        background=False,
    )
    assert notice is None


def test_print_notice_skips_non_tty() -> None:
    stream = io.StringIO()
    update.print_notice("hello", stream=stream)
    assert stream.getvalue() == ""


def test_format_notice() -> None:
    text = update.format_notice("1.1.3", "1.2.0")
    assert "1.1.3" in text
    assert "1.2.0" in text
    assert "pip install --upgrade waker-ai" in text


def test_print_notice_forced() -> None:
    stream = io.StringIO()
    update.print_notice(
        update.format_notice("1.1.3", "1.2.0"), stream=stream, force=True
    )
    assert "Update available" in stream.getvalue()


def test_print_notice_falls_back_to_ascii() -> None:
    class Cp1252(io.StringIO):
        def write(self, text: str) -> int:
            text.encode("cp1252")
            return super().write(text)

    stream = Cp1252()
    update.print_notice(
        update.format_notice("1.1.3", "1.2.0"), stream=stream, force=True
    )
    assert "Update available" in stream.getvalue()
    assert "->" in stream.getvalue()


def test_should_check_respects_env(monkeypatch) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setenv("WAKER_UPDATE_CHECK", "0")
    assert not update.should_check(Tty())
    monkeypatch.setenv("WAKER_UPDATE_CHECK", "1")
    assert update.should_check(Tty())
    monkeypatch.delenv("WAKER_UPDATE_CHECK")
    monkeypatch.setenv("CI", "1")
    assert not update.should_check(Tty())


def test_main_prints_notice(monkeypatch, tmp_path: Path) -> None:
    from waker import cli

    calls: list[str] = []
    monkeypatch.setattr(cli.update, "should_check", lambda: True)
    monkeypatch.setattr(cli.update, "check_for_update", lambda: "NOTICE")
    monkeypatch.setattr(cli.update, "print_notice", lambda notice: calls.append(notice))

    cli.main(["detect", "--repo", str(tmp_path)])

    assert calls == ["NOTICE"]
