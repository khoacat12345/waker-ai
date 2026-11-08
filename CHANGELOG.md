# Changelog

All notable changes to `waker-ai`.

## v1.1.2 — 2026-11-08

### Fixed

- Linux CI: the Windows-only `CREATE_NO_WINDOW` assertions in
  `tests/test_winproc.py` are now skipped on non-Windows. The static test that
  forbids direct `subprocess.run`/`Popen` calls still runs everywhere.
- No product change; v1.1.0/v1.1.1 code is unchanged.

### Tests

- 186 passed, 1 skipped (Windows); Linux runs 2 + 3 skipped in that module.

## v1.1.1 — 2026-11-08

### Added / completed (Phase E–F of the blind evaluation spec)

- Acceptance fake agents: prompt/report leakage, public-pass + hidden-fail,
  vault file tamper, and a full CLI blind run.
- `Vault.current_hash()` recomputes file hashes on disk; editing a vault file
  now triggers `VAULT_TAMPER` (the manifest-only hash could not detect it).
- Skill templates (OpenCode / Claude / Gemini): blind workflow — `vault init`,
  `add`, `validate`, `start --vault`; never paste hidden tests into the worker
  chat.
- README demo GIF includes a blind-evaluation frame.

### Tests

- 186 passed, 1 skipped.

## v1.1.0 — 2026-11-08

### Added — Blind Evaluation (Kaggle Mode)

- Hidden test vault **outside the repo** (`%LOCALAPPDATA%` / XDG), referenced by
  a random `vault_id` only.
- `waker vault init/add/list/rm` — Architect stores hidden suites; file hashes
  and suite hash in the manifest, never test source.
- `waker vault validate` — baseline red/green, collect errors, skip/xfail,
  timeout and two-run flakiness check; marks `validated_at`.
- `blind_runner` — grades in an isolated temp dir, maps failures to opaque
  `test_N` ids, redacts paths, supports `leak=minimal|message`, always cleans up.
- Engine: `--vault <id>` on `run`/`start`, auto-validate at prepare, gates
  `G_hidden` / `G_vault`, diagnoses `HIDDEN_FAIL`, `VAULT_TAMPER`,
  `SUSPECT_TEST`; hidden counts in ledger/status/report; sanitized wake prompts.
- 40 new tests for the feature (vault, validation, grading, engine integration).
- **Security model:** blind by construction, not an adversarial sandbox. Same
  user can still read the vault if it searches; Docker/Windows Sandbox is v1.2.

## v1.0.5 — 2026-11-08

### Fixed

- Progress no longer counts constraints in the numerator: a run with 4 tasks
  and 1 constraint now shows `4/4` instead of `5/4 — 125%`.
- The `diagnose` event uses the same work-task count.
- Cost is persisted immediately after every turn. A killed/stopped run no longer
  loses the cost of the turn that was in flight.

## v1.0.4 — 2026-11-08

### Fixed

- **One supervisor per run**: an atomic `run.lock` (pid + timestamp) is acquired
  by `prepare()` / `from_run()`. Starting or resuming an already-active run is
  refused instead of spawning a duplicate engine and a duplicate agent.
  Stale locks (dead pid) are replaced automatically.
- **`waker stop` is honest**: it now marks the run `aborted`, sets `ended_ts`,
  and removes the lock. `waker watch` exits instead of showing a stale
  "running 0/N" forever.
- Found in the wild: two `--resume` calls produced two supervisors editing the
  same repo at once. The lock prevents that class of bug.

## v1.0.3 — 2026-11-08

### Fixed

- **Windows console popups**: every `subprocess.run` / `Popen` now goes through
  `waker.winproc`, which adds `CREATE_NO_WINDOW` on Windows. This covers git,
  pytest, `taskkill`, OpenCode session export, doctor version probes, planner
  file listing and the detached daemon—no more conhost flashes or focus steals.
- A static test now fails if any module bypasses `waker.winproc` with a direct
  `subprocess.run` / `subprocess.Popen` call.

