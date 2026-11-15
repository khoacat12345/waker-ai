# Waker Anti-Slop AI Code Guardian — Architecture & Feature Specification

**Status:** proposed (design)
**Target:** v2.0.0 (opt-in preview in v1.3.0)
**Owner:** Waker maintainers
**Scope:** Python AST quality gate for AI-generated code, contract schema,
engine enforcement, CLI diagnostics, packaging, migration.
**Non-goals:** replacing pytest/ruff/mypy; auto-rewriting code; full JS/TS AST
support; LLM-based style judgement; runtime profiling.

> **Version note.** The current stable release is **v1.2.0** (2026-11-15). The
> old `v0.3.0 -> v1.0.0` roadmap is historical; publishing v1.0.0 after v1.2.0
> would be a downgrade. This spec therefore targets **v2.0.0** as the major
> release, with an opt-in **v1.3.0** preview. If only one release is desired,
> ship v2.0.0.

---

## 1. Executive summary

Waker already wins by refusing to trust an agent's words: it checks
`git diff ∩ scope`, public `verify`, and optional hidden tests. The next gap is
**code quality that still passes tests**: duplicated symbols, copy-pasted
blocks, god functions, silent `except: pass`, and runaway file growth.

The Anti-Slop Guardian adds a deterministic, stdlib-only AST gate:

```
turn ends
  -> changed files
  -> anti-slop scan (changed files only, cached)
  -> tamper / hidden / public verify / quality
  -> diagnose: SLOP | HIDDEN_FAIL | FALSE_DONE | DONE ...
  -> kick with precise findings, or rollback/abort if configured
```

Design principles:

1. **Mechanical, not vibes.** Every finding is an AST fact with a rule ID,
   file, line, column, and fingerprint. No model judges quality.
2. **Fail closed on new slop, never on legacy noise.** Baseline-first; only
   new/changed violations block.
3. **Do not destroy valid work.** Default is `kick` (reject the turn and wake
   the agent with findings); `revert` is opt-in and file-scoped; `abort` is
   explicit.
4. **Zero new dependencies.** `ast`, `tokenize`, `symtable`, `hashlib`,
   `json`, `pathlib`, `concurrent.futures`.
5. **Fast.** Changed Python files only + content-hash cache; budget < 300 ms
   for a typical diff; degrade gracefully, never block the run on a scan bug.

---

## 2. Slop taxonomy and rule catalog

| ID | Rule | Default | Blocking |
|---|---|---:|---:|
| `SLOP001` | Duplicate symbol in the same scope | on | yes |
| `SLOP002` | Silent / broad exception handler | on | yes |
| `SLOP003` | Cyclomatic complexity above limit | 15 | yes |
| `SLOP004` | Function longer than limit | 100 logical lines | yes |
| `SLOP005` | Module longer than limit | 1000 logical lines | yes |
| `SLOP006` | Copy-pasted block across files | 20 lines / 8 statements | yes |
| `SLOP007` | File growth above baseline | +15% and +30 lines | warn |
| `SLOP008` | Deep nesting / too many parameters | depth 5 / 8 params | warn |

Severity is configurable (`error` / `warning` / `off`). `--strict` makes
warnings fail `waker audit`.

### 2.1 AST nodes to traverse

| Node | Used for |
|---|---|
| `Module` | module LOC, top-level definitions, copy-paste blocks |
| `FunctionDef`, `AsyncFunctionDef` | name, args, body, decorators, complexity, LOC, nesting |
| `ClassDef` | method duplicate detection, class LOC/nesting |
| `ExceptHandler` | silent/broad exception detection |
| `If`, `For`, `AsyncFor`, `While` | complexity, nesting, branch scope |
| `Match`, `match_case` | complexity |
| `comprehension` | complexity (generators/conditions) |
| `BoolOp` | complexity (`and`/`or` operands) |
| `IfExp` | complexity |
| `Try`, `With`, `AsyncWith` | scope/context; not complexity by default |
| `Call`, `Attribute` | optional broad-suppress detection (`contextlib.suppress`) |
| `Assign`, `AnnAssign`, `Import`, `ImportFrom` | duplicate/shadow symbols and re-export guards |
| `Lambda` | ignored by default; optional complexity |
| `Global`, `Nonlocal` | scope-aware duplicate detection |
| `Return`, `Yield` | optional returns/limits |

