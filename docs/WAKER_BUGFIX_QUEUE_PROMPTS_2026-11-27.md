# Waker v2.3.1 — Queue Prompts by Phase

**Status:** READY TO QUEUE — prompts only; no production code changed.
**Bug report:** [`WAKER_BUG_REPORT_2026-11-27.md`](WAKER_BUG_REPORT_2026-11-27.md)
**Fix plan:** [`WAKER_BUGFIX_PLAN_2026-11-27.md`](WAKER_BUGFIX_PLAN_2026-11-27.md)

## Queue order — do not run in parallel

```text
F0  Skill/template sync + live UI instructions
  -> F1  Per-phase state/history
  -> F2  Phase lifecycle events
  -> F3  Phase-aware initial/wake prompts
  -> F4  All-phase status/report/UI
  -> F5  Regression tests + dogfood
  -> F6  v2.3.1 release preparation (approval gate)
```

F1 and F2 touch `engine.py`/`state.py`; do not parallelize them.
F3/F4 should land after F1/F2 so they can read the new phase fields.

## Shared rules for every phase

- Repo: `C:\Users\tuank\waker-ai`
- Branch: `fix/v2.3.1-phase-reporting` (create from current `main` once).
- Do not delete unrelated untracked files (`.agents/`, other docs).
- Do not modify `main` directly.
- Do not push/tag/publish in F0–F5.
- Do not reset evidence, ledger, contract hash, or run state.
- Run targeted tests after the phase; report exact command and exit status.
- If a required behavior is already implemented, verify it and report instead of
  writing duplicate code.
- If tests fail, fix the implementation, do not weaken tests.

## Waker queue hints

Use these as scope/verify hints if queueing through Waker:

| Phase | Scope | Verify |
|---|---|---|
| F0 | `.opencode/skills/waker/**`, `src/waker/skill_templates/**`, `README.md`, `tests/test_skill_install.py` | `pytest tests/test_skill_install.py -q` |
| F1 | `src/waker/state.py`, `src/waker/engine.py`, `tests/test_engine.py`, `tests/test_state.py` | `pytest tests/test_engine.py tests/test_state.py -q` |
| F2 | `src/waker/engine.py`, `tests/test_engine.py` | `pytest tests/test_engine.py -q` |
| F3 | `src/waker/injector.py`, `src/waker/engine.py`, `tests/test_engine.py` | `pytest tests/test_engine.py -q` |
| F4 | `src/waker/ui.py`, `src/waker/cli.py`, `src/waker/daemon.py`, `tests/test_ui.py`, `tests/test_cli.py` | `pytest tests/test_ui.py tests/test_cli.py -q` |
| F5 | `tests/**`, `scripts/**` | `pytest -q` + manual dogfood |
| F6 | `pyproject.toml`, `src/waker/__init__.py`, `CHANGELOG.md`, `README.md`, `docs/**` | `pytest -q`, `python -m build`, `twine check` |

---

# F0 Prompt — Skill/template sync and live UI

```text
You are working in C:\Users\tuank\waker-ai.

Read:
- docs/WAKER_BUG_REPORT_2026-11-27.md
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md

Work only on branch fix/v2.3.1-phase-reporting. If it does not exist, create it
from current main; otherwise check it out. Do not push.

GOAL
Fix the dogfooding failure where @waker never tells the user how to open the
live Cyber-Deck. The repo skill is newer than the packaged template and the
globally installed skill.

REQUIRED CHANGES
1. Update .opencode/skills/waker/SKILL.md:
   - Add a dedicated "## Live UI" section.
   - After every successful waker start, require the agent to give the concrete
     run id and commands:
       waker watch --repo . --run <run_id>
       waker watch --repo . --run <run_id> --window
       waker watch --repo . --run <run_id> --mini
   - Explain Windows/--window, SSH/chatbox/--mini, and that --hold is only for
     the separate window.
   - Keep the existing Grill-Me conditional gate and phase-review flow.
   - Do not use raw terminal key prompts in chatbox mode.
2. Sync the OpenCode source skill into:
   - src/waker/skill_templates/opencode/SKILL.md
   Update Claude/Gemini/generic templates with the same Live UI contract.
3. Add or update tests in tests/test_skill_install.py:
   - every packaged template contains "waker watch", "--window", "--mini";
   - installing into a temp home produces the packaged template content;
   - repo skill and OpenCode template contain the Live UI section.
4. Add a short "How to see it live" subsection to README.md near Quickstart.
5. After tests pass, install the global OpenCode skill:
   .venv\Scripts\python.exe -m waker install-skill --for opencode --global
   Do not install before the template is synced. Report that the current chat
   session must be restarted to load the new skill.
6. Do not change engine/state/planner code.

ACCEPTANCE
- Template contains the live commands.
- Fresh install hash matches the packaged template.
- A chatbox session can answer: "how do I open the live UI?" with exact commands.
- Targeted tests pass.

COMMIT
docs(skill): sync live UI instructions and templates

REPORT
List changed files, test command/result, installed skill path, and the exact
restart instruction.
```