### Notes

- This hides **waker's own** child processes. If an agent CLI itself creates
  console windows when it runs shell tools, that is outside waker's process; use
  the PTY adapter (tier 3) when a fully invisible session is required.

## v1.0.2 — 2026-11-08

### Fixed

- `waker start --detach` now accepts the `--detach` flag used by the skill
  documentation. `start` was already detached; argparse rejected the redundant
  flag, which broke the documented command.

## v1.0.1 — 2026-11-08

### Fixed

- **Skill UX**: never asks "OK để chạy?" when lint has errors. It now shows the
  errors and offers `--via opencode` or a manual merge.
- **Skill repo guard**: asks for the target repo when prompt paths do not exist
  in the current repo (e.g. `.agents/...` while inside `waker-ai`).
- **Skill prompt hygiene**: strips the `@waker` prefix; warns that execution
  orders are not task lists.
- **Git worktrees**: `ensure_runtime_excluded` now uses
  `git rev-parse --git-common-dir`, so `.waker/` is excluded even when `.git`
  is a file (worktree). Previously a worktree run could commit runtime logs.

### Added

- `waker plan` prints a hint when a prose prompt yields >= 6 tasks with no
  scope, suggesting `--via opencode`.

## v1.0.0 — 2026-11-08

### Added

- `waker plan --via opencode`: one planning turn converts a vague prompt into a
  `tasks.yaml` contract, then the deterministic linter validates it (fail closed).
- `waker run --resume <id>`: continue an interrupted or failed run from its
  on-disk ledger, with a fresh kick budget and a `generation` suffix for kick
  artifacts (`kick-N-g1`) so the audit trail is preserved.
- `waker detect`: detects pytest / npm / cargo / go / make test and prints
  confidence + source.
- `.github/workflows/publish.yml`: PyPI Trusted Publishing (OIDC) with an API
  token fallback.
- `docs/demo.gif` + `scripts/make_demo_gif.py`: generated README demo.
- `docs/demo-45s.md`: 45-second recording script.
- `CHANGELOG.md`, `docs/release-v1.0.0.md`.

### Changed

- State now stores adapter/model/permission/binary/constraint data so a run can
  be resumed exactly.
- `RunState.elapsed` includes time from previous generations.
- Claude is documented as **beta** (unit-tested, no live CI run).
- Cost guard scope documented: exact for OpenCode, best-effort for Claude,
  0 for generic/PTY.

### Tests

- 127+ automated tests (Windows 11 / Python 3.12), plus a gated live OpenCode
  E2E. CI matrix: Ubuntu + Windows × Python 3.11 + 3.12.

## v0.3.1 — 2026-11-07

- `waker setup`: detect installed CLIs and install the skill globally.
- Fallback to existing config directories when no CLI is on PATH.
- README one-command onboarding note.

## v0.3.0 — 2026-11-07

- Claude Code T1 adapter (stream-json, resume, permission mode).
- PTY tier-3 adapter (ConPTY + pyte) on Windows.
- `waker doctor` with adapter tiers and a safe injector self-test.
- Per-scope verify scheduling + full-suite gating.
- Web dashboard (static + live) and Rich watch TUI.
- Wheel packaging, CI matrix, release v0.3.0.

## v0.2.0 — 2026-11-07

- OpenCode T1 live: `--session`, `--format json`, cost from session export.
- Cost guard (`--max-cost`).
- Daemon: `start --detach`, `stop`, loopback `serve`.
- Skill installers for OpenCode / Claude / Gemini / generic.
- Windows process-tree kill (Job Object + `taskkill /T /F`) and live freeze probe.

## v0.1.0 — 2026-11-07

- Deterministic 4-bucket planner + contract lint.
- State, ledger, append-only events, git checkpoints.
- Evidence gates: scope diff, verify exit code, test hash (TAMPER).
- Pure detector and the wake loop.
- Markdown status + Rich watch.
- Fake agents (lazy / liar / tamper / freeze / blocked) and 60 tests.