`ast.parse(..., type_comments=True)`; `tokenize` for logical line counting;
`symtable` as a scope cross-check where AST parent links are ambiguous.

---

## 3. `waker.gate` package

```
src/waker/gate/
  __init__.py          # public API: AntiSlopConfig, Finding, scan_paths, scan_diff
  model.py             # Finding, ScanResult, Rule, Severity
  config.py            # validation, defaults, YAML dict -> AntiSlopConfig
  scanner.py           # parsing, traversal, per-file orchestration
  rules/
    duplicates.py      # SLOP001, SLOP006
    exceptions.py      # SLOP002
    complexity.py      # SLOP003, SLOP004, SLOP005, SLOP008
    growth.py          # SLOP007
  baseline.py          # fingerprints, .waker/anti-slop-baseline.json
  sarif.py             # SARIF 2.1.0 output
  cache.py             # content-hash + config-hash cache
  revert.py            # opt-in file-scoped restore (uses waker.winproc/git)
```

The gate core imports **only the standard library**. Rich is used by the CLI
layer, never by `waker.gate`.

### 3.1 Core types

```python
# waker/gate/model.py
@dataclass(frozen=True)
class Finding:
    rule: str                 # SLOP001 ...
    severity: str             # error | warning
    path: str                 # repo-relative, forward slashes
    line: int
    col: int
    end_line: int | None
    message: str
    suggestion: str
    fingerprint: str          # stable, path+rule+normalized snippet
    symbol: str | None = None

@dataclass
class ScanResult:
    findings: list[Finding]
    files_scanned: int
    files_skipped: int
    duration_ms: int
    errors: list[str]         # parse/cache errors; never raise to the engine
```

```python
# waker/gate/config.py
@dataclass(frozen=True)
class AntiSlopConfig:
    enabled: bool = False                 # v1.3 preview: opt-in; v2: default on
    max_function_lines: int = 100
    max_module_lines: int = 1000
    max_cyclomatic_complexity: int = 15
    max_nesting_depth: int = 5
    max_parameters: int = 8
    ban_broad_except: bool = True
    ban_silent_except: bool = True
    ban_duplicate_symbols: bool = True
    duplicate_block_min_lines: int = 20
    duplicate_block_min_statements: int = 8
    track_file_growth: float = 0.15       # 15%
    growth_min_lines: int = 30
    paths: tuple[str, ...] = ("**/*.py",)
    exclude: tuple[str, ...] = (
        ".venv/**", "venv/**", "build/**", "dist/**",
        "**/__pycache__/**", "**/node_modules/**",
        "tests/**", "**/test_*.py", "**/*_test.py",
        "**/migrations/**", "**/generated/**",
    )
    on_violation: str = "kick"            # kick | revert | abort
    baseline: str = "auto"                # auto | path | off
    changed_only: bool = True
    allow: tuple[str, ...] = ()            # path globs exempt from all rules
```

Validation rules: non-negative numbers; `0 < track_file_growth < 1`;
`on_violation in {kick, revert, abort}`; unknown keys are errors in `lint`,
warnings in `audit`; all path globs normalized.

---

## 4. Rule implementations

### 4.1 SLOP001 — duplicate symbol

Collect definitions with a scope stack:

```python
Definition(scope=("module",), name="parse", kind="function", node=..., line=...)
Definition(scope=("module","Parser"), name="parse", kind="method", ...)
```

Flag when the same `(scope, name)` is defined more than once in a module.

Implementation notes:

- Use `ast` parent/scope traversal; `symtable` to confirm local/global names.
- Include `def`, `async def`, `class`; optionally `Assign`/`AnnAssign` for
  top-level constants (off by default; too noisy).
- Exemptions:
  - `@typing.overload` overload sets.
  - `@property` / `@x.setter` / `@x.deleter` groups.
  - Definitions in mutually exclusive `if TYPE_CHECKING` / `if sys.platform`
    branches (scope path includes the branch predicate; compare only within the
    same branch unless `cross_branch_duplicates: true`).
  - `try/except ImportError` fallback definitions.
  - `.pyi` stubs and generated files (excluded by default).
  - Explicit `# waker: ignore[SLOP001] reason="..."`.
- Message example:
  `"Function 'parse' is defined twice in module scope (first at line 12)."`
- Suggestion: merge/rename; if intentional, add a suppression with a reason.

### 4.2 SLOP006 — copy-pasted blocks

Two-tier detection:

1. **Exact normalized fingerprints**: for each function/block with at least
   `duplicate_block_min_statements`, serialize statements with
   `ast.dump(stmt, annotate_fields=False, include_attributes=False)` and hash
   with `hashlib.blake2b(digest_size=16)`. Group identical hashes across files.
2. **Near-duplicate**: for blocks ≥ `duplicate_block_min_lines`, compare
   token/statement sequences with `difflib.SequenceMatcher` (ratio ≥ 0.85);
   cap comparisons (e.g., 5,000 pairs) to avoid O(n²).

Exclude:

- imports, `__all__`, license headers, simple dataclasses, pytest fixtures,
  generated bindings, migrations, tests (by default);
- blocks smaller than the thresholds;
- exact matches that are a single expression/constant.

Finding reports both locations and a shared fingerprint so a baseline entry
suppresses the pair, not one side.

### 4.3 SLOP002 — silent exception quarantine

For every `ExceptHandler`:

```python
broad = handler.type is None or _is_broad(handler.type)
silent = all(_is_noop(stmt) for stmt in handler.body)

def _is_noop(stmt):
    return (
        isinstance(stmt, (ast.Pass, ast.Continue, ast.Break))
        or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis)
        or (isinstance(stmt, ast.Return) and stmt.value is None)
    )
```

Flag:

- `broad and silent` → `SLOP002` **error** (default).
- `broad and not silent` → warning if `ban_broad_except` and the handler only
  logs/prints without re-raising (configurable; default **off** to avoid
  punishing legitimate logging).
- `narrow and silent` → warning if `ban_silent_except` (default on for empty
  handlers; `except FileNotFoundError: pass` is often legitimate; allow via
  config/suppression).

Broad types: bare `except:`, `Exception`, `BaseException`,
`BaseExceptionGroup`; `except (ValueError, Exception)` is broad if any member
is broad.

Allow:

- `try: import optional_dep` + `except ImportError: pass` when
  `allow_optional_imports: true` (default true? choose **false** for v2,
  explicit suppression is better).
- explicit `# waker: ignore[SLOP002] reason="..."`.
- handlers that `raise`, `raise ... from`, call `.exception()/.error()` with
  context, or assign to a visible error state (not just `pass`).

### 4.4 SLOP003–005, SLOP008 — complexity and bloat

Cyclomatic complexity per function/async function:

```
1
+ If / IfExp
+ For / AsyncFor / While
+ ExceptHandler
+ match_case
+ each comprehension generator and each `if` in a comprehension
+ (BoolOp operands - 1) for and/or
```

Not counted: `else`, `finally`, `with` (unless configured), `assert`, decorators.

Line counting via `tokenize`:

- **function logical lines**: body lines from `node.body[0].lineno` to
  `node.end_lineno`, excluding blank lines, comments, and the function
  docstring. Decorators and `def` header excluded.
- **module logical lines**: same, whole file; shebang/encoding/comments
  excluded.
- Also report physical lines in JSON for transparency.

Defaults:

