# Waker Bugfix Plan — Phase Completion, Reporting & Skill Sync

**Status:** PROPOSED — chưa sửa code.
**Bug report:** [`WAKER_BUG_REPORT_2026-11-27.md`](WAKER_BUG_REPORT_2026-11-27.md)
**Baseline:** v2.3.0 main.
**Release target:** v2.3.1 hotfix for skill sync/reporting; optional v2.4.0
for phase-history UI if scope grows.

## Goal

Make Waker answer these questions truthfully at any time:

1. Phase nào đã xong?
2. Phase nào đang chạy?
3. Task nào đã pass, task nào còn pending?
4. Run đang thực sự chạy tiếp, timeout, hay đã kết thúc?
5. Làm sao mở live Cyber-Deck?

## Non-goals

- Không đổi nghĩa của `DONE` (vẫn cần evidence + verify).
- Không reset evidence/contract hash.
- Không làm phase tự chuyển khi agent chưa hoàn thành task.
- Không publish PyPI trong plan này nếu chưa có lệnh.

---

## F0 — Sync skill/templates and live-UI instructions — HOTFIX

**Priority:** P0, shortest path for dogfooding.
**Files:**

- `.opencode/skills/waker/SKILL.md`
- `src/waker/skill_templates/opencode/SKILL.md`
- `src/waker/skill_templates/claude/SKILL.md`
- `src/waker/skill_templates/gemini/SKILL.md`
- `src/waker/skill_templates/generic/AGENTS.md`
- `C:\Users\tuank\.opencode\skills\waker\SKILL.md` (installed copy, after sync)
- tests for template contents

**Changes:**

1. Use the repo skill as source of truth; sync it to the packaged template.
2. Add an explicit `## Live UI` section:
   ```powershell
   waker watch --repo . --run <run_id>
   waker watch --repo . --run <run_id> --window
   waker watch --repo . --run <run_id> --mini
   ```
3. Hard rule after `waker start`:
   - phải đưa command cụ thể với `run_id`,
   - phải nhắc `--window` nếu Windows GUI,
   - phải nhắc `--mini` nếu SSH/chatbox/non-TTY.
4. Add a test that every skill template contains:
   - `waker watch`
   - `--window`
   - `--mini`
5. Do **not** run `waker setup` before template sync; after sync, install global
   skill and restart chat session.
6. Add a short "How to see it live" callout in README.

**Acceptance:**

- Fresh `waker setup --for opencode --global` installs a skill containing the
  live-UI section.
- Global installed skill hash matches packaged template.
- New chat session tells the user the exact live command after start.
- `waker watch` works against a completed run and a running run.

**Estimate:** 0.5 day.

---

## F1 — Persist per-phase status and timestamps

**Priority:** P0/P1, fixes the "phase done but not reported" root cause.
**Files:** `src/waker/state.py`, `src/waker/engine.py`, tests.

**Data model:**

Add without breaking old `run.json`:

```python
phase_statuses: dict[str, str] = {}
# pending | running | completed | timeout

phase_started_at: dict[str, float] = {}
phase_completed_at: dict[str, float] = {}
```

Keep existing `phase_status` as a compatibility mirror of the active phase.

**Rules:**

- On prepare:
  - all known phases → `pending`
  - active P1 → `running`
  - emit `phase_started`
- On phase transition:
  - old phase → `completed`
  - save `phase_completed_at`
  - emit `phase_completed` with elapsed
  - new phase → `running`
  - emit `phase_started`
- On phase timeout:
  - status → `timeout`
  - save reason + unfinished tasks
- On run terminal:
  - only mark current completed if it really has no unfinished tasks;
  - never overwrite `timeout` with `completed`.

**Acceptance:**

- Run P1 then P2: `run.json` has P1 `completed`, P2 `completed`, and both
  timestamps.
- Run P1 done but P2 pending: state has P1 `completed`, P2 `running`.
- Existing old runs load with empty maps and remain readable.

**Estimate:** 1 day.

---

## F2 — Emit phase lifecycle events

**Priority:** P1.
**Files:** `src/waker/engine.py`, tests, maybe event consumers.

**Events:**

```json
{"t":"phase_started","phase":"P1","budget":3600,"at":"..."}
{"t":"phase_completed","phase":"P1","elapsed":3100,"tasks":["T1"],"at":"..."}
{"t":"phase_timeout","phase":"P2","unfinished":["T4"],"reason":"..."}
{"t":"budget_warning","phase":"P2","remaining":600}
{"t":"budget_extended","phase":"P2","extend_seconds":1800}
```

**Rules:**

- exactly one `phase_started` per phase entry;
- exactly one `phase_completed` per normal phase transition;
- no completed event if phase timed out;
- event data must come from ledger/state, never estimated.

**Acceptance:**

- P1 → P2 run has `phase_started(P1)`, `phase_completed(P1)`,
  `phase_started(P2)`, `phase_completed(P2)`.
- Timeout run has `phase_timeout` and no `phase_completed` for that phase.
- Chatbox can read event stream and say “P1 đã xong, đang sang P2”.

**Estimate:** 0.75 day.

---

