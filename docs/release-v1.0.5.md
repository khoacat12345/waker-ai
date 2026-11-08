# waker-ai v1.0.5 — accurate progress and cost

Patch release for two display/accounting bugs found after run `989bcfca`
finished with 4 tasks + 1 constraint.

## Fixed

### `5/4 — 125%`

Constraints were counted as "done" but not in the denominator, so a finished
run showed 125%. Progress now counts only work tasks; a constraint is shown in
its own row and never inflates the percentage.

### Cost lost on a killed turn

`RunState.cost_usd` was only saved at kick boundaries. If a run was stopped
mid-turn, the cost of that turn vanished from the report. It is now persisted
immediately after every turn.

## Verification

```
141 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v1.0.5/waker_ai-1.0.5-py3-none-any.whl
waker setup
```

## Checksums

```
SHA256  43121e1ff94bc1ac4f5efa4270d4af72c8b46b3c9f791b67f3ec24924365d292
FILE    waker_ai-1.0.5-py3-none-any.whl (73,023 bytes)
```

## License

MIT

