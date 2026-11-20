# Changelog

All notable changes to `waker-ai`.

## v2.2.0 — 2026-11-20

**Chatbox-first Grill-Me, timeout profiles and phase budget display.**

This release makes Waker easier to use from a chatbox and gives large projects
time budgets that fit the work instead of the old 90-minute ceiling.

### Added

- **Conditional Grill-Me** in the `waker` skill. Clear prompts silent-pass with
  zero questions; vague prompts get at most three blocking questions in one
  round. No preference interrogation and no invented scope/verify.
- **Chatbox phase flow**: `waker plan --phases none|manual|auto`, phase table
  review, natural-language budget edits, `ok` / `1` / `chạy` approval and a
  small-task fast path. No raw terminal key reads in chatbox/non-TTY mode.
- **Phase contract schema**: top-level `phases` (`id`, `name`, `budget`) and
  task `phase` are parsed, validated and round-tripped with backward-compatible
  `P1` defaulting for legacy YAML.
- **Timeout profiles**: `small`, `medium`, `large`, `overnight`; `--profile`
  on `run`/`start`; explicit timeout flags still take precedence.
- **`TIMEOUT` diagnosis** (exit 7) for turn or wall-clock exhaustion, separate
  from `BREAKER` (kick/cost limits). `FROZEN` remains its own diagnosis.
- **Timeout telemetry**: all four values (`turn_timeout`, `max_wall_clock`,
  `verify_timeout`, `freeze_after`) persist in `run.json`, events and
  `waker status --format json`; verify/test timeouts are recorded separately.
- **Phase display** on the Cyber-Deck:
  `PHASE n/N  <name>  elapsed / budget  [########--]`, with green/yellow/red
  thresholds at 80% and 95% of the phase budget.

### Changed

- `waker plan` now supports `--phases`, `--profile` and machine-readable
  `--json` phase data.
- `waker status` markdown shows the four timeout values.
- Legacy contracts without `phases` continue to run with implicit `P1`.
- Large and overnight profiles use 5h and 8h wall clocks respectively instead
  of the old 90-minute default.

### Fixed

- **Completed-run Cyber-Deck:** `waker watch` now renders a completed, failed or
  blocked run as a static deck in the normal terminal buffer instead of using
  the alternate screen and erasing it immediately. Live runs still use
  `Live(screen=True)`.
- **`waker watch --window` lifecycle:** the child window now receives `--hold`,
  the launcher uses `start /wait`, and the `watch.window` marker stores
  `{pid, started}` JSON. A dead/stale PID is cleaned automatically; a live
  window still blocks duplicate opens.

### Deferred to v2.3.0

- Hard phase-budget enforcement and automatic phase transitions.
- `resume --extend`, historical budget suggestions.
- Code-enforced `waker grill` / `questions.yaml` if the instruction-only gate
  is not sufficient.

### Verification

- Full pytest suite: **336 collected, 335 passed, 1 skipped**, zero failures.
  The skip is the opt-in real-OpenCode E2E test.
- `python -m build`: `waker_ai-2.2.0.tar.gz` + wheel.
- `twine check dist/waker_ai-2.2.0*`: both **PASSED**.
- `waker.__version__` reports `2.2.0`.

## v2.0.0 — 2026-11-16

**Waker Anti-Slop AI Code Guardian (default-on).**

This is a major release: every `waker run` now treats deterministic AST
quality as part of the completion contract. The agent must leave the changed
files clean, not merely claim that tests pass.

### Added

- **Anti-slop gate** (`waker.gate`): read-only Python AST checks with stable
  fingerprints, line/column evidence, severity, confidence, score, grade and
  Markdown badge.
- **Core anti-slop rules** (`SLOP000–008`): duplicate symbols, silent broad
  exceptions, cyclomatic complexity, function/module length, copy-paste blocks,
  file growth, nesting and parameter warnings.
- **Test integrity rules** (`TEST001–008`): no-assert tests, tautologies,
  mocking the SUT, uncalled mock assertions, swallowed assertions,
  unconditional skip/xfail, mock-ratio warnings and orphan tests.
- **Type evidence rules** (`TYPE001–012`): unjustified `Any` parameters and
  returns, `Any` aliases, chained casts, widen-then-cast, ad-hoc
  `isinstance`, unexplained `# type: ignore`, string attribute access and
  unsafe dictionary values.
- **Comment/suppression/stub rules** (`COMMENT001–004`, `SUPPRESS001–002`,
  `STUB001`): narrator/step/placeholder comments, unexplained suppressions
  and placeholder-only function bodies.
- **Architecture rules** (`ARCH001–004`): module graph, relative imports,
  `TYPE_CHECKING` edges, Tarjan SCC import cycles, layer inversion, fan-out
  and non-static dynamic imports.
