# waker-ai v0.3.1 — the skill is now one command away

Patch release focused on onboarding. v0.3.0 shipped the skill **template** inside
the wheel, but installing the package never wrote it into your agent's config —
so `waker` was invisible until you discovered `install-skill` yourself.

## New: `waker setup`

```bash
pip install waker-ai
waker setup
```

`setup` detects the CLIs installed on your machine and installs the skill where
each one looks for it:

| CLI | Destination |
|---|---|
| OpenCode | `~/.opencode/skills/waker/SKILL.md` (or `.opencode/...` with `--local`) |
| Claude Code | `~/.claude/skills/waker/SKILL.md` |
| Gemini CLI | `~/.gemini/config/skills/waker/SKILL.md` |
| Generic | `AGENTS.md` block (idempotent) |

Flags:

```bash
waker setup --dry-run          # show what would be installed
waker setup --local            # install into the current repo, not the home dir
waker setup --for opencode     # force a provider (repeatable)
```

Restart the chat session after installing — skills are loaded at startup.

## Why not automatic on `pip install`?

A Python package cannot write into your agent's config directory during install:
that would be an unbounded, silent modification outside the package's own
environment (and pip explicitly discourages install-time side effects).
`waker setup` is the explicit, auditable one-time step.

## Also fixed

- `waker setup` only auto-installs for CLIs actually found on `PATH`; if none are
  found it falls back to existing config directories, so wrappers still work.
- Documented the restart requirement and the security boundary in the README.

## Install

PyPI publish is pending for v1.0. Until then, use the attached wheel or install
from source:

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v0.3.1/waker_ai-0.3.1-py3-none-any.whl
waker setup
```

From source:

```bash
pip install "waker-ai @ git+https://github.com/khoacat12345/waker-ai.git"
waker setup
```

## Verification

```
110 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Checksums

```
SHA256  fc2d42ecf4783c2ae6cc1a9e8f91d9eda4389265ec14ef1001711615d16babc9
FILE    waker_ai-0.3.1-py3-none-any.whl (65,068 bytes)
```

## License

MIT