---

# F1 Prompt — Persist per-phase state/history

```text
You are working in C:\Users\tuank\waker-ai on branch
fix/v2.3.1-phase-reporting. Do not push/publish.

Read:
- docs/WAKER_BUG_REPORT_2026-11-27.md (B1/B5)
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md (F1)

GOAL
Fix the root cause where a completed phase is overwritten by the next phase and
therefore Waker cannot report "P1 completed; P2 running".

REQUIRED CHANGES
1. Extend RunState with backward-compatible defaults:
   - phase_statuses: dict[str, str]  # pending|running|completed|timeout
   - phase_started_at: dict[str, float]
   - phase_completed_at: dict[str, float]
   Keep phase_status and phase_elapsed for compatibility.
2. In Engine.prepare:
   - initialize all configured phases to "pending";
   - mark the first/current phase "running";
   - set phase_started_at.
3. In phase transitions:
   - accumulate elapsed for the old phase;
   - mark the old phase "completed" and set phase_completed_at;
   - mark the new phase "running" and set phase_started_at;
   - never mark a timeout phase as completed.
4. On final DONE:
   - mark the active phase completed only if it has no unfinished tasks;
   - preserve timeout status.
5. phase_elapsed_for and current phase calculations must use the new state
   without breaking legacy runs with no phase maps.
6. Add tests:
   - P1 done/P2 pending -> P1 completed, P2 running;
   - P1 -> P2 -> DONE -> both completed;
   - timeout -> timeout retained;
   - old run.json without new fields loads safely.

ACCEPTANCE
- A two-phase run exposes both phase statuses after transitions.
- No evidence/ledger/contract hash reset.
- tests/test_engine.py and tests/test_state.py pass.

COMMIT
fix(engine): persist per-phase status and completion history
```

---

# F2 Prompt — Emit phase lifecycle events

```text
You are working in C:\Users\tuank\waker-ai on branch
fix/v2.3.1-phase-reporting. Do not push/publish.

Read:
- docs/WAKER_BUG_REPORT_2026-11-27.md (B2)
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md (F2)

GOAL
Make phase transitions auditable instead of silent.

REQUIRED CHANGES
1. Emit exactly one phase_started event for each phase entry:
   {"t":"phase_started","phase":"P1","budget":...,"at":...}
2. Emit exactly one phase_completed event for each normal phase completion:
   {"t":"phase_completed","phase":"P1","elapsed":...,"tasks":[...],"at":...}
3. Keep phase_timeout and budget_warning behavior.
4. Do not emit phase_completed for a phase that timed out.
5. Include phase events in the event stream consumed by status/report/UI.
6. Add tests:
   - P1 -> P2 -> DONE event order;
   - no duplicate phase_started/completed;
   - timeout has phase_timeout and no completion for that phase.
7. Do not change task/evidence semantics.

ACCEPTANCE
- events.jsonl shows P1 completed before P2 started.
- Chatbox can answer which phase is done from events.
- tests/test_engine.py passes.

COMMIT
feat(engine): emit phase lifecycle events
```

---

# F3 Prompt — Phase context in initial/wake prompts

```text
You are working in C:\Users\tuank\waker-ai on branch
fix/v2.3.1-phase-reporting. Do not push/publish.

Read:
- docs/WAKER_BUG_REPORT_2026-11-27.md (B3)
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md (F3)
- src/waker/injector.py and the current initial/wake prompt tests.

GOAL
Make the agent work inside the current phase and acknowledge completed phases.

REQUIRED CHANGES
1. Initial prompt includes:
   - CURRENT PHASE, name, budget;
   - task IDs in the current phase;
   - explicit "Do not start tasks from the next phase".
2. Wake prompt includes:
   - current phase and status;
   - completed phases and their passed task IDs;
   - remaining phase budget;
   - pending tasks in current phase;
   - explicit next-phase barrier.
3. Keep the 80% budget warning once per phase.
4. Legacy runs without phases keep the old prompt shape.
5. Add tests that assert:
   - current phase name;
   - remaining budget;
   - completed phase ID;
   - "do not start next phase";
   - 80% warning content.

ACCEPTANCE
- A prompt for P2 contains P1 completed and P2 current.
- Prompt never tells the agent to start a phase that is not active.
- tests/test_engine.py passes.

COMMIT
feat(prompt): inject current/completed phase context
```

