---
name: waker
description: Supervise a long coding task with an external watchdog until every task has on-disk evidence and tests pass. Supports blind hidden-test grading.
version: 1.1.2
author: khoacat12345
license: MIT
homepage: https://github.com/khoacat12345/waker-ai
---

# waker — supervisor for AI coding agents

`waker` is a **local CLI supervisor**, not an in-model prompt. It launches and
grades a coding agent (OpenCode, Claude Code, Gemini, or a generic process) on
the user's machine. This skill is the control protocol.

## Prerequisite — ask the user first

Do **not** install anything silently. Ask the user to run:

```bash
pip install waker-ai
waker setup
waker doctor
```

If `waker` is missing after that, stop and tell the user. Never pretend to
supervise without the CLI.

## Start a run

1. Take the user's request **verbatim**. Do not summarise it.
2. Create the contract:

```bash
waker plan --prompt "<verbatim>" --out .waker/tasks.yaml --repo .
```

3. Print `.waker/tasks.yaml` and every lint warning.
   If lint has **errors**, do **not** start. Offer `waker plan --via opencode`
   or ask the user to add `scope`/`verify`.
4. Start in the background:

```bash
waker start --detach --repo . --tasks .waker/tasks.yaml \
  --adapter opencode --model <provider/model> \
  --test "<test command>" --max-kicks 5 --max-cost 1.0
```

5. Report the run id and say: "Running in the background."

## Status

```bash
waker status --format md --repo .
waker report --repo .
```

Paste the table verbatim. Never declare success yourself — only `waker status`
and `waker report` decide. If the user asks "what is missing", read task status
from `waker status --format json`.

## Blind evaluation (optional)

When the user asks for hidden tests / Kaggle mode:

```bash
waker vault init --repo .
waker vault add --vault <id> --suite <name> --task T1 <hidden_test.py>
waker vault validate --vault <id> --repo .
waker start --detach --vault <id> --tasks .waker/tasks.yaml ...
```

The hidden suite lives outside the repo. Never paste its content into the worker
chat and never put the vault path in a prompt.

## Hard rules

- Do not claim a task is done; the daemon decides from `git diff ∩ scope` plus
  `verify` exit code.
- Do not edit `tasks.yaml` or test files after starting a run.
- Do not install packages (including `waker-ai`) without explicit user consent.
- Do not run `waker` with `--auto` / bypass permissions in a repo the user did
  not approve.
