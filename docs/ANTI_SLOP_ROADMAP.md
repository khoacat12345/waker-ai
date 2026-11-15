# Waker Anti-Slop Guardian — Phased Implementation Plan

**Status:** proposed — waiting for approval
**Baseline:** waker-ai v1.2.0
**Target:** v1.3.0 (opt-in preview) → v2.0.0 (default-on)
**Design:** [`docs/ANTI_SLOP_SPEC.md`](ANTI_SLOP_SPEC.md)
**Implementation plan:** [`docs/ANTI_SLOP_ROADMAP.md`](ANTI_SLOP_ROADMAP.md)
**Reference repos:** `C:\Users\tuank\anti-slop-refs` (review-only, outside this repo)

---

## 0. Rules of engagement

1. **No code from reference repos is copied.** Ideas and rule names are used
   with attribution; implementations are written from scratch for Waker.
2. **No new runtime dependency.** `waker.gate` uses only the Python standard
   library; Rich stays in the CLI layer.
3. **No LLM in the gate.** Deterministic AST facts only. Optional mutation/
   coverage/type checks are explicit contract commands.
4. **No breaking v1 contracts.** v1.3 is opt-in and default-off; v2.0 accepts
   both schema v1 and v2.
5. **No destructive default.** `on_violation: kick` is the default; `revert`
   and `abort` are explicit policies.
6. **Every phase ends with tests, docs, a separate commit, and a review
   checkpoint.** No release until the user says so.

---

## 1. What we are building (scope)

```
Phase 1-3: passive gate + `waker audit` (safe, read-only)
Phase 4-5: active enforcement in the run loop (SLOP → kick/rollback)
Phase 6:   v1.3.0 opt-in release
Phase 7:   v2.0.0 default-on + migration
```

Gate families:

| Family | Rules | Default in v1.3 | Default in v2.0 |
|---|---|---|---|
| Core anti-slop | `SLOP001–008` | off (opt-in) | on (new contracts) |
| Test integrity | `TEST001–008` | warn | on |
| Type evidence | `TYPE001–012` | warn | on for new/changed |
| Comments/suppression | `COMMENT/SUPPRESS/STUB` | warn | warn/on for placeholders |
| Architecture | `ARCH001–004` | off | on |
| Dead code | `DEAD001–004` | off | on (private-only) |
| Dependencies | `PKG001–004` | off | on (`allow_new: false`) |
| Security | `SEC001–007` | off | on |
| Resource/API/async/coupling | `RES/API/ASYNC/COUPLE` | off | warn |

---

## 2. Reference intelligence — what to borrow, not copy

| Source | What we take | What we do not take |
|---|---|---|
| `dmmulroy/anti-slop` (TypeScript) | Type-evidence rules: `Any`/unknown params/returns, chained assertions, widen-then-assert, safety comments; vendored/opinionated rule philosophy | Oxlint dependency, TS parser, Effect-specific rules |
| `TinyFrontier/anti-slop-py` (Python, zero-dep) | AST + `tokenize` + local scope table; 15 evidence rules; baseline/diff/review; diagnostics that end with a recipe | Its exact code, vendoring installer, FastAPI group (optional later) |
| `scanaislop/aislop` | UX: score, CI/SARIF, GitHub Action, editor/agent hook, agent repair; broad rule vocabulary | 12-language core, Node runtime, auto-fix in the safety-critical gate |
| `dannote/sloplint` | Comment slop rules (obvious/narrator/step/section/placeholder/apologetic), empty-error-handler | ast-grep dependency, multilingual core |
| `import-linter` / `pyscythe` / `layerguard` | Layer direction, cycles, fan-in/out, baseline | Their graph code |
| `vulture` / `pyscythe dead-code` | Confidence tiers, framework/entry-point/`.pyi` exemptions | Auto-delete |
| `deptry` / `pip-audit` | Import↔distribution mapping, manifest diff, allowlist | Mandatory network/audits in core |
| Bandit / Semgrep / Ruff `S` | High-confidence security patterns | Full security scanner scope |
| `pytest-review` / `exspec` / `falsegreen` / `vacuous` / `testrot` / `pragma` | Structural false-green test rules; confidence | "Mock ratio is a defect"; LLM judge |
| `mutmut` / `cosmic-ray` / `coverage.py` | Optional proof commands | Bundling them as dependencies |