- **Dead-code rules** (`DEAD001–004`): unused private/public symbols and
  imports, with `__all__`, pytest hooks, framework hooks and pyproject entry
  points exempted where appropriate.
- **Dependency rules** (`PKG001–004`): stdlib/first-party detection through
  `sys.stdlib_module_names` and `importlib.metadata.packages_distributions()`,
  allowlists, new-dependency checks, pinning warnings and import/distribution
  mapping warnings.
- **Security rules** (`SEC001–007`): `eval`/`exec`, unsafe pickle/marshal,
  `shell=True`, unsafe `yaml.load`, disabled TLS verification, hardcoded
  secrets (redacted in output) and SQL string interpolation.
- **SARIF 2.1.0 export**: `waker audit --format sarif`, suitable for GitHub
  Advanced Security and other CI consumers.
- **Baseline support**: `.waker/anti-slop-baseline.json` stores legacy debt.
  The engine also snapshots pre-run findings, so changing an old file does not
  inherit all of its historical violations; newly introduced findings still
  block. Stable keys survive line shifts without hiding a second finding in the
  same file.
- **Engine enforcement**: `Diagnosis.SLOP`, `Observation.slop_ok`,
  `Observation.slop_findings`, `Observation.slop_blocking`; blocking findings
  deny `DONE` and generate a wake prompt with rule ID, file, line, message and
  repair recipe.
- **Violation policies**: `kick` (default), `revert` and `abort`.
  `revert` restores only violating paths from the pre-turn checkpoint and never
  runs `git reset --hard`; unrelated work is preserved. `abort` terminates with
  exit code `6`.
- **Quality display**: Rich TUI status bar and Markdown/JSON quality block with
  Cleanliness Score, grade, errors and warnings.
- **CLI expansion**: `waker audit --arch --dead-code --deps --security`,
  `--all-gates`, `--baseline`, `--baseline-file`, `--no-baseline`,
  `--write-baseline`, `--format sarif`, and per-run `waker run --baseline` /
  `--no-baseline`.

### Changed

- **Anti-Slop is default-on** for new runs: the engine enables core, tests,
  types, comments, architecture, dead code, dependencies and security checks.
  Set `EngineConfig(anti_slop=False)` or use the CLI opt-out for legacy
  behavior.
- Calibration: `TYPE006`, `TYPE009`, `TYPE010`, `TYPE011` and `TYPE012` are
  warnings; `TYPE001–005` and `TYPE007–008` remain blocking errors.
- Cleanliness Score and badge are now part of `waker audit` output, JSON and
  the printable report.
- `waker status --format json` includes the latest `quality` block; `waker
  watch` and `waker report` show the quality line.

### Migration

- Users who need the old behavior can pin `waker-ai==1.2.0` or disable the
  anti-slop watchdog.
- For legacy repositories, run `waker audit --write-baseline` once, commit
  `.waker/anti-slop-baseline.json`, then use `waker audit` normally. Only new
  findings should block.
- Suppressions use `# waker: ignore[RULE] reason="..."`; a reason and rule ID
  are required.

### Tests and packaging

- Full pytest suite green (1 Windows-only skip); zero new runtime
  dependencies beyond the existing `pyyaml` and `rich` dependencies.
- `python -m build` and `twine check dist/*` are part of the release gate.
- Python standard library is used for all gate logic; TypeScript/JavaScript is
  a future external adapter. Auto-fix is deferred to v2.1.


## v1.2.0 — 2026-11-15

### Added

- Non-blocking PyPI update notifier: reads a 6-hour cache, refreshes it in a
  daemon thread, and prints a yellow banner on interactive terminals when a
  newer version exists. Disabled in CI, with `WAKER_UPDATE_CHECK=0`, or
  `NO_UPDATE_NOTIFIER`; no telemetry.
- ASCII fallback for legacy Windows consoles.

### Tests

- Full suite green (1 Windows-only skip).

## v1.1.3 — 2026-11-10

### Changed

- `waker setup` now prints the live progress hint: `waker watch` (terminal) or
  ask "progress" in chat. `waker start` prints the same live-view command.
- Skill templates (OpenCode / Claude / Gemini / generic) now require the agent
  to say after starting a run: "Running in the background. Ask me for progress
  in chat, or run `waker watch --repo .` for the live view." While a run is
  active, the agent runs `waker status --format md` and pastes the table on
  every user message.
- English is now the default for all user-facing output: CLI help/messages,
  `waker watch` / `status` / `report`, kick/initial prompts, vault/lint/doctor
  output, and skill templates. Vietnamese input parsing remains supported.

### Tests

- Full suite green (1 Windows-only skip).

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

- **Skill UX**: never asks "OK to run?" when lint has errors. It now shows the
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
