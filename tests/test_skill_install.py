from __future__ import annotations

from pathlib import Path

from waker.skill_install import BEGIN, PROVIDERS, install_skill


def test_install_skill_for_each_provider(tmp_path: Path):
    expected = {
        "opencode": tmp_path / ".opencode" / "skills" / "waker" / "SKILL.md",
        "claude": tmp_path / ".claude" / "skills" / "waker" / "SKILL.md",
        "gemini": tmp_path / ".gemini" / "config" / "skills" / "waker" / "SKILL.md",
        "generic": tmp_path / "AGENTS.md",
    }
    for provider in PROVIDERS:
        target = install_skill(provider, tmp_path)
        assert target == expected[provider]
        assert target.exists()
        assert "waker" in target.read_text(encoding="utf-8").lower()


def test_generic_install_is_idempotent(tmp_path: Path):
    install_skill("generic", tmp_path)
    install_skill("generic", tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count(BEGIN) == 1


def test_generic_install_preserves_existing_agents_md(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    target.write_text("# My rules\n\nbe nice\n", encoding="utf-8")
    install_skill("generic", tmp_path)
    text = target.read_text(encoding="utf-8")
    assert "# My rules" in text
    assert "be nice" in text
    assert BEGIN in text


def test_unknown_provider_raises(tmp_path: Path):
    try:
        install_skill("vim", tmp_path)
    except ValueError as exc:
        assert "unknown provider" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("should have raised")
