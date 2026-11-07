# waker-ai v0.3.0 — *Ship while you sleep*

> **Agent claims. Waker verifies. The disk decides.**

`waker-ai` is an independent supervisor for AI coding agents. It watches the
disk — not the agent's words — and keeps waking the agent until every task has
on-disk evidence and every gate is green.

---

## Highlights

### 1. Three adapter tiers — one supervisor for any CLI

| Tier | Mechanism | Works with |
|---|---|---|
| **T1 — native resume** | `opencode run --session <id> --format json`, `claude -p --resume <id> --output-format stream-json` | OpenCode, Claude Code |
| **T2 — context replay** | fresh process + a context digest rebuilt from the ledger | Aider, Gemini CLI, any `--message` / `-p` CLI |
| **T3 — PTY keystroke** | ConPTY (`pywinpty`) + screen buffer (`pyte`), prompt detection, send keys + Enter | any text-mode TUI, even without a headless mode |

`waker doctor` detects what is installed, prints the tier, and runs a safe
injector self-test (a harmless shell, **0 tokens**, never your AI session).

### 2. A watchdog that does not believe the agent

Success is mechanical, never rhetorical:

```python
done(T) = (git diff ∩ T.scope ≠ ∅) and (T.verify exits 0)
```

It catches the four classic failure modes:

- **Premature exit** → `PARTIAL`, wake with the exact missing task.
- **Hallucinated completion** → `FALSE_DONE`, wake with real test output.
- **Test tampering** → `TAMPER`, restore the exam, then wake.
- **Freeze / thrash** → `FROZEN` / `THRASH`, kill or change strategy.

Plus a **cost guard** (`--max-cost`), kick limit, wall-clock limit, and
per-kick git checkpoints, so a bad wake is always revertible.

### 3. Two interfaces, one source of truth

- **Terminal**: `waker status` (Markdown snapshot) and `waker watch`
  (Rich live board with evidence per task).
- **Web**: `waker dashboard` — static HTML or a live loopback page.
- **Chatbox**: `waker install-skill --for opencode|claude|gemini|generic`;
  `waker start --detach` keeps running after you close the chat.

---

## Install

```bash
pip install waker-ai
# optional Windows PTY tier-3
pip install "waker-ai[pty]"
```

Or from the attached wheel:

```bash
pip install waker_ai-0.3.0-py3-none-any.whl
```

## Quick start

```bash
# 1) prompt -> mechanical contract (0 token, deterministic)
waker plan --prompt "Phase 1: auth, scope: src/auth/**, verify: pytest tests/auth -q"

# 2) validate it (missing scope/verify/overlap => fail closed)
waker lint --tasks .waker/tasks.yaml

# 3) supervise an agent
waker run --tasks .waker/tasks.yaml \
  --adapter opencode --model opencode-go/deepseek-v4.1-flash \
  --test "pytest tests/ -q" --max-kicks 5 --max-cost 0.50
```

Background + live board:

```bash
waker start --detach --tasks .waker/tasks.yaml --adapter opencode --model <model>
waker watch
waker dashboard --open
waker stop
```

---

## What's new in v0.3.0

- **Claude Code adapter (T1)** with `--permission-mode`, stream-json parsing,
  cost/token accounting and automatic session discovery.
- **PTY tier-3 adapter** for Windows (ConPTY + pyte): prompt detection,
  auto-approve, idle detection, process-tree kill.
- **`waker doctor`**: environment + CLI tier detection + safe injector test.
- **Verify scheduling**: only tasks whose scope changed are re-verified;
  the full suite runs only when the run is a DONE candidate, when the agent
  *claims* done, or every N kicks.
- **Web dashboard** (`waker dashboard`): static HTML report or live loopback.
- **Windows safety**: Win32 Job Object + `taskkill /T /F` fallback, live freeze
  probe that kills a silent tree instead of waiting for the turn timeout.
- **Cost guard**: USD limit per run, driven by `opencode session export`.
- **Packaging**: PEP 639 metadata, clean wheel, skill templates included,
  `pip install` verified in a fresh venv.
- **Docs**: English README with a feature-comparison table and a
  45-second demo script (`docs/demo-45s.md`).

### Test status

```
108 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

The skipped test is the real-OpenCode E2E, gated behind `WAKER_LIVE_TEST=1`.

---

## Known limitations

- PTY tier-3 is **Windows-only** in v0.3.0 (POSIX PTY is planned).
- Claude Code support is unit-tested; no live CI run yet (the CLI is not
  installed on the build machine).
- The dashboard uses a 2-second meta-refresh, not WebSocket streaming.
- The daemon and dashboard bind to `127.0.0.1` and have no auth.
- `--permission-mode bypassPermissions` is required for fully unattended
  Claude runs; use it only in a sandboxed repo.

---

## Checksums

```
SHA256  2f313b3aae85fbf9d756616fc76d89afeb593f942a6a4a5165637d82d04caf78
FILE    waker_ai-0.3.0-py3-none-any.whl (64,246 bytes)
```

## License

MIT — see [LICENSE](https://github.com/khoacat12345/waker-ai/blob/main/LICENSE).

---

**waker-ai** · never let your AI coding agent sleep on the job again.
