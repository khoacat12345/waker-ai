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
3. If status is not `running`: read `waker report --repo .` and summarize the
   exact numbers.

## Start a new run

1. Take the user's prompt **verbatim** (drop a leading `@waker` if present).
2. `waker plan --prompt "<verbatim>" --out .waker/tasks.yaml --repo .`
3. Print `.waker/tasks.yaml` + lint warnings, then ask `OK to run? (ok / edit)`.
4. When the user agrees:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --test "<test command>" \
  --adapter generic --agent "claude -p --resume {session} {prompt}" \
  [--max-kicks 5] [--max-cost 1.0]
```

5. Answer immediately, do not go silent: "Running in the background. You can
   ask me for progress in chat, or open a terminal and run
   `waker watch --repo .` for the live view."

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

- Do not edit `tasks.yaml` after starting.
- Do not edit test files.
- Do not say "done" — only read `status`/`report`.
- "What is missing" = the task list with `status != done` in
  `waker status --format json`.