| Limit | Default | Severity |
|---|---:|---|
| `max_function_lines` | 100 | error |
| `max_module_lines` | 1000 | error |
| `max_cyclomatic_complexity` | 15 | error |
| `max_nesting_depth` | 5 | warning |
| `max_parameters` | 8 | warning |

`SLOP007` growth:

- Compare current file logical lines to the baseline blob
  (`git show <baseline>:path`, or the pre-turn checkpoint for new files).
- Flag when `delta >= growth_min_lines` **and**
  `delta / max(baseline_lines, 1) >= track_file_growth`.
- New files: compare against `max_module_lines` (not growth).
- Deleted files: no finding.
- Default warning; configurable to error.

---

## 5. Contract schema (v2, backward compatible in v1.3)

### 5.1 Recommended YAML

```yaml
version: 2

anti_slop:
  enabled: true
  max_function_lines: 100
  max_module_lines: 1000
  max_cyclomatic_complexity: 15
  ban_broad_except: true
  ban_silent_except: true
  ban_duplicate_symbols: true
  duplicate_block_min_lines: 20
  track_file_growth: 0.15
  growth_min_lines: 30
  paths: ["src/**/*.py", "waker/**/*.py"]
  exclude: ["tests/**", "**/generated/**", "**/migrations/**"]
  on_violation: kick
  baseline: auto
  changed_only: true

tasks:
  - id: T1
    desc: "Add auth guard"
    scope: ["src/auth/**"]
    verify: "pytest tests/auth -q"
    anti_slop:
      max_function_lines: 80        # per-task override
      severity: error

constraints:
  - id: C-SLOP
    kind: anti_slop
    desc: "No AI slop"
    anti_slop:
      ban_broad_except: true
      ban_duplicate_symbols: true
```

The existing `constraints` form remains valid:

```yaml
constraints:
  - id: C1
    desc: "No new dependencies"
    check: "python scripts/check_deps.py"
```

### 5.2 Schema changes

- `Task` gets `anti_slop: dict[str, Any] | None`; `to_dict`/`from_dict` preserve
  it.
- `PlanBundle` gets `anti_slop: dict[str, Any]` for the global block.
- `load_tasks()` currently does `raw.get("tasks") or raw.get("constraints")`.
  Change to **merge both lists**; this is required for the example above.
- `lint_tasks()`:
  - `kind: anti_slop` requires a valid `anti_slop` block (or global defaults);
    no `check`/`verify` command required.
  - unknown `anti_slop` keys → error in `lint`; unknown rule → error.
  - warn if `anti_slop.enabled` but no `paths`/exclude.
- `EngineConfig` gets `anti_slop: AntiSlopConfig | None`; built from the global
  block + `kind: anti_slop` constraints, with per-task overrides.
- `RunState` persists the normalized config + a hash, so resume is deterministic.

### 5.3 Engine integration

New `Diagnosis.SLOP` and `Observation` fields:

```python
class Diagnosis(str, Enum):
    ...
    SLOP = "SLOP"

@dataclass
class Observation:
    ...
    slop_ok: bool = True
    slop_findings: list[dict] = field(default_factory=list)
    slop_blocking: int = 0
    slop_warnings: int = 0
    slop_hash: str = ""
```

Pipeline in `Engine._observe()` (after `changed_files` and before/after public
verify):

```python
quality = gate.scan_paths(
    repo,
    changed_files,
    config,
    baseline_commit=state.baseline_commit,
    cache=...,
)
obs.slop_findings = [f.to_dict() for f in quality.findings]
obs.slop_blocking = sum(f.severity == "error" for f in quality.findings)
obs.slop_warnings = sum(f.severity == "warning" for f in quality.findings)
obs.slop_ok = obs.slop_blocking == 0
obs.slop_hash = quality.hash
```

Scanner errors are **non-fatal**: record `slop_errors`, log an event, and do
not fail the run (a gate bug must never brick a working repo). Parse errors
(`SyntaxError`) are findings (`SLOP000`) unless already covered by the test
failure; a syntax error should usually be `SLOP000` error.

