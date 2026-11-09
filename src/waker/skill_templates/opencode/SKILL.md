---
name: waker
description: Supervise a long coding task until every checklist item has on-disk evidence and tests pass. Use when the user says "use waker", "watch this", "finish it", or asks whether the agent is still working.
---

# waker — supervisor

You must **not** declare a task done yourself. Only the daemon decides, based on
`git diff ∩ scope` and `verify` exit codes. Your words are not evidence.

## If a run is already active

Every time the user sends a message (even if they do not ask for progress),
before answering:

1. Run `waker status --format md --repo .`
2. Insert the **full table** at the top of your answer.
3. If status is `running`: do not speculate or promise on the daemon's behalf.
4. If status is not `running`: read `waker report --repo .` and summarize the
   exact numbers (tasks done/total, tests, kicks, cost).

## Start a new run

1. **Identify the target repo.** If the prompt mentions a path that is not in
   the current repo (for example `.agents/v2/...` while in `waker-ai`), ask the
   user for the target repo before planning. Do not guess.
2. Take the user's prompt **verbatim** (drop a leading `@waker` if present).
   Do not summarize or reinterpret.
3. `waker plan --prompt "<verbatim>" --out .waker/tasks.yaml --repo <target repo>`
4. Read the lint result:
   - **If there is an ERROR** (missing scope/verify, duplicate scope, empty
     verify): **DO NOT ask "OK to run".** Show the errors and offer exactly two
     options:
     a) `waker plan --via opencode --model <model> --prompt "<verbatim>" --repo <repo>`
        to let a model fill scope/verify, then lint again;
     b) the user merges/fixes tasks manually.
   - Continue only when lint has **0 errors**.
5. When lint is clean: print `.waker/tasks.yaml` + any warnings, then ask
   exactly one question: `OK to run? (ok / edit)`.
6. When the user agrees, run:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<repo test command>" \
  --adapter opencode --model <provider/model> [--max-kicks 5] [--max-cost 1.0]
```

If not OpenCode, use the generic adapter:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<test command>" --adapter generic \
  --agent "claude -p --resume {session} {prompt}"
```

7. Answer immediately, do not go silent: "Running in the background. You can
   ask me for progress in chat, or open a terminal and run
   `waker watch --repo .` for the live view."

> Prompts that look like an instruction (approval, decision, numbered lines)
> are usually not tasks. Use `--via opencode` to group them into 3–6 tasks with
> scope/verify instead of turning each line into an empty task.

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
6. When reporting progress: only read `hidden x/y` from
   `waker status --format md`. Do not guess, do not print test names, do not
   print source.
7. **Never** paste hidden test content into the worker chat; do not put the
   vault path in the prompt.

## Hard rules

- If lint has an ERROR, **do not start** and **do not ask "OK to run"**.
- Do not edit `tasks.yaml` after starting (the hash will report TAMPER).
- Do not edit test files. To change tests, stop the run, edit, and restart.
- Do not say "done" — only read `status`/`report`.
- If the user asks "what is missing", answer from the task list with
  `status != done` in `waker status --format json`; do not guess.
