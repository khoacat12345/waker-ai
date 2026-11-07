# waker-ai

**Never let your AI coding agent sleep on the job again.**

`waker` is an independent watchdog & supervisor for AI coding agents. It watches
the disk (not the agent's words), verifies your contract, and wakes the agent up
until every task has evidence and every gate is green.

> Agent claims. Waker verifies. The disk decides.

## Phase 1 (this repo state)

- `waker plan --prompt "..."` - deterministic 4-bucket parser (work /
  constraint / preference / unknown), **0 token**.
- `waker lint --tasks ...` - mechanical contract validation (scope, verify,
  duplicate ids, overlapping scopes, trivial commands).
- `waker run --tasks ... --agent ...` - the supervisor loop:
  observe -> verify -> diagnose -> checkpoint -> wake.
- `waker status` / `waker watch` - Markdown snapshot and live Rich TUI.
- `tests/fake_agent.py` - reproduces lazy / liar / tamper / freeze / blocked
  agents so the loop is proven without spending a token.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .[dev]

waker plan --prompt "Phase 1: auth, scope: src/auth/**, verify: pytest tests/auth -q"
waker lint --tasks .waker/tasks.yaml
```

Run the supervisor against any CLI agent:

```bash
waker run --tasks .waker/tasks.yaml \
  --test "pytest tests/ -q" \
  --agent "opencode run --session {session} --auto {prompt}" \
  --max-kicks 5
```

## Design

The full design lives in [`plan.md`](plan.md). The short version:

1. **No agent message is trusted.** Two signals only: `git diff` intersected with
   each task's `scope`, and the task's `verify` command exiting `0`.
2. **The contract is frozen before work starts** and hashed. Editing tests is
   `TAMPER`: waker restores them and kicks.
3. **Every wake is a real session resume**, not a new context.
4. **Every kick is checkpointed**, so a bad wake is revertible.
5. **The UI only renders `ledger.json`** - it never computes state.

## Status

Phase 1 is complete when `pytest tests/` exits `0`. Phase 2 will add the
OpenCode JSON event stream, the daemon (`waker serve`), PTY tier-3 adapters,
`doctor`, and notifications.
