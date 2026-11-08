# waker-ai v1.0.3 — silent background on Windows

Patch release for the console-window flashes that stole focus during background
runs.

## Fixed

Every child process launched by waker now carries `CREATE_NO_WINDOW`
(`0x08000000`) on Windows. The flag is applied through one helper,
`waker.winproc`, so it cannot be forgotten:

- `git` probes (`status`, `diff`, `ls-files`, `checkout`, `commit`)
- `pytest` / verify commands
- `taskkill /T /F` in the tree killer
- `opencode session export` cost reads
- `doctor` version probes
- detached daemon / worker spawn (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
  CREATE_NO_WINDOW`)
- planner file listing and worktree resolution

A regression test (`tests/test_winproc.py`) both checks the flag and fails if any
module reintroduces a direct `subprocess.run` / `subprocess.Popen` call.

## Scope

This makes **waker's own** subprocesses invisible. If an agent CLI opens console
windows when *it* runs shell tools, that is outside waker's process; the PTY
adapter (tier 3) is the path to a fully invisible session.

## Verification

```
135 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v1.0.3/waker_ai-1.0.3-py3-none-any.whl
waker setup
```

## Checksums

```
SHA256  ed6a98a9edc51de35ada1bfb96dbd4ba870cf276e8c453bc8d4f99dc9b13ee53
FILE    waker_ai-1.0.3-py3-none-any.whl (71,950 bytes)
```

## License

MIT