Detector priority (proposed):

```
ALIVE
VAULT_TAMPER / TAMPER
BLOCKED
FROZEN
HIDDEN_FAIL / SUSPECT_TEST
SLOP                 # quality is blocking, but hidden correctness wins first
DONE                 # requires slop_ok
FALSE_DONE
THRASH / STALL
BREAKER
PARTIAL
```

`DONE` condition becomes:

```python
if obs.all_tasks_done and test_ok and obs.integrity_ok and obs.hidden_ok and obs.slop_ok:
    return Diagnosis.DONE
```

`SLOP` is **non-terminal by default**; it falls through `_budget_guard`, gets a
checkpoint, and a wake prompt. `on_violation: abort` maps it to terminal
`SLOP`/exit code 6. Add `Diagnosis.SLOP` to `EXIT_CODES` only for abort mode.

`injector.build_wake_prompt()` gets `slop_findings` and `slop_summary`:

```text
QUALITY GATE — 3 blocking finding(s):
- SLOP002 src/foo.py:42:1 silent exception: `except Exception: pass`
  Fix: catch a specific exception or log with context.
- SLOP004 src/bar.py:18 function `handle()` is 143 lines (limit 100).
  Split the function or move branches into helpers.
```

### 5.4 Rollback semantics

Three policies:

| `on_violation` | Behavior | Safety |
|---|---|---|
| `kick` (default) | Reject the turn; keep all work; wake with findings | safest; agent fixes |
| `revert` | Restore **only violating files** from the pre-turn checkpoint, keep other files | opt-in; may lose valid edits in those files |
| `abort` | Stop the run with terminal `SLOP` (exit 6) | explicit |

`revert` implementation:

1. Before each turn, the existing checkpoint commit is the restore point.
2. Map findings to repo-relative paths.
3. For tracked files:
   `git restore --source=<checkpoint> --staged --worktree -- <paths>`
4. For untracked files: delete only if the file is inside the repo and not a
   symlink; refuse paths outside the repo.
5. Record `slop_revert` with files, checkpoint, and finding fingerprints.
6. Re-scan to confirm; if violations remain, fall back to `kick` rather than
   loop blindly.

Do **not** `git reset --hard`: it would destroy unrelated valid work and
interfere with the agent's session. A hunk-level surgical revert is deferred;
file-level revert is predictable and documented.

---

## 6. CLI experience

### 6.1 Commands

```bash
waker audit                         # scan diff/HEAD, read-only
waker audit --anti-slop             # explicit (default in v2)
waker audit --changed-only          # default; only changed files
waker audit --all                   # whole tracked Python tree
waker audit --baseline main         # compare against a git revision
waker audit --write-baseline        # record current findings (human-approved)
waker audit --format json
waker audit --format sarif > waker.sarif
waker check --anti-slop             # alias for CI/pre-commit, no writes
waker gate rules                    # list rule IDs/defaults
waker gate explain SLOP002          # rule docs + examples
waker gate baseline status          # baseline file stats
```

Exit codes:

- `0`: no blocking findings (warnings allowed unless `--strict`)
- `2`: blocking findings
- `1`: internal/scan error (never a finding)
- `3`: invalid config

### 6.2 Terminal diagnostics

```
Anti-Slop Audit — 3 findings (2 blocking, 1 warning)

src/payments/refund.py:42:1  SLOP002  error
  41  try:
  42      charge.refund()
  43  except Exception:
  44      pass
  Silent broad exception. Catch a specific error, or log and re-raise.

src/payments/refund.py:18:1  SLOP004  error
  Function `refund_batch()` is 143 logical lines (limit 100).
  Split the loop body into `_refund_one()` and keep orchestration here.

src/payments/models.py:7:1  SLOP007  warning
  File grew from 210 to 248 lines (+18%, +38 lines).
  Move the new DTOs into `refund_models.py` or update the baseline.

Baseline: 1 pre-existing finding suppressed (`.waker/anti-slop-baseline.json`).
```