## F3 — Inject phase context into initial/wake prompts

**Priority:** P1.
**Files:** `src/waker/injector.py`, `src/waker/engine.py`, tests.

**Initial prompt must include:**

```text
CURRENT PHASE: P1 — Auth & JWT
PHASE BUDGET: 45m
PHASE SCOPE TASKS: T1, T2
Do not start tasks from P2 until P1 is complete.
```

**Wake prompt must include:**

```text
PHASE: P2 — Stripe Payment (running)
COMPLETED PHASES: P1 (T1, T2)
REMAINING: 01:12:30
PENDING IN CURRENT PHASE: T4, T5
Do not work on P3 yet.
```

**Rules:**

- Phase warning at 80% is appended once.
- After phase completion, wake prompt acknowledges completed phase.
- If current phase times out, prompt says stop and report unfinished tasks.
- No phase context for legacy runs without phases.

**Acceptance:**

- Agent sees current phase and cannot claim it is on P1 when the ledger says P2.
- Prompt test checks phase name, remaining budget, completed phase, and
  “do not start next phase”.
- Warning prompt still contains the 80% message.

**Estimate:** 0.75 day.

---

## F4 — Status/report/UI expose all phases

**Priority:** P1.
**Files:** `src/waker/ui.py`, `src/waker/cli.py`, `src/waker/daemon.py`,
`tests/test_ui.py`, `tests/test_cli.py`.

**`waker status --format json`:**

```json
{
  "phase": {"id":"P2","status":"running"},
  "phases": [
    {"id":"P1","name":"Auth","status":"completed","elapsed":3100,"budget":2700},
    {"id":"P2","name":"Stripe","status":"running","elapsed":1200,"budget":7200}
  ]
}
```

**`waker status` markdown / `waker report`:**

- Phase table:
  ```text
  PHASE  STATUS      ELAPSED / BUDGET   PASSED/PENDING
  P1     completed   00:51:40 / 00:45   T1, T2 / -
  P2     running     00:20:00 / 02:00   T3 / T4, T5
  ```
- Current phase line remains for Cyber-Deck compact.
- Add `phase_completed` event line to report kick history.

**UI:**

- Cyber-Deck shows current phase plus a small `DONE: P1` / completed count.
- Do not add more than one row; preserve 22/24-line budget.
- Red timeout remains.

**Acceptance:**

- Chatbox status after P1 says `P1 completed`, `P2 running`.
- Report lists all phases and unfinished tasks.
- 120/80-column layout still within limits.
- Old runs without phase data show no fake table.

**Estimate:** 1 day.

---

## F5 — Regression tests and dogfood

**Priority:** P0/P1.
**Files:** `tests/test_engine.py`, `tests/test_ui.py`, `tests/test_cli.py`,
`tests/test_skill_install.py` (or new template test).

**Test matrix:**

1. Two-phase fake agent:
   - P1 done, P2 pending → state P1 completed/P2 running.
   - status JSON/report show both.
   - no next-phase work in prompt.
2. Full transition:
   - P1 → P2 → DONE; events `phase_started/completed` in order.
3. Phase timeout:
   - no completed event for timed-out phase;
   - `phase_timeout` includes unfinished IDs.
4. Resume `--extend`:
   - phase budget and max wall extended;
   - phase status returns running;
   - old completed phase remains completed.
5. Skill templates:
   - all packaged templates contain `waker watch`, `--window`, `--mini`.
6. Global install:
   - install to temp home; assert installed hash == template hash.
7. Legacy run:
   - no phase fields; status/report still work.

**Manual dogfood:**

- Create a 2-phase demo repo with fake agent.
- Start Waker.
- Ask chatbox progress; it must answer:
  - `P1 completed`
  - `P2 running`
  - live command.
- Let P2 run >80%; warning.
- Force phase timeout; resume with `--extend`; verify.

**Estimate:** 1 day.

---

## F6 — Release v2.3.1

**Priority:** after F0–F5 pass.

- Bump `2.3.1` in `pyproject.toml` and `src/waker/__init__.py`.
- Changelog: phase history, phase events, prompt context, status table,
  skill/template sync.
- Full pytest; build; twine check.
- Commit/tag/push/publish **only after explicit approval**.
- Do not publish if skill template still stale.

**Estimate:** 0.5 day.

---

## Immediate sequence

1. **F0 first** — sync skill/template and reinstall local chat skill; this fixes
   the “agent never told me how to open live UI” symptom today.
2. **F1 + F2** — persist and emit phase completion; this fixes the core
   “phase done but Waker doesn't report” bug.
3. **F3** — prompt phase context; prevents cross-phase work.
4. **F4** — status/report/UI all-phase visibility; fixes chatbox explanation.
5. **F5** — regression + dogfood.
6. **F6** — v2.3.1 release after approval.

## Definition of done

A two-phase run can be inspected at any point and answer unambiguously:

```text
P1: completed
P2: running
Current phase: P2
Remaining phase budget: ...
Pending tasks: ...
Live UI: waker watch --repo . --run <id>
```

No 3-hour run should look “stuck” merely because P1 completed and P2 is
running; the status must show both facts.
