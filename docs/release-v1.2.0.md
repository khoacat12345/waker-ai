# waker-ai v1.2.0 — update notifications

This release adds a safe, non-blocking update notifier for users who install
Waker from PyPI.

## What it does

- Checks the public PyPI JSON metadata in a **background daemon thread**.
- Reads a small cache first (6-hour TTL); the check never blocks a command.
- On an interactive terminal, prints a small yellow banner when a newer
  version is available:

  ```text
  ╭──────────────────────────────────────────────────────╮
  │ Update available: 1.2.0 → 1.2.1                      │
  │ Run: pip install --upgrade waker-ai                  │
  ╰──────────────────────────────────────────────────────╯
  ```

- Writes to **stderr**, so `waker status --format json` and scripts keep a
  clean stdout.
- Falls back to ASCII on legacy Windows consoles.
- Disabled in CI, with `WAKER_UPDATE_CHECK=0`, or `NO_UPDATE_NOTIFIER`.
  No telemetry; only the public PyPI JSON is fetched.

## Notes

- pip never upgrades a package automatically. The banner only tells users how
  to run `pip install --upgrade waker-ai`.
- The cache lives under `%LOCALAPPDATA%\waker\update-check.json` on Windows,
  `~/Library/Caches/waker/` on macOS, and `$XDG_CACHE_HOME/waker/` (or
  `~/.cache/waker/`) on Linux.
- The notifier ships in 1.2.0; it will show a banner when a later release is
  published. Users on older versions need to upgrade once to get it.

## Verification

- Full test suite green (1 Windows-only skip).
- Unit coverage for version comparison, fresh/stale cache, failed network,
  TTY gating, env opt-out, ASCII fallback, and CLI integration.
- `waker --version` and a PyPI-installed smoke test verified.

## Install / upgrade

```bash
pip install --upgrade waker-ai
waker --version
```

## Checksums

> GitHub asset checksum. The PyPI wheel is built separately on CI and can
> differ byte-wise.

```
SHA256  b82ea700167395834ac95ac088fa481ff41469545191917d262715e1f53521a9
FILE    waker_ai-1.2.0-py3-none-any.whl (87,710 bytes)
```

## License

MIT
