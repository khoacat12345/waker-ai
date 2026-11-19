---
name: waker
description: Supervise a long coding task until every checklist item has on-disk evidence and tests pass. Use when the user says "use waker", "watch this", "finish it", or asks whether the agent is still working.
---

# waker — supervisor

You must **not** declare a task done yourself. Only the daemon decides, based on
`git diff ∩ scope` and `verify` exit codes. Your words are not evidence.

## If a run is already active

1. Run `waker status --format md --repo .`
2. Insert the **full table** at the top of your answer.
3. If status is `running`: do not speculate or promise on the daemon's behalf.
4. If status is not `running`: read `waker report --repo .` and summarize the
   exact numbers (tasks done/total, tests, kicks, cost).

## Grill-Me Check (only when starting a run)

Run this check **only** when the user asks to plan/start a new Waker run. Do not
run it for status, progress, explanations, code review, or while a run is
already active.

### Silent-pass

Do **not** ask any questions when the prompt already contains enough to build a
verifiable contract:

- **Goal**: the intended outcome is clear.
- **Scope**: files/modules/directories to change are known.
- **Verify**: a test command or objective acceptance check exists.
- **Required input**: no missing credential, environment, data, or deploy
  access that blocks the start.

When all four are present, skip Grill-Me entirely and continue with the normal
`waker plan` flow. "Silent-pass" means **0 Grill-Me questions**; do not invent
extra questions to look thorough.

### Ask only when blocked

Ask only when at least one of the four items above is missing and guessing
wrong would produce the wrong result or make the contract unverifiable.

Rules:

- Ask **at most 3 questions in one round**.
- Ask only blocking questions; never ask about preferences, naming, minor
  library choices, or visual style.
- Never invent `scope` or `verify`.
- Never answer your own questions.
- If the user replies "whatever you decide", "tùy bạn", or similar for a
  preference, record it as a `preference` and choose a safe default.
- If the user says "whatever" for `scope` or `verify`, do **not** treat that as
  permission to guess: stop and ask them to provide or split the task.
- If the prompt is still ambiguous after 3 questions, stop and ask the user to
  split it into smaller tasks. Do not call `waker plan`.

Suggested format:

```text
Grill-Me — cần chốt 2 điểm trước khi freeze contract:

1. Scope: auth sửa trong src/auth/** hay cả src/api/**?
2. Verify: dùng pytest tests/auth -q hay cần thêm case login sai trả 401?

Trả lời xong mình mới tạo tasks.yaml.
```

## Start a new run

0. Run the **Grill-Me Check** above first. If it is silent-pass, continue here.
   If it asks blocking questions, stop and wait for the user's answers before
   calling `waker plan`.
1. Identify the target repo. If the prompt mentions a path that is not in the
   current repo, ask the user for the target repo before planning. Do not guess.
2. Take the user's prompt **verbatim** (drop a leading `@waker` if present).
3. Choose the phase mode before planning:
   - small, clear task (≤2 tasks, one phase): `--phases none`
   - user supplied explicit phases: `--phases manual`
   - large/multi-module task: `--phases auto --profile <profile>`
     (`small|medium|large|overnight`)
   - use `--json` when you need to read the plan programmatically.
   ```bash
   waker plan --prompt "<verbatim>" --out .waker/tasks.yaml --repo <repo> \
     [--phases none|manual|auto] [--profile large] [--json]
   ```
4. Read the lint result:
   - **If there is an ERROR** (missing scope/verify, duplicate scope, empty
     verify): **do not ask "OK to run".** Show the errors and offer exactly two
     options:
     a) `waker plan --via opencode --model <model> --prompt "<verbatim>" --repo <repo>`
        so a model fills scope/verify, then lint again;
     b) the user merges/fixes tasks manually.
   - Continue only when lint has **0 errors**.
5. When lint is clean, branch by task size:
   - **Small fast path:** prompt is clear, `/waker` was explicit, and the plan
     has ≤2 tasks in one phase. Print a one-line summary, then start immediately
     with `--phases none`; do not ask an extra phase question.
   - **Large review path:** print the phase table and any warnings, then ask
     exactly one question: `Chạy luôn? (ok / sửa)`. Wait for `ok`, `1`, or
     `chạy`; do not start before that.
6. When the user agrees (or the small fast path applies), start the run:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<repo test command>" \
  --adapter opencode --model <provider/model> [--max-kicks 5] [--max-cost 1.0]
```

7. Answer immediately: "Running in the background. You can ask me for progress
   in chat, or run `waker watch --repo .` for the live view."

## Chatbox phase review

This section applies when running inside a chatbox, not a raw terminal.

- **Never use raw terminal key prompts** such as `[Enter]`, `[e]`, or reading
  individual keys. They can block the chatbox. Use normal conversational text.
- For a large task, after `waker plan --phases auto` show:
  ```text
  Mình đề xuất 3 phase (profile large, cap 5h):
  P1  Auth & JWT      T1–T3   45m
  P2  Stripe Payment  T4–T7   2h
  P3  E2E & Security  T8–T9   30m
  Chạy luôn? (ok / sửa)
  ```
- Accept exactly `ok`, `1`, or `chạy` as approval. Anything else is feedback,
  not approval.
- If the user edits in natural language (for example “tăng P2 lên 3h, P1 còn
  30m”):
  1. Update the matching phase objects in `.waker/tasks.yaml`.
  2. Run `waker lint --tasks .waker/tasks.yaml --repo <repo>`.
  3. Show a short confirmation of the new budgets and lint result.
  4. Ask the same approval question again. Do not start until the user approves.
- Do not change `scope`, `verify`, or task ownership while editing budgets.
  If a requested edit is ambiguous, ask one blocking question.
- Non-TTY/chatbox mode must never wait for a keypress; it may print the plan
  and exit with instructions instead.

## Cyber-Deck (`/waker`)

When a run is active and the user asks for progress, a visual view, or uses
`/waker`:

```powershell
# Windows: open a separate terminal window, once per run
waker watch --repo . --run <run_id> --window

# SSH / no GUI / chatbox fallback
waker watch --repo . --run <run_id> --mini
```

The `/waker` command must attach to the **existing** run. Do not start a second
run and do not spawn more than one window for the same run id. If `--window`
cannot open (non-Windows, SSH), fall back to `--mini`; never guess progress.

## Stop

`waker stop --repo .`

## Blind evaluation (Kaggle mode)

When the user says "blind grading", "hidden test", or "Kaggle mode":

1. Write hidden tests to separate files, **not** in the working repo.
2. `waker vault init --repo .` → get `vault_id`.
3. `waker vault add --vault <id> --suite <name> --task T1 <file>`
4. `waker vault validate --vault <id> --repo .` — if FAIL, fix the suite and
   rerun; **do not** start until the suite validates.
5. Start: `waker start --detach --vault <id> --tasks .waker/tasks.yaml ...`
6. Report only `hidden x/y` from `waker status --format md`; do not guess, print
   test names, or print source.
7. **Never** paste hidden test content into the worker chat; do not put the
   vault path in the prompt.

## Hard rules

- If lint has an ERROR, **do not start** and **do not ask "OK to run"**.
- In chatbox mode, never use raw key reads or `[Enter]/[e]` prompts.
- No explicit `ok` / `1` / `chạy` means no large-run start.
- Do not edit `tasks.yaml` after starting (the hash will report TAMPER).
- Do not edit test files. To change tests, stop the run, edit, and restart.
- Do not say "done" — only read `status`/`report`.
- If the user asks "what is missing", answer from the task list with
  `status != done` in `waker status --format json`; do not guess.
