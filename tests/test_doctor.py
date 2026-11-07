from __future__ import annotations

import pytest

from waker import doctor
from waker.adapters import pty as pty_adapter


def test_environment_reports_python_and_git():
    env = doctor.environment()
    assert env.python.startswith("3.")
    assert env.platform
    assert env.shell


def test_detect_tools_and_tiers(monkeypatch):
    monkeypatch.setattr(
        doctor, "_which", lambda name: f"C:/bin/{name}.exe" if name in {"opencode", "claude"} else None
    )
    monkeypatch.setattr(doctor, "_version", lambda name, path: f"{name} 9.9")

    tools = {tool.name: tool for tool in doctor.detect_tools()}
    assert tools["opencode"].found is True
    assert tools["opencode"].tier == "T1"
    assert tools["claude"].found is True
    assert tools["claude"].tier == "T1"
    assert tools["aider"].found is False
    assert tools["aider"].tier == "-"
    assert "any-text-cli" in tools


def test_render_text_contains_sections(monkeypatch):
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    monkeypatch.setattr(doctor, "_version", lambda name, path: "")
    text = doctor.render_text(doctor.environment(), doctor.detect_tools())
    assert "waker doctor" in text
    assert "adapters" in text
    assert "tier" in text


@pytest.mark.skipif(not pty_adapter.AVAILABLE, reason="PTY unavailable")
def test_injector_self_test_roundtrips_a_marker():
    ok, detail = doctor.injection_self_test(timeout=20)
    assert ok, detail
