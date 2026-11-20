# waker-ai v2.2.0 — Chatbox Grill-Me, timeout profiles, phase display

**Release date:** 2026-11-20
**Status:** package built and validated; publish pending approval.
**Baseline:** v2.0.0
**Design:** [`plan.md` §27](../plan.md#27-approved--grill-me--timeout-profiles)

## Highlights

### Conditional Grill-Me

The `waker` skill now has a conditional contract check before `waker plan`:

- Clear prompt with goal + scope + verify + required inputs → **silent-pass,
  0 questions**.
- Missing blocking information → at most **3 questions, one round**.
- No preference/naming/style interrogation.
- “Tùy bạn” for a preference is recorded as a preference; it never authorizes
  invented `scope` or `verify`.
- Ambiguity after the question round stops planning and asks the user to split
  the task.

This is intentionally instruction-only for v2.2.0. Code-enforced
`waker grill` / `questions.yaml` is deferred to v2.3.0.

### Chatbox phase flow

```bash
waker plan --prompt "..." --phases none
waker plan --prompt "..." --phases manual
waker plan --prompt "..." --phases auto --profile large --json
```

- `none`: one implicit `P1` for small tasks.
- `manual`: preserve the user's phase assignments.
- `auto`: rule-based proposal from task phase/scope, with phase budgets from
  the selected profile.
- Large tasks print a review table and wait for `ok` / `1` / `chạy`.
- Natural-language edits such as “tăng P2 lên 3h, P1 còn 30m” are written back
  to `tasks.yaml`, re-linted and confirmed before start.
- Small clear `/waker` tasks use the fast path.
- Chatbox/non-TTY mode never reads raw terminal keys.

### Timeout profiles

| Profile | Turn | Run | Verify | Freeze | Kicks |
|---|---:|---:|---:|---:|---:|
| `small` | 5m | 20m | 2m | 3m | 3 |
| `medium` | 15m | 90m | 5m | 5m | 5 |
| `large` | 30m | 5h | 15m | 10m | 8 |
| `overnight` | 45m | 8h | 30m | 15m | 12 |

`medium` preserves the historical defaults. Use `--profile large` or
`--profile overnight` for long projects; explicit timeout flags still override
the profile.

Wall-clock or turn exhaustion now terminates with `TIMEOUT` (exit code 7)
instead of the generic `BREAKER`. Kick/cost exhaustion remains `BREAKER`, and
freeze detection remains `FROZEN`.

### Timeout telemetry

`run.json`, events and `waker status --format json` expose:

```json
{
  "profile": "large",
  "timeouts": {
    "turn_timeout": 1800,
    "max_wall_clock": 18000,
    "verify_timeout": 900,
    "freeze_after": 600
  }
}
```

Per-kick events also record verify-timeout task IDs and full-suite timeout
state, so a slow test is not silently reported as a code failure.

### Phase display

The Cyber-Deck shows the current phase from the run state:

```text
PHASE 2/2  Docs  01:12:10 / 02:00:00  [######----]
```

- Green below 80% of phase budget.
- Yellow from 80%.
- Red from 95%.
- No phase row when the contract has no phase metadata; values are never
  synthesized.

## Fixed

- **Completed-run Cyber-Deck visibility:** a run in `DONE`, `FAILED`,
  `BLOCKED`, `TIMEOUT` or another terminal state is rendered once with
  `Console.print` in the normal terminal buffer. `Live(screen=True)` is used
  only for a genuinely running run. When a live run ends, the final frame is
  rendered again so it is not erased with the alternate screen.
- **`--window` lifecycle:** the child command receives `--hold`, uses
  `cmd start /wait`, and the `watch.window` marker is JSON:
  `{"pid": 12345, "started": 1760000000.0}`. A dead or legacy marker is removed
  immediately; a live launcher prevents duplicate windows. The window stays
  open until Enter, then can be reopened.

## Backward compatibility

- Existing contracts without `phases` load unchanged and receive implicit
  `P1`.
- Existing runs without phase fields load with safe defaults.
- Existing timeout flags remain valid; `medium` is the default profile.

## Verification

- Full pytest suite: **336 collected, 335 passed, 1 skipped**; zero failures.
  The skip is the real-OpenCode E2E test guarded by `WAKER_LIVE_TEST=1`.
- `python -m build`: built `waker_ai-2.2.0.tar.gz` and
  `waker_ai-2.2.0-py3-none-any.whl`.
- `twine check dist/waker_ai-2.2.0*`: both artifacts **PASSED**.
- `waker.__version__` reports `2.2.0`.
- No production code outside the E1–E6 scope is changed by E7.

## Install / upgrade

```bash
pip install --upgrade waker-ai==2.2.0
waker --version
```

Do not publish this release until the product owner gives explicit approval.
