from __future__ import annotations

import sys
from pathlib import Path

import pytest

from waker.adapters.base import TurnContext
from waker.adapters.pty import AVAILABLE, PtyAdapter

FAKE_TUI = Path(__file__).parent / "fake_tui.py"

pytestmark = pytest.mark.skipif(
    not AVAILABLE, reason="PTY tier-3 needs Windows + pywinpty + pyte"
)


def test_pty_drives_a_text_cli_and_keeps_context(repo: Path):
    adapter = PtyAdapter(
        [sys.executable, str(FAKE_TUI)],
        idle_seconds=0.5,
        auto_approve=False,
    )
    ctx = TurnContext(
        repo=str(repo),
        run_id="pty",
        session_id="ses_pty",
        kick=0,
        timeout=20,
        use_freeze_probe=False,
    )
    try:
        first = adapter.run_turn("hello", ctx)
        assert "ECHO:hello" in first.output
        assert "PROMPT>" in first.output

        second = adapter.run_turn("second", ctx)
        assert "ECHO:second" in second.output
    finally:
        adapter.close()


def test_pty_close_is_idempotent(repo: Path):
    adapter = PtyAdapter([sys.executable, str(FAKE_TUI)], idle_seconds=0.4)
    adapter.close()
    adapter.close()
