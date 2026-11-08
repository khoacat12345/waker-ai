# waker-ai v1.1.2 — Linux CI fix (tests only)

Patch release after the v1.1.0/v1.1.1 tags failed on `ubuntu-latest`.

## Fixed

`tests/test_winproc.py` asserted `creationflags & CREATE_NO_WINDOW` on every OS.
On Linux `WINPROC.NO_WINDOW` is `0`, so three tests failed:

```
assert calls[0]["creationflags"] & winproc.NO_WINDOW  # 0 & 0
```

Those three tests are now skipped on non-Windows. The cross-platform static test
(`test_no_direct_subprocess_calls_in_src`) still runs on Linux and guards against
bypassing `waker.winproc`.

No product code changed.

## Verification

```
Windows: 186 passed, 1 skipped
Linux  : same suite; 3 Windows-only flag tests skipped
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v1.1.2/waker_ai-1.1.2-py3-none-any.whl
waker setup
```

## Checksums

```
SHA256  a5b1cd73ce1fa79dbb54677e897f1381c46fde381dbfbcc569d2eb32ec1d4547
FILE    waker_ai-1.1.2-py3-none-any.whl (85,964 bytes)
```

## License

MIT