**The one-line thesis shared by all of them:** prompt instructions
(`CLAUDE.md`/`PROMPT.md`) do not survive a few turns; a **deterministic gate at
the exit** does. Waker adds the missing piece: an **active kick/rollback loop**
instead of a passive red line.

---

## 3. Phases

### Phase 0 — Freeze the contract (0.5–1 session)

**Goal:** agree on rule IDs, severity, schema, diagnostics, and non-goals before
writing production code.

Deliverables:

- `docs/ANTI_SLOP_SPEC.md` (already written; update as decisions land).
- `docs/ANTI_SLOP_ROADMAP.md` (this file).
- `tests/fixtures/anti_slop/` and `tests/fixtures/guardians/` fixture layout:
  clean, core slop, test slop, type slop, layer inversion, dead code,
  dependency violation, security violation, comment slop.
- A written decision log (section 8 below).

Tests/exit:

- Fixtures reviewed; no production behavior change.
- `pytest` still green (1 Windows-only skip).
- No new dependencies.

**Checkpoint:** user approves rule catalog + thresholds.

---

### Phase 1 — `waker.gate` core + `waker audit` (2–3 sessions)

**Goal:** a fast, deterministic, read-only Python AST gate that is useful on its
own and cannot affect `waker run`.

Deliverables:

```
src/waker/gate/
  __init__.py
  model.py          # Finding, ScanResult, FamilySummary
  config.py         # AntiSlopConfig, GatesConfig, validation
  scanner.py        # scan_paths, scan_diff, parse/traverse
  cache.py          # content-hash + config-hash cache
  baseline.py       # load/write/fingerprints (skeleton)
  rules/
    duplicates.py   # SLOP001, SLOP006
    exceptions.py   # SLOP002
    complexity.py   # SLOP003, SLOP004, SLOP005, SLOP008
    growth.py       # SLOP007
```

CLI:

```bash
waker audit [--anti-slop] [--changed-only|--all]
            [--baseline <rev>] [--format md|json] [--strict]
```

- `waker audit` is read-only; no `waker run` changes.
- JSON shape is stable; Markdown has code frames.
- Exit codes: 0 clean/warn-only, 2 blocking findings, 1 scan error, 3 config.
- `.waker/quality-cache.json` is ignored; no baseline writes yet.

Tests:

- Unit per rule; line/column/fingerprint stability.
- Clean vs slop fixtures; false-positive fixtures (`@overload`, property
  setters, conditional definitions, generated/test exclusions).
- No network; no new dependencies; Windows/Linux.

**Checkpoint:** review `waker audit` output before engine integration.

---

### Phase 2 — Test, type, and comment guards (2–3 sessions)

**Goal:** add the highest-value AI-slop families that do not need a full
project graph.

Deliverables:

- `rules/tests.py` — `TEST001–008`:
  no assertion, tautology, mock-the-SUT, uncalled mock assertion, swallowed
  assertion, unconditional skip/xfail, mock-ratio **warning**, orphan test.
- `rules/types.py` — `TYPE001–012`:
  `Any`/`object` params/returns, `Any` aliases, chained casts, widen-then-cast,
  ad-hoc `isinstance`, cast without safety comment, unexplained
  `# type: ignore`, string attribute access, unsafe dict values.
- `rules/comments.py` — `COMMENT001–004`, `SUPPRESS001–002`, `STUB001`:
  obvious/narrator/step/section/placeholder/apologetic comments, TODO policy,
  unexplained/blanket suppression, stub bodies.
- Suppression parser:
  `# waker: ignore[RULE] reason="..."` (required reason; rule ID required).
- Fixtures for real/property-based tests, `TypeGuard`/boundary parsing, valid
  why-comments, valid suppressions, legacy `Any` baseline.

CLI:

```bash
waker audit --tests --types --comments
waker audit --gates test_integrity,type_evidence,comments
```

Tests:

- Each rule positive/negative; false-positive matrix.
- Mock-ratio warning never exits 2.
- Type/comment rules only new/changed when `new_code_only: true`.
- JSON family/severity/confidence fields.

**Checkpoint:** review false-positive rate on the Waker repo itself and on
`anti-slop-refs`; aim for zero false positives on clean fixtures.

---

### Phase 3 — Architecture, dead code, dependencies, security (3–4 sessions)

**Goal:** complete the passive gate set and add SARIF/CI output.

Deliverables:

- `graph.py` — module graph, relative imports, `TYPE_CHECKING` edges, Tarjan
  SCC, fan-in/out.
- `rules/architecture.py` — `ARCH001–004` (layer inversion, cycles, fan-out,
  dynamic import warning).
- `symbols.py` + `rules/dead_code.py` — `DEAD001–004` with confidence,
  private-only, framework/entry-point/`__all__`/`.pyi`/`globals()` exemptions.
- `manifests.py` + `rules/dependencies.py` — stdlib/first-party/allowlist,
  `importlib.metadata.packages_distributions()`, requirements/pyproject diff,
  pinning, optional PyPI lookup (off by default).
- `rules/security.py` — `SEC001–007` with secret redaction.
- `rules/resources.py` — `RES/API/ASYNC/COUPLE` warnings.
- `sarif.py` — SARIF 2.1.0.
- `waker gate rules|explain|baseline status`.

Tests:

- Core→UI import rejected; cycle rejected; `TYPE_CHECKING` false positive
  allowed.
- Private dead function rejected; public API/framework hook not; unused import
  exemptions.
- `yaml` → PyYAML mapping; blocked package; manifest diff; offline mode.
- Secret redaction; test fixture `eval` suppression.
- 200-file diff under soft budget; `--all` on 2,000 files.
- No network by default; no code execution; symlink escape blocked.

**Checkpoint:** review full gate report; decide which families are blocking vs
warning for v2 defaults.

---

### Phase 4 — Engine enforcement and wake loop (3–4 sessions)

**Goal:** turn the passive audit into Waker’s active watchdog. This is the
differentiator no reference linter has.

Deliverables:

- `models.Diagnosis.SLOP` (umbrella) and `Observation` fields:
  `slop_ok`, `slop_findings`, `slop_blocking`, `slop_warnings`,
  `slop_hash`, `quality_families`, `quality_abort`.
- `Engine._observe()`: run gate on `changed_files` only; cache by file/config
  hash; scanner errors are non-fatal.
- `detector.diagnose()`: gate order:
  tamper/vault → blocked → frozen → security → hidden/verify → test/type/arch/
  dead/deps/slop → DONE. Exact order documented in the spec; `DONE` requires
  `slop_ok`.
- `injector.build_wake_prompt()`: grouped findings, max 10, each with rule,
  `file:line`, problem, recipe. No hidden-test source/path leakage.
- Ledger/events/report:
  `quality` summary, per-family counts, fingerprints, config hash.
- UI:
  `waker status --format json` quality block;
  `waker watch` quality row;
  `waker report` Quality Gate section.
- Default policy: `on_violation: kick`; no revert yet.

Tests:

- Fake agent writes slop at kick 0 → `SLOP`; fixes it at kick 1 → `DONE`.
- `DONE` never when a blocking family is red.
- `TAMPER` still outranks `DONE`; hidden failure still outranks quality.
- Wake prompt contains recipes and no hidden source.
- v1.2 behavior unchanged when gates are disabled.
- Full suite green; no false `TAMPER` from the gate cache.

**Checkpoint:** review a real terminal kick; approve before rollback code.

---

### Phase 5 — Policies, baseline, rollback, and TUI (2–3 sessions)

**Goal:** make adoption safe on legacy repos and add controlled enforcement.

Deliverables:

- `on_violation` per family: `kick` (default), `revert` (file-scoped restore
  from pre-turn checkpoint), `abort` (terminal `SLOP`, exit 6).
- `revert.py`: `git restore --source=<checkpoint> --staged --worktree -- <paths>`;
  untracked files removed only inside repo, no symlinks; never
  `git reset --hard`; event `slop_revert`; re-scan after revert.
- Baseline:
  - `.waker/anti-slop-baseline.json` committed (add a `.gitignore` exception).
  - `waker audit --write-baseline`; stale fingerprint handling.
  - Only new/changed findings block.
- Suppression hygiene: unused suppression warning; `--strict` can fail.
- TUI: code frames, family colors, `quality: N errors · M warnings`.
- Docs: onboarding, baseline, suppression, exit codes, config reference.

Tests:

- Revert preserves unrelated files; untracked-file safety; abort exit 6.
- Baseline suppresses legacy; new violation blocks.
- Windows/Linux, cp1252 fallback, no console windows.
- Full E2E with fake agent and hidden vault.

**Checkpoint:** full acceptance; user approves v1.3 release.

---

### Phase 6 — v1.3.0 opt-in release (1 session)

