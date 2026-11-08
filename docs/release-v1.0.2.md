# waker-ai v1.0.2 — `start --detach` compatibility

Patch release for a one-line CLI bug found while launching a real overnight run.

## Fixed

`waker start --detach` now accepts `--detach`. The `start` command already runs
detached; the flag was rejected by argparse, so the command documented in the
waker skill failed with:

```
waker: error: unrecognized arguments: --detach
```

The flag is now accepted (and is a no-op, because detached is the default).

## Verification

```
130 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v1.0.2/waker_ai-1.0.2-py3-none-any.whl
waker setup
```

## Checksums

```
SHA256  f1018fc965db3691d39fa13b1eb2cde513cca3976f785044333c9a291238927f
FILE    waker_ai-1.0.2-py3-none-any.whl (71,323 bytes)
```

## License

MIT

