# waker-ai v1.0.4 — one supervisor per run

Patch release for a race found during a real overnight session: two `--resume`
commands produced **two supervisors and two agents** editing the same repository.

## Fixed

### Run lock

`waker` now acquires an atomic `run.lock` before a run starts or resumes:

```
<repo>/.waker/runs/<run_id>/run.lock
pid
timestamp
run_id
```

- Second `start` / `run --resume` for an active run is refused with
  `run <id> is already active (pid N)`.
- Stale locks (process no longer alive) are replaced automatically.
- `start` checks the lock before spawning a detached child, so the common
  duplicate-resume path fails fast.

### `waker stop` updates the UI

`stop` now:

1. kills the process tree,
2. marks the run `aborted` with `ended_ts`,
3. removes the lock.

Previously it killed the engine but left `status: running`, so `waker watch`
showed a stale `0/N` forever.

## Verification

```
140 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v1.0.4/waker_ai-1.0.4-py3-none-any.whl
waker setup
```

## Checksums

```
SHA256  7e05d7215bf2cc5c2c7783ccea1a1cf911907bc1cb5bf8fdcf6ae048f146e0ed
FILE    waker_ai-1.0.4-py3-none-any.whl (72,955 bytes)
```

## License

MIT