**Goal:** ship the gate as a safe preview.

- Version bump `1.2.0 → 1.3.0`.
- CHANGELOG + release notes + Agensi zip.
- Build wheel/sdist; twine check; fresh-venv install.
- Tag/GitHub release/PyPI; verify workflow and PyPI JSON.
- Gates default **off**; `waker audit` always available.
- Update notifier already shipped in v1.2.0; no new mechanism.
- Announce only after tests/publish are verified.

**Checkpoint:** user approval before release.

---

### Phase 7 — v2.0.0 default-on + migration (2–3 sessions)

**Goal:** make the Guardian the default for new contracts without breaking v1.

- Schema v2 `gates` canonical; top-level `anti_slop` alias.
- New `version: 2` contracts: gates on; v1 contracts: warn/migration hint.
- Defaults: certain rules block; likely rules warn; baseline required for
  adoption.
- `waker lint` migration diagnostics; `waker doctor` gate status.
- Migration guide + example contracts.
- v2.0 release, then optional v2.1: JS/TS adapter, score/badge, hunk-level
  revert, mutation/coverage adapters.
- **Not core:** auto-fix, auto-delete, LLM judge, 12-language parser.

**Checkpoint:** user approval before v2.0 release.

---

## 4. Test strategy (all phases)

| Layer | Tests |
|---|---|
| Unit | each rule; line/col/fingerprint; severity; config; suppression |
| Fixtures | clean, core slop, test slop, type slop, layers, dead code, deps, security, comments |
| False positives | overloads, property setters, `TYPE_CHECKING`, framework hooks, public API, valid mocks, why-comments |
| Engine | kick loop, DONE gating, hidden/tamper priority, wake prompt, revert/abort |
| CLI | exit codes, JSON schema, SARIF, TTY vs pipe, `--strict`, `--all`, `--gates` |
| Performance | 200-file diff < 500 ms; cache hit avoids parse; `--all` 2,000 files |
| Cross-platform | Windows/Linux; UTF-8/cp1252; no console windows |
| Security | symlink escape, huge file, invalid syntax, non-UTF8, no execution, secret redaction |

**Definition of done for every phase:**

- New tests pass; full suite green.
- No new runtime dependency.
- Docs updated.
- One commit per phase (or a small commit series); no release.
- A short phase report with evidence (command + output).

---

## 5. Commit and release discipline

- Branch per phase if the user prefers; otherwise `main` with separate commits.
- Never mix gate code with engine enforcement in one commit.
- `problem.md` gets a P-entry for any deferred bug/known limitation.
- Release only after explicit user approval; v1.3.0 opt-in first.
- Keep the current v1.2.0 working while the gate is developed.

---

## 6. Effort and checkpoints

| Phase | Effort (sessions) | User checkpoint |
|---|---:|---|
| 0 | 0.5–1 | rule catalog/thresholds |
| 1 | 2–3 | audit UX |
| 2 | 2–3 | false-positive review |
| 3 | 3–4 | gate set/severity |
| 4 | 3–4 | kick prompt |
| 5 | 2–3 | rollback/baseline |
| 6 | 1 | v1.3 release |
| 7 | 2–3 | v2.0 release |

Estimates are relative coding sessions, not calendar promises.

---

## 7. Open decisions (need user approval)

1. **v1.3 opt-in vs single v2.0 release.** Recommended: v1.3 opt-in, then v2.0.
2. **Default v2 gate set.** Recommended: core + test + type + architecture +
   dead code + dependencies + security; comments warnings; resource/API/async/
   coupling warnings.
3. **Thresholds.** 100 function lines, 1000 module lines, complexity 15,
   mock ratio 0.70 warning, growth 15% + 30 lines.
4. **Rollback default.** `kick`; `revert`/`abort` opt-in.
5. **Python-only core.** Recommended; JS/TS via optional adapter later.
6. **Baseline file.** Commit `.waker/anti-slop-baseline.json`; cache stays
   ignored.
7. **Comment rules default.** Warnings, except placeholder comments and
   unexplained suppressions.
8. **Score/badge/auto-fix.** Defer to v2.1; do not put in the safety-critical
   gate.

---

## 8. Immediate next step (only after the user says go)

Phase 0: create fixtures and freeze the rule catalog. No production code.
Then Phase 1: `waker.gate` core + `waker audit` read-only.

**Waiting for the command.**
