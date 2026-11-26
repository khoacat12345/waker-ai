# Waker v2.3.0 — Bug Report: Phase Completion & Chatbox Reporting

**Date:** 2026-11-27
**Status:** DIAGNOSIS ONLY — no production code changed yet.
**Scope:** `main` after v2.3.0, Cyber-Deck, phase-budget runtime, chatbox skill.
**Symptom reported:** a phase is complete on disk, but Waker/chatbox still says
the run is running; a run was observed for 3 hours and appeared unfinished.

## Executive summary

The engine is not necessarily stuck. The main bug is that **Waker keeps only
the current phase status and never reports a historical `phase_completed`
event**. The chatbox therefore sees "run is running" and has no way to say
"P1 completed, now working on P2".

There is also a release/install bug: the **packaged skill template and the
globally installed `@waker` skill are older than the repo skill**, so the
chatbox does not know the new live-UI commands.

## Evidence

### E1. Phase status is overwritten

Diagnostic run with two phases:

```text
P1 One  (task T1)
P2 Two  (task T2)
```

After the run finished:

```text
phase_id       = P2
phase_status   = completed
phase_elapsed  = {"P1": 5.16, "P2": 3.16}
```

Only `P2` is exposed by `phase_snapshot`; there is no retained `P1 completed`
status. The UI/report cannot show that P1 finished.

### E2. No phase lifecycle events

The same run's relevant events contained only:

```text
diagnose
diagnose
```

There was no `phase_started` or `phase_completed` event. `phase_timeout` and
`budget_warning` exist from E8, but normal completion is silent.

### E3. Status/report expose only the active phase

`waker status --format json` and `waker report` show one `phase` object.
There is no all-phase list, no completed timestamp, and no phase history.

### E4. Skill install is stale

The three skill sources differ:

| File | Role | State |
|---|---|---|
| `.opencode/skills/waker/SKILL.md` | repo source | updated |
| `C:\Users\tuank\.opencode\skills\waker\SKILL.md` | chatbox-loaded copy | **old / no Cyber-Deck** |
| `src/waker/skill_templates/opencode/SKILL.md` | what `waker setup` installs | **old / no Cyber-Deck** |

Hashes are different. Running `waker setup` now would reinstall the old skill,
not the repo version. The user-wide `C:\Users\tuank\AGENTS.md` also has no
Waker live-UI instruction.

This is why dogfooding did not show how to open `waker watch`.

## Bug list

### B1 — Phase completion history is lost — HIGH

- `RunState.phase_status` is a single current value.
- `_sync_phase()` changes P1 → P2 by setting old status to completed and then
  immediately overwriting it with new running status.
- There is no `phase_statuses: dict[str, str]` or per-phase completion record.
- Result: chatbox cannot answer "which phase is done?".

### B2 — No `phase_started` / `phase_completed` events — HIGH

- `_sync_phase()` writes state only; it emits no event.
- `_finish()` sets the final phase completed only for `DONE`; no event.
- Event stream and report have no audit trail for normal phase transitions.
- Result: agent cannot distinguish "P1 done, P2 running" from "stuck".

### B3 — Wake prompt lacks phase context — HIGH

- `build_initial_prompt()` lists all tasks but does not say which phase is
  active.
- `build_wake_prompt()` lists missing tasks but not:
  - current phase,
  - completed phases,
  - remaining phase budget,
  - "do not start next phase".
- Result: the agent can work across phase boundaries, and chatbox updates are
  ambiguous.

### B4 — Status/report/UI are current-phase-only — HIGH

- `phase_snapshot()` returns one phase object.
- `waker status --format json` exposes only that object.
- `waker report` shows one phase block.
- Cyber-Deck shows one PHASE row.
- Result: after P1 completes, only P2 is visible; user thinks P1 was never
  acknowledged or the run is stuck.

### B5 — Phase completion can be masked by constraints — MEDIUM

- `_phase_unfinished()` includes work tasks **and constraints**.
- `phase_snapshot()` derives the current phase from work tasks only.
- A constraint-only pending item can make engine and UI disagree.

### B6 — Packaged skill template is stale — HIGH

- `src/waker/skill_templates/opencode/SKILL.md` is old.
- `waker setup` / `install-skill` copies that stale file.
- v2.3.0 users cannot see the new Grill-Me/phase/live-UI instructions from a
  fresh setup.

### B7 — Globally loaded chatbox skill is stale — HIGH

- `C:\Users\tuank\.opencode\skills\waker\SKILL.md` is older than repo skill.
- It has no Cyber-Deck section and does not tell the agent to provide:
  ```bash
  waker watch --repo . --run <run_id>
  waker watch --repo . --run <run_id> --window
  waker watch --repo . --run <run_id> --mini
  ```
- This is the immediate reason live UI was not shown during dogfooding.

### B8 — Live-view instruction is not prominent in docs — MEDIUM

- README has `waker watch --repo .`, but the after-start chatbox flow does not
  force the agent to give the concrete run id and `--window`/`--mini` fallback.
- User must search docs to find it.

### B9 — Three hours may be normal for overnight profile — NOT A BUG

- `overnight` has an 8-hour wall clock; 3 hours is not itself a timeout.
- If P1 is done and P2/P3 remain, the run is expected to keep going.
- The missing per-phase reporting makes this look like a stall.
- If the run is truly stuck, `run.json`, `events.jsonl` and `ledger.json` are
  needed to distinguish:
  - agent still working,
  - verify hung,
  - phase budget not enforced,
  - chatbox reporting stale.

## Reproduction

The phase-history issue was reproduced with a two-phase fake-agent run:

- P1 task done, P2 task done.
- Final state only exposed P2.
- No `phase_completed` event.
- `phase_snapshot` returned only P2.

A true "P1 done but P2 still running" observation should be captured from the
user's run with:

```powershell
waker status --repo <repo> --run <run_id> --format json
waker report --repo <repo> --run <run_id>
Get-Content <repo>/.waker/runs/<run_id>/events.jsonl -Tail 30
```

## Immediate mitigation

1. Do **not** run `waker setup` until the template is synced; it would install
   the old skill.
2. In the current terminal, live view is still available directly:
   ```powershell
   waker watch --repo . --run <run_id>
   ```
3. Treat a 3-hour run under `overnight` as potentially normal until
   `events.jsonl` shows a timeout/freeze.
4. Reinstall/sync skill only after the template fix.

## What is not broken

- `TIMEOUT` for turn/wall clock (v2.2/E5) is implemented.
- Phase budget 80% warning and 100% hard stop at turn boundary (v2.3/E8a)
  are implemented and tested.
- `resume --extend` is implemented and tested.
- Phase line, timeout red, and remaining time are implemented in the
  Cyber-Deck.
- The bug is **reporting/history/prompt context**, not the existence of those
  mechanisms.