---

# F4 Prompt — All-phase status, report and UI

```text
You are working in C:\Users\tuank\waker-ai on branch
fix/v2.3.1-phase-reporting. Do not push/publish.

Read:
- docs/WAKER_BUG_REPORT_2026-11-27.md (B4/B5)
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md (F4)

GOAL
Make waker status/report/Cyber-Deck show all phases, not only the active one.

REQUIRED CHANGES
1. Extend phase_snapshot to return:
   - current phase;
   - phases[] with id, name, status, elapsed, budget, remaining,
     passed task IDs and pending task IDs.
2. Add "phases" to waker status --format json.
3. Add a compact phase table to waker status markdown and waker report.
4. Keep the Cyber-Deck within 22/24 rows:
   - show current phase line;
   - show completed-phase count or a compact "DONE: P1" line.
5. Include constraints where they belong to a phase, so engine and UI agree.
6. Preserve legacy runs without phases.

ACCEPTANCE
- P1 done/P2 running is visible in status JSON, status markdown, report and deck.
- No text overflow at 80 or 120 columns.
- tests/test_ui.py and tests/test_cli.py pass.

COMMIT
feat(ui): show all phase states in status and report
```

---

# F5 Prompt — Regression tests and dogfood

```text
You are working in C:\Users\tuank\waker-ai on branch
fix/v2.3.1-phase-reporting. Do not push/publish.

Read:
- docs/WAKER_BUG_REPORT_2026-11-27.md
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md (F5)

GOAL
Prove the phase-completion bug is gone, including in the chatbox workflow.

REQUIRED TESTS
1. Two-phase fake agent:
   - P1 completed, P2 pending after the first transition;
   - status JSON/markdown/report show both;
   - phase events show P1 completed then P2 started.
2. Full transition P1 -> P2 -> DONE.
3. Phase timeout and resume --extend:
   - timeout phase not marked completed;
   - extension returns phase to running;
   - old completed phases remain completed.
4. Phase-aware prompt assertions.
5. Skill template/install assertions.
6. Legacy run without phases.
7. Full pytest.

MANUAL DOGFOOD
- Create a temporary two-phase demo repo.
- Run Waker and ask chatbox for progress.
- It must answer P1 completed/P2 running and give exact waker watch command.
- Check live UI and `--window` behavior.
- Do not use a real secret/token.

ACCEPTANCE
- Full pytest 0 failed (one opt-in live skip allowed).
- Manual script shows P1 done/P2 running.
- Report exact commands/results.

COMMIT
test(phase): cover completion reporting and chatbox dogfood
```

---

# F6 Prompt — v2.3.1 release preparation

```text
You are working in C:\Users\tuank\waker-ai on branch
fix/v2.3.1-phase-reporting. Do not push, tag, or publish without explicit
approval.

Read:
- docs/WAKER_BUGFIX_PLAN_2026-11-27.md (F6)
- CHANGELOG.md

GOAL
Prepare v2.3.1 for approval.

REQUIRED CHANGES
1. Bump version to 2.3.1:
   - pyproject.toml
   - src/waker/__init__.py
2. CHANGELOG v2.3.1:
   - per-phase status/history;
   - phase_started/phase_completed events;
   - phase-aware prompts;
   - all-phase status/report/UI;
   - skill/template sync + live UI instructions.
3. Update README status/PyPI wording for v2.3.1.
4. Run full pytest.
5. Build: python -m build
6. Twine: twine check dist/waker_ai-2.3.1*
7. Report commit hash, test result, artifact names and twine result.
8. Stop. Do not tag, push, upload or publish until the product owner explicitly
   approves.

ACCEPTANCE
- 0 failed tests; one opt-in skip allowed.
- wheel + sdist pass twine.
- Working tree clean after commit.
- Release artifacts remain local.

COMMIT
chore(release): prepare v2.3.1
```

## Final queue checklist

Before queueing:

- [ ] Start from current `main`; create `fix/v2.3.1-phase-reporting`.
- [ ] Queue F0 first.
- [ ] Queue F1 then F2 sequentially (same engine files).
- [ ] Queue F3 after F2.
- [ ] Queue F4 after F3.
- [ ] Queue F5 after F4.
- [ ] Queue F6 only after F5 passes and user approves release.
- [ ] Do not run F1/F2 in parallel.
- [ ] Restart the chat session after F0 installs the global skill.
- [ ] Keep the v2.3.0 tag/release untouched.
