# waker-ai

**Never let your AI coding agent sleep on the job again.**

`waker` is an independent watchdog & supervisor for AI coding agents. It watches
the disk (not the agent's words), verifies your contract, and wakes the agent up
until every task has evidence and every gate is green.

> Agent claims. Waker verifies. The disk decides.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | planner, contract lint, evidence, detector, engine loop, status/watch | ✅ done |
| 2 | OpenCode T1 live, cost guard, daemon + detach, skills, job object + live freeze probe | ✅ done |
| 3 | PTY tier-3 adapters, browser dashboard, verify scheduling, Claude live | ⏳ planned |

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
waker --version
```

## Quick start

```bash
# 1. turn a prompt into a mechanical contract (0 token)
waker plan --prompt "Phase 1: auth, scope: src/auth/**, verify: pytest tests/auth -q"

# 2. validate it (missing scope/verify/overlap = fail closed)
waker lint --tasks .waker/tasks.yaml

# 3. supervise an OpenCode agent, with cost + freeze guards
waker run --tasks .waker/tasks.yaml \
  --adapter opencode --model opencode-go/deepseek-v4.1-flash \
  --test "pytest tests/ -q" \
  --max-kicks 5 --max-cost 0.50
```

Run it in the background instead:

```bash
waker start --detach --tasks .waker/tasks.yaml \
  --adapter opencode --model <provider/model> --test "pytest tests/ -q"

waker status --repo .
waker watch --repo .
waker stop --repo .
```

Or expose the control plane to a chatbox skill:

```bash
waker serve --port 47821
curl http://127.0.0.1:47821/status?repo=.
```

Install the skill where your agent looks for it:

```bash
waker install-skill --for opencode   # .opencode/skills/waker/SKILL.md
waker install-skill --for claude     # .claude/skills/waker/SKILL.md
waker install-skill --for gemini     # .gemini/config/skills/waker/SKILL.md
waker install-skill --for generic    # AGENTS.md block (idempotent)
```

## How it decides "done"

For every task:

```python
done(T) = (git diff ∩ T.scope ≠ ∅) and (T.verify exits 0)
```

Nothing else counts. An agent saying "all tasks completed" is treated as a hint,
never as evidence.

| Gate | What it stops |
|---|---|
| `scope ∩ diff` | touching an unrelated file to look busy |
| `verify` exit 0 | claiming success while tests are red |
| test hash | editing the exam (`TAMPER` → restore + kick) |
| contract hash | moving the goalposts mid-run |
| cost + kick + wall-clock limits | burning the budget in a retry loop |

## Windows safety

- Runs are assigned to a **Win32 Job Object** with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; a fallback `taskkill /T /F` is always
  issued, so grandchildren die too.
- **Live freeze probe**: no stdout *and* no file activity for
  `--freeze-after` seconds → the tree is killed and the turn is marked
  `FROZEN` instead of waiting for the full timeout.

## OpenCode adapter notes (v2.0.32, verified)

- `opencode run --session <id> --auto --format json` emits JSONL events
  (`step_start`, `text`, `tool_use`, ...). **No cost in the stream.**
- Cost/tokens are read from `opencode session export <id>`
  (`info.cost`, `info.tokens`) before and after each turn; the delta is charged
  to that turn.
- Prompts are passed as an **argv element**, never through a shell: shell
  quoting corrupts prompts containing quotes/backslashes. On Windows the adapter
  resolves the real `opencode.exe` (or `WAKER_OPENCODE_BIN`).

## Repo layout

```
src/waker/
├── planner.py          # deterministic 4-bucket parser + contract lint
├── state.py            # run state, ledger, events, checkpoints
├── evidence.py         # diff/scope matching, test hash, tamper restore
├── detector.py         # pure Observation -> Diagnosis
├── engine.py           # spawn -> observe -> verify -> diagnose -> wake
├── process.py          # live streaming, freeze probe, tree kill
├── winjob.py           # Win32 Job Object wrapper
├── opencode_events.py  # JSON stream + session usage parsing
├── daemon.py           # detached runs + loopback HTTP control plane
├── skill_install.py    # install-skill for 4 providers
├── adapters/           # generic (T2), opencode (T1)
└── ui.py               # markdown + Rich live
tests/                  # 86 automated tests + gated live E2E
```

## Tests

```bash
pytest tests/                 # 86 passed, live test skipped by default
$env:WAKER_LIVE_TEST="1"      # real OpenCode E2E
pytest tests/test_live_opencode.py -q
```

Design details: [`plan.md`](plan.md).
