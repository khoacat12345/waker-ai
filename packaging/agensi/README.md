# waker — never let an AI coding agent sleep on the job

`waker` is a local watchdog for AI coding agents. It watches the disk (not the
agent's words), verifies a frozen contract, and wakes the agent until every task
has on-disk evidence and tests pass.

This package contains the **skill instructions only**. The engine is a local
Python CLI installed separately:

```bash
pip install waker-ai
waker setup
waker doctor
```

- Repository: https://github.com/khoacat12345/waker-ai
- PyPI: https://pypi.org/project/waker-ai/
- License: MIT

## What the skill does

- Turns a user request into a mechanical contract (`waker plan`).
- Starts the supervisor in the background (`waker start --detach`).
- Reports progress from the ledger (`waker status`, `waker report`).
- Optionally grades hidden tests without showing them to the worker
  (`waker vault`).

## What it does not do

- It does not run inside the model; it needs the local CLI.
- It does not install packages without explicit user consent.
- It never declares success on its own.
