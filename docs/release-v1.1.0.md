# waker-ai v1.1.0 — Blind Evaluation (Kaggle Mode)

> The Architect writes the exam. The worker never sees it. Waker grades blind.

## What's new

### Hidden Test Vault

The Architect (chatbox) stores hidden tests in a vault **outside the repo**:

```bash
waker vault init --repo .
waker vault add --vault <id> --suite auth --task T1 tests/test_auth_hidden.py
waker vault validate --vault <id> --repo .
waker run --tasks tasks.yaml --vault <id> ...
```

- Vault live in `%LOCALAPPDATA%\waker\vault\<id>` (Windows) or XDG data dir.
- Only the random `vault_id` travels into the run config — never a path.
- Manifest stores per-file SHA256 + suite hash; **no test source**.
- `waker vault validate` enforces: baseline red, no import/collect errors, no
  skip/xfail, at least one test, two runs agree (no flaky).

### Blind grading

- Hidden suites run in an isolated temp dir with the repo on `PYTHONPATH`.
- Failures map to opaque ids: `hidden://auth/test_3: AssertionError: ...`.
- Paths, temp dirs, source lines and locals are stripped.
- `leak: minimal` shows only "test_N failed"; `leak: message` adds the assertion
  message; source is never returned.
- Temp dir is deleted even on timeout.

### Engine gates

- `--vault <id>` on `waker run` / `waker start`; a task with `blind` and no
  vault fails closed.
- `DONE` requires **100% hidden + public smoke + constraints**.
- New diagnoses: `HIDDEN_FAIL` (kick with sanitized diagnostics),
  `VAULT_TAMPER` (stop), `SUSPECT_TEST` (broken exam, stop).
- Ledger/status show only `hidden x/y`; no test names or source.

### Contract additions

```yaml
- id: T1
  verify: "pytest tests/test_auth_smoke.py -q"
  public_api: ["login(name, password) -> token | None"]
  blind:
    suite: auth
    baseline: red
    timeout: 120
    leak: message
```

## Security model (read this)

v1.1 is **blind by construction**, not an adversarial sandbox:

- The worker runs as the same OS user; if it actively searches the filesystem it
  can read the vault. It is not told the path, and the path is not in its prompt,
  scope, ledger or report.
- Real isolation requires Docker/Windows Sandbox — planned for v1.2.
- This protects against self-grading bias, lazy test writing and test tampering,
  not against a hostile process.

## Verification

```
181 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

40 new tests cover: vault storage, validation (red/import/skip/flaky), sanitized
grading, temp cleanup, engine gates, missing vault, resume with vault.

## Install

PyPI publishing is pending. Until the first upload:

```bash
pip install "waker-ai @ git+https://github.com/khoacat12345/waker-ai.git"
waker setup
```

Or the attached wheel:

```bash
pip install waker_ai-1.1.0-py3-none-any.whl
```

## Checksums

```
SHA256  6e9f018d1da325d82d3d97ef26517dc91400d207a891b3757a612e120adfd862
FILE    waker_ai-1.1.0-py3-none-any.whl (84,815 bytes)
```

## License

MIT
