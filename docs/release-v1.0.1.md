# waker-ai v1.0.1 — worktree safety + a smarter skill

Patch release for two issues found during real use.

## Fixed

### 1. The skill asked to start when lint was red

v1.0.0's skill instruction said "ask OK để chạy?" unconditionally. When a long
prose/execution-order prompt produced 27 tasks with no `scope`/`verify`, the
linter correctly rejected it — but the skill still asked to start, which looked
like a crash.

Now the skill:

- shows the lint errors,
- **never** asks to start while errors remain,
- offers `--via opencode` (one planning turn) or a manual merge,
- asks for the **target repo** when the prompt references paths that do not
  exist in the current repo,
- strips the `@waker` prefix and warns that execution orders are not task lists.

### 2. Git worktrees could commit `.waker/`

`ensure_runtime_excluded` assumed `.git` is a directory. In a linked worktree
`.git` is a file, so the exclude was silently skipped and checkpoints could
commit runtime logs.

It now resolves `git rev-parse --git-common-dir` and writes the exclude there.

## Added

`waker plan` prints a hint when a prose prompt produces >= 6 tasks with no scope:

```
# Gợi ý: prompt này có vẻ là văn xuôi/lệnh thực thi...
# Dùng `--via opencode` để model điền scope/verify.
```

## Verification

```
129 passed, 1 skipped   (pytest, Windows 11 / Python 3.12)
CI matrix: ubuntu-latest + windows-latest × Python 3.11 + 3.12
```

## Install

```bash
pip install https://github.com/khoacat12345/waker-ai/releases/download/v1.0.1/waker_ai-1.0.1-py3-none-any.whl
waker setup
```

Or from source:

```bash
pip install "waker-ai @ git+https://github.com/khoacat12345/waker-ai.git"
```

## Checksums

```
SHA256  84cea7720910cef8e7a6ed37ed5cf7127dcbd83fa7a9e2ce1f9fb27f05d4baff
FILE    waker_ai-1.0.1-py3-none-any.whl (71,301 bytes)
```

## License

MIT