- Rich table + code frame; `--format json` is stable and headless.
- `waker watch` header adds:
  `quality: 2 errors · 1 warning` and colors the row red/yellow.
- `waker status --format json` adds:
  `"quality": {"errors": 2, "warnings": 1, "rules": ["SLOP002","SLOP004"]}`.
- `waker report` appends a **Quality Gate** section with findings and the
  config hash; the report remains a render of events.

### 6.3 JSON shape

```json
{
  "version": 1,
  "scanned": 14,
  "skipped": 3,
  "findings": [
    {
      "rule": "SLOP002",
      "severity": "error",
      "path": "src/payments/refund.py",
      "line": 42,
      "col": 1,
      "end_line": 44,
      "message": "Silent broad exception handler",
      "suggestion": "Catch a specific error or log and re-raise.",
      "fingerprint": "sha256:...",
      "baseline": false
    }
  ],
  "summary": {"errors": 1, "warnings": 0}
}
```

SARIF 2.1.0 maps `rule`, `level`, `locations`, `partialFingerprints`, so
GitHub code scanning/CI can annotate the PR.

### 6.4 Suppression

Prefer namespaced comments with a reason:

```python
except ImportError:  # waker: ignore[SLOP002] reason="optional accelerator"
    pass
```

- Inline is line-scoped; a `# waker: ignore-file[SLOP006] reason="..."` at the
  top of a generated file exempts the file.
- `waker audit` prints suppressions with counts; `--strict` can fail if a
  suppression is unused (stale suppression).
- No blanket `# noqa`; rule IDs required; reason required (lint warns if
  missing).

---

## 7. Packaging, performance, security

### 7.1 Zero dependencies

- `waker.gate` imports only stdlib: `ast`, `tokenize`, `symtable`, `hashlib`,
  `json`, `pathlib`, `dataclasses`, `collections`, `concurrent.futures`,
  `difflib`.
- No `tree-sitter`, `radon`, `flake8`, `pylint`, `libcst`.
- CLI rendering already depends on `rich`; the core gate remains usable
  headless (`waker audit --format json`).
- Python ≥ 3.11 (already required); `ast.Match`/`match_case` available.

### 7.2 Performance

- Scan only `changed_files` by default; `--all` is explicit.
- Cache key: `sha256(file content) + sha256(normalized config) + gate version`.
  Cache file: `.waker/quality-cache.json`; invalidated on config version bump.
- Parse one file at a time; a thread pool for file reads (I/O) not required for
  normal diffs. For `--all` on >2,000 files, use
  `concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count()))`;
  AST work is CPU-bound but the GIL is acceptable at this scale. If needed, a
  `ProcessPoolExecutor` behind a flag.
- Guardrails: max file size 2 MB, max 20k lines, skip binary/non-UTF8, skip
  symlinks outside the repo, stop after 5,000 findings.
- Soft budget: 500 ms; if exceeded, return partial results and a `scan_timeout`
  event; never fail the run.

### 7.3 Security

- `ast.parse`/`tokenize` are non-executing; never import or `exec` target code.
- No network in the gate.
- Never follow symlinks outside the repo; resolve paths and check
  `Path.is_relative_to(repo)`.
- Do not include source snippets in hidden-test prompts; quality findings are
  public code, but still sanitize absolute paths.
- Rollback uses `waker.winproc` (silent Windows subprocess) and only paths
  inside the repo; never `git reset --hard`.
- Config validation prevents pathological thresholds (e.g., 0 lines, negative
  growth).

### 7.4 Multi-language boundary

The zero-dependency AST gate is **Python-only**. For JS/TS/Rust, Waker can:
- run external commands as **contract constraints** (`check: "npx eslint ..."`),
- support an optional future plugin interface (`waker-gate-<lang>`), and
- keep “anti-slop” scope honest: do not claim AST coverage for languages we do
  not parse.

