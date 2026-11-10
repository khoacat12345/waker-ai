# waker-ai v1.1.3 — English UI + live progress hints

This release makes Waker usable by an international audience and makes the
live view discoverable from the CLI and from chat agents.

## Highlights

- **English by default** for all user-facing output:
  - CLI help and messages (`waker setup`, `start`, `stop`, `status`, `report`).
  - `waker watch` TUI and `waker status --format md` tables.
  - Kick and initial prompts sent to the coding agent.
  - Vault, lint, engine, and doctor messages.
  - OpenCode / Claude / Gemini / generic skill templates.
- **Vietnamese input parsing is retained** (`waker plan` still understands
  Vietnamese prompts), but the UI no longer mixes languages.
- **Live progress is discoverable**: `waker setup` and `waker start` now print
  `waker watch`; skill templates tell the agent to announce the live view after
  starting and to paste `waker status` on every user message while a run is
  active.

## Verification

- Full test suite green (1 Windows-only skip).
- End-to-end proof run: public + hidden tests, `HIDDEN_FAIL` at kick 0, `DONE`
  at kick 1, English kick prompt with sanitized hidden failures.
- `waker --help`, `waker setup`, `waker doctor`, `waker watch`, and
  `waker status/report` verified in English.

## Install

```bash
pip install waker-ai==1.1.3
waker setup
waker doctor
```

## Checksums

> GitHub asset checksum. The PyPI wheel is built separately on CI and can
> differ byte-wise.

```
SHA256  017ae1dcef181c8416683d343145e95c106b19f4a2d632b91c90ee437d72201a
FILE    waker_ai-1.1.3-py3-none-any.whl (85,143 bytes)
```

## License

MIT
