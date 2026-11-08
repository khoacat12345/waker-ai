# waker-ai v1.1.1 — blind evaluation, finished (Phase E–F)

Completes the plan in `docs/BLIND_EVALUATION_SPEC.md` after v1.1.0 shipped the
core (Phase A–D).

## Added

### Acceptance tests (fake agents)

- **Leak check**: the worker prompt, ledger and report contain no vault id, vault
  path, hidden file name or test source.
- **Hardcode**: an agent that satisfies only the public smoke but not the hidden
  suite gets `HIDDEN_FAIL` with a sanitized wake prompt.
- **Vault tamper**: editing a hidden test file after validation now triggers
  `VAULT_TAMPER` (exit 5).
- **CLI end-to-end**: `waker run --vault <id>` with a fake worker reaches DONE
  only when the hidden suite passes.

### `Vault.current_hash()`

The previous `vault_hash()` hashed the manifest, so editing a file on disk was
invisible. The engine now compares hashes recomputed from the actual files.

### Skill workflow

OpenCode / Claude / Gemini skill templates now document blind mode:

```bash
waker vault init --repo .
waker vault add --vault <id> --suite auth --task T1 tests/test_auth_hidden.py
waker vault validate --vault <id> --repo .
waker start --detach --vault <id> --tasks .waker/tasks.yaml ...
```

Hard rule: never paste hidden tests into the worker chat; never put the vault
path in the prompt.

### Demo

The README GIF now includes a blind-evaluation frame (`hidden 12/12`, sanitized
failure ids).

## Verification

```
186 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

PyPI publishing is pending. Until the first upload:

```bash
pip install "waker-ai @ git+https://github.com/khoacat12345/waker-ai.git"
waker setup
```

Or the attached wheel:

```bash
pip install waker_ai-1.1.1-py3-none-any.whl
```

## Checksums

```
SHA256  2d33412c49c5edc30d8c6eb292ebdc37fc5e3b3c9dc408e25a8d3d087e4c9c17
FILE    waker_ai-1.1.1-py3-none-any.whl (85,961 bytes)
```

## License

MIT
