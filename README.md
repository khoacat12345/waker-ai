# waker-ai

[![tests](https://github.com/khoacat12345/waker-ai/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/khoacat12345/waker-ai/actions/workflows/ci.yml)

**Never let your AI coding agent sleep on the job again.**

`waker` is an independent supervisor for AI coding agents. It watches the disk
(not the agent's words), verifies a frozen contract, and wakes the agent up until
every task has on-disk evidence and every gate is green.

> Agent claims. Waker verifies. The disk decides.

```text
$ waker run --tasks .waker/tasks.yaml --adapter opencode --test "pytest -q"

**waker · run cff9c232 · 1/1 — 100%**
`████████████████`  ⏱ 00:45  🔁 0/5  🧪 PASS  💰 $0.0016

|   | Task | Work              | Evidence      | Gate |
|---|------|-------------------|---------------|------|
| ✅ | T1   | create live.txt   | src/live.txt  | pass |
```

## Why

AI agents do four things that ruin unattended runs:

1. **Stop early** — finish 1 of 5 tasks, exit 0, go quiet.
2. **Lie** — print "all tasks completed" while the test suite is red.
3. **Cheat** — edit the tests until they pass.
4. **Spin** — rewrite the same two lines five times with no progress.

Waker handles all four because it never trusts the agent's output. It only
trusts `git diff` and exit codes.

## Feature comparison

| Capability | Manual babysitting | `until` loop in bash | Agent built-in "auto" | **waker-ai** |
|---|:---:|:---:|:---:|:---:|
| Verifies work on disk (not claims) | ❌ | partial | ❌ | ✅ |
| Session resume across wakes | ❌ | ❌ | partial | ✅ T1 |
| Detects test tampering | ❌ | ❌ | ❌ | ✅ |
| Detects "claimed done, tests red" | ❌ | ❌ | ❌ | ✅ |
| Detects frozen / thrashing agents | ❌ | ❌ | ❌ | ✅ |
| Per-task checklist with evidence | ❌ | ❌ | partial | ✅ |
| Cost guard (USD) | ❌ | ❌ | ❌ | ✅ |
| Works with many CLIs | ❌ | ✅ | ❌ | ✅ T1/T2/T3 |
| Survives chatbox close (`--detach`) | ❌ | ✅ | ❌ | ✅ |
| Live TUI + web dashboard | ❌ | ❌ | ❌ | ✅ |
| Runs 100% offline for parsing/lint | ❌ | ✅ | ❌ | ✅ 0 token |

## Install

```bash
# PyPI publish is pending for v1.0 - install the release wheel:
pip install https://github.com/khoacat12345/waker-ai/releases/download/v0.3.1/waker_ai-0.3.1-py3-none-any.whl

# or from source:
# pip install "waker-ai @ git+https://github.com/khoacat12345/waker-ai.git"

# one command: detect installed CLIs and install the waker skill
waker setup

# Windows PTY tier-3 (optional)
pip install "pywinpty>=3.0" "pyte>=0.8"
```

From source:

```bash
git clone https://github.com/khoacat12345/waker-ai
cd waker-ai
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
pytest
```

## Quickstart (60 seconds)

```bash
# 1) turn a prompt into a mechanical contract - 0 token, deterministic
waker plan --prompt "Phase 1: auth, scope: src/auth/**, verify: pytest tests/auth -q"

# 2) validate the contract - fail closed on missing scope/verify
waker lint --tasks .waker/tasks.yaml

# 3) supervise the agent
waker run --tasks .waker/tasks.yaml \
  --adapter opencode --model opencode-go/deepseek-v4.1-flash \
  --test "pytest tests/ -q" \
  --max-kicks 5 --max-cost 0.50
```

Background mode, then watch from anywhere:

```bash
waker start --detach --tasks .waker/tasks.yaml \
  --adapter opencode --model <provider/model> --test "pytest tests/ -q"

waker status --repo .
waker watch --repo .
waker dashboard --repo . --open
waker stop --repo .
```

Install the chatbox skill:

```bash
waker setup                          # detects OpenCode/Claude/Gemini, installs globally
# or explicit:
waker install-skill --for opencode --global   # ~/.opencode/skills/waker/SKILL.md
waker install-skill --for claude --global     # ~/.claude/skills/waker/SKILL.md
waker install-skill --for gemini --global     # ~/.gemini/config/skills/waker/SKILL.md
waker install-skill --for generic             # AGENTS.md block (idempotent)
```

Skills are loaded when the chat session starts — restart your CLI after
installing. A `pip install` cannot write into your agent's config by itself
(that is a security boundary); `waker setup` is the one-time post-install step.

## How done is decided

For every task:

```python
done(T) = (git diff ∩ T.scope ≠ ∅) and (T.verify exits 0)
```

| Gate | Stops |
|---|---|
| `scope ∩ diff` | touching an unrelated file to look busy |
| `verify` exit 0 | claiming success while tests are red |
| test hash | editing the exam (`TAMPER` → restore + kick) |
| contract hash | moving the goalposts mid-run |
| cost / kicks / wall clock | burning the budget in a retry loop |

## Adapters

| Tier | Mechanism | CLIs |
|---|---|---|
| **T1** | native session resume | OpenCode (`run --session --format json`), Claude Code (`-p --resume --output-format stream-json`) |
| **T2** | fresh process + context digest | any CLI with a non-interactive flag (`aider --message`, `gemini -p`, custom commands) |
| **T3** | PTY keystroke injection (ConPTY + pyte) | any text-mode TUI, even without a headless mode |

`waker doctor` detects what is installed and prints the tier:

```text
$ waker doctor --inject-test
OK opencode      tier T1  (opencode 2.0.32)
OK claude        tier T1  (claude 1.x)
-- aider         tier -
OK any-text-cli  tier T3  (pywinpty)
injector self-test: PASS - marker seen
```

The injector self-test drives a harmless shell, never an AI session.

## Safety on Windows

- Every run is assigned to a **Win32 Job Object**
  (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`); `taskkill /T /F` is always issued as a
  fallback, so grandchildren die too.
- **Live freeze probe**: no stdout **and** no file activity for `--freeze-after`
  seconds → kill the tree and mark the turn `FROZEN`; no waiting for a
  15-minute timeout.
- Prompts are passed as argv, never through a shell (shell quoting corrupts
  prompts that contain quotes or backslashes).

## CLI

```text
waker plan        prompt -> contract (0 token)
waker lint        contract validation (0 token)
waker run         supervise in the foreground
waker start       supervise in the background (detached)
waker stop        stop a run (tree kill)
waker serve       loopback HTTP control plane
waker status      markdown/JSON snapshot
waker watch       live Rich TUI
waker dashboard   static HTML or live web dashboard
waker report      print the acceptance report
waker doctor      environment + adapter tier + injector test
waker setup       detect CLIs and install the skill (one command)
waker install-skill  opencode / claude / gemini / generic
```

## Demo

A 45-second recording script lives in [`docs/demo-45s.md`](docs/demo-45s.md).

## Design

Full design and decision log: [`plan.md`](plan.md).
Phase reports: `.waker/runs/phase1_report.md`, `phase2_report.md`, `phase3_report.md`.

## Status

v0.3.0 — Phase 3 complete. Launch (v1.0) pending:
PyPI publish, signed release, GitHub Actions matrix, and the 45s video.

## License

MIT