---

## 8. Versioning and migration

### 8.1 Current reality

- Stable: **v1.2.0** (update notifier shipped).
- The original `v0.3.0 -> v1.0.0` roadmap is historical; do not publish v1.0.0
  after v1.2.0.

### 8.2 Proposed train

| Version | Content | Default |
|---|---|---|
| **v1.3.0** | `waker.gate`, `waker audit`, JSON/SARIF, opt-in contract block, `SLOP` diagnosis | anti-slop **off** |
| **v2.0.0** | default-on for new contracts; blocking gate; rollback policies; schema v2 | on for `version: 2` |
| **v2.x** | JS/TS plugin interface, hunk-level revert, more rules | opt-in |

If a single major release is required, ship **v2.0.0** and keep `v1.2.x`
maintained for one release cycle.

### 8.3 Migration

- v1.x `constraints` with `check`/`verify` remain valid.
- v2 accepts schema v1 contracts; `waker lint` prints a migration hint.
- New `anti_slop` block is optional in v1.3, default-on for new `version: 2`
  contracts in v2.
- Existing repos can opt out with `anti_slop.enabled: false` or
  `WAKER_ANTI_SLOP=0`.
- Baseline old violations with `waker audit --write-baseline` before enabling
  blocking; this is the recommended onboarding path.
- `waker doctor` reports: gate version, files scanned, baseline age, and
  whether the gate is enabled.

### 8.4 Update notifications

Already shipped in **v1.2.0** (`src/waker/update.py`):

- reads a 6-hour cache; refreshes PyPI in a daemon thread; never blocks;
- banner on interactive terminals only, to stderr; ASCII fallback;
- `WAKER_UPDATE_CHECK=0`, `NO_UPDATE_NOTIFIER=1`, and CI skip;
- no telemetry; only the public PyPI JSON.

For v2:
- reuse the same notifier; no new mechanism;
- add `waker doctor` output for current/latest version and the upgrade command;
- release notes include the `pip install --upgrade waker-ai` line;
- pip never auto-updates; the banner is a notification, not an installer.

---

## 9. Test plan and acceptance criteria

### 9.1 Fixtures

`tests/fixtures/anti_slop/`:

- `clean.py` — no findings.
- `duplicate_symbols.py` — duplicate top-level function/class/method.
- `overloads.py` — `@overload`, property/setter, platform branches (no false
  positives).
- `copy_paste_a.py`, `copy_paste_b.py` — shared block.
- `exceptions.py` — bare/broad/empty, narrow/empty, logging/re-raise (allowed).
- `complexity.py` — nested branches, boolean operators, match.
- `long_function.py`, `long_module.py`.
- `growth_before.py` / `growth_after.py` — 15% rule.
- `generated.py`, `tests/test_fixture.py` — excluded by default.

### 9.2 Tests

- Unit: each rule; line/column/fingerprint stability; severity; suppression.
- False positives: overloads, property setters, conditional definitions,
  optional imports, dataclasses, `__init__.py` re-exports.
- Config: defaults, overrides, invalid values, unknown keys, path/exclude.
- Baseline: write/read, stale fingerprints, new vs old findings.
- Engine: `SLOP` at kick 0 → clean at kick 1 with a fake agent; `DONE` requires
  `slop_ok`; `kick`/`revert`/`abort`; no false `TAMPER` from the gate cache.
- CLI: exit codes, JSON schema, SARIF, TTY vs pipe, `--strict`, `--all`.
- Performance: 200 changed files under the soft budget; cache hit avoids parse.
- Cross-platform: Windows/Linux; no console windows; UTF-8 and cp1252 fallback.
- Security: symlink escape, huge file, invalid syntax, non-UTF8, no execution.

### 9.3 Acceptance

- [ ] `waker audit` finds the fixture slop and returns 2.
- [ ] Clean fixture returns 0; no network.
- [ ] `waker run` rejects a slop-producing fake agent (`SLOP`), wakes it, then
  accepts a clean turn (`DONE`).
