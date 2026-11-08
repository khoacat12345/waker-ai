"""Skill installation for OpenCode / Claude Code / Gemini CLI / generic AGENTS.md."""

from __future__ import annotations

import shutil
from pathlib import Path

TARGETS = {
    "opencode": Path(".opencode/skills/waker/SKILL.md"),
    "claude": Path(".claude/skills/waker/SKILL.md"),
    "gemini": Path(".gemini/config/skills/waker/SKILL.md"),
}
PROVIDERS = ("opencode", "claude", "gemini", "generic")
BEGIN = "<!-- waker:begin -->"
END = "<!-- waker:end -->"


def template_path(provider: str) -> Path:
    base = Path(__file__).resolve().parent / "skill_templates" / provider
    return base / ("AGENTS.md" if provider == "generic" else "SKILL.md")


def install_skill(provider: str, root: str | Path = ".", global_: bool = False) -> Path:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    base = Path.home() if global_ else Path(root)
    template = template_path(provider)
    if not template.exists():
        raise FileNotFoundError(f"missing template: {template}")

    if provider == "generic":
        target = base / "AGENTS.md"
        block = template.read_text(encoding="utf-8").strip()
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if BEGIN in existing and END in existing:
            before, _, rest = existing.partition(BEGIN)
            _, _, after = rest.partition(END)
            existing = before.rstrip() + "\n\n" + after.lstrip()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            (existing.rstrip() + "\n\n" if existing.strip() else "")
            + f"{BEGIN}\n{block}\n{END}\n",
            encoding="utf-8",
        )
        return target

    target = base / TARGETS[provider]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, target)
    if provider == "opencode" and global_:
        # Also mirror to ~/.config/opencode/skills/waker/SKILL.md (XDG compliant for Linux/macOS)
        xdg_target = base / ".config" / "opencode" / "skills" / "waker" / "SKILL.md"
        xdg_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, xdg_target)
    return target