- [ ] Baseline suppresses legacy findings; only new ones block.
- [ ] `waker status --format json` exposes quality counts; stdout remains
  parseable when the update banner is enabled.
- [ ] `pytest` green on Windows and Linux; no new runtime dependencies.
- [ ] A v1.x contract still runs unchanged.

---

## 10. Risks and decisions

| Risk | Mitigation |
|---|---|
| False positives (metaprogramming, generated code) | baseline, exclusions, suppression with reason, warn-first rollout |
| Duplicate detection noise | scope-aware, decorator/platform exemptions, thresholds, cross-file only for copy-paste |
| God-function threshold subjective | configurable per task; baseline; warn for 100–150, error >150? default 100 error |
| Rollback destroys valid work | default `kick`; `revert` opt-in + file-scoped; log every revert |
| Python-only AST | state clearly; external commands for other languages; future plugin |
| Performance on huge diffs | changed-only, content-hash cache, limits, soft timeout |
| Gate bug bricks runs | scanner errors are non-fatal; tests + fallback to verify-only |
| “Slop” becomes a style war | rule IDs are narrow and mechanical; no formatting/naming rules |
| v2 breaks existing contracts | v1.3 opt-in, schema v1 accepted, baseline, env opt-out |

**Key decisions:**

1. Default `on_violation: kick`, not rollback. Rejecting the turn is a soft
   rollback; destructive file restore must be explicit.
2. Quality is blocking only for **new** findings; legacy is baselined.
3. `waker.gate` is stdlib-only; Rich stays in the CLI layer.
4. Python AST only in v2; no false multi-language claims.
5. Current version is v1.2.0; the anti-slop major release is **v2.0.0**, with
   v1.3.0 as the opt-in preview.

---

## 11. Implementation phases

| Phase | Deliverable | Exit criteria |
|---|---|---|
| 0 | This spec + rule IDs + fixtures | reviewed |
| 1 | `waker.gate` core + `waker audit` read-only | unit tests, clean/slop fixtures |
| 2 | Contract schema + engine `SLOP` + wake prompt | fake-agent E2E, no regression |
| 3 | Baseline, suppression, SARIF, TUI/status | CLI acceptance, perf budget |
| 4 | v1.3.0 opt-in release | PyPI, update notifier, docs |
| 5 | v2.0.0 default-on + migration | migration guide, baseline onboarding |

---

## Appendix A — Example engine observation

```python
obs = Observation(
    ...,
    slop_ok=False,
    slop_blocking=2,
    slop_warnings=1,
    slop_findings=[
        {"rule": "SLOP002", "path": "src/pay.py", "line": 42, ...},
        {"rule": "SLOP004", "path": "src/pay.py", "line": 18, ...},
    ],
)
diag = detector.diagnose(obs)  # Diagnosis.SLOP
```

## Appendix B — Example SARIF result

```json
{
  "version": "2.1.0",
  "runs": [{
    "tool": {"driver": {"name": "waker-anti-slop", "version": "2.0.0"}},
    "results": [{
      "ruleId": "SLOP002",
      "level": "error",
      "message": {"text": "Silent broad exception handler"},
      "locations": [{"physicalLocation": {
        "artifactLocation": {"uri": "src/pay.py"},
        "region": {"startLine": 42, "startColumn": 1}
      }}],
      "partialFingerprints": {"waker/v1": "sha256:..."}
    }]
  }]
}
```

## Appendix C — Defaults summary

```
max_function_lines          100
max_module_lines            1000
max_cyclomatic_complexity   15
max_nesting_depth           5
max_parameters              8
ban_broad_except            true
ban_silent_except           true
ban_duplicate_symbols       true
duplicate_block_min_lines   20
duplicate_block_min_statements 8
track_file_growth           0.15
growth_min_lines            30
on_violation                kick
changed_only                true
```
