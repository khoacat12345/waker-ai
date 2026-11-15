# Waker Anti-Slop AI Code Guardian — Architecture & Feature Specification

**Status:** proposed (design)
**Target:** **v2.0.0 — default-on** (no v1.3 intermediate)
**Implementation plan:** [`ANTI_SLOP_ROADMAP.md`](ANTI_SLOP_ROADMAP.md)
**Owner:** Waker maintainers
**Scope:** Python AST quality gate for AI-generated code, contract schema,
engine enforcement, CLI diagnostics, packaging, migration.
**Non-goals:** replacing pytest/ruff/mypy; auto-rewriting code; full JS/TS AST
support; LLM-based style judgement; runtime profiling.

> **Version note.** The current stable release is **v1.2.0** (2026-11-15). The
> Product Owner decision (2026-11-15) is to ship the Guardian **directly in
> v2.0.0 with default-on gates**; the earlier v1.3 opt-in preview is cancelled.
> Users who need the old behavior pin v1.2.0. The old
> `v0.3.0 -> v1.0.0` roadmap is historical; do not publish v1.0.0 after v1.2.0.

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

> The table above is the **core** anti-slop family. The four extended guardian
> families — test integrity, architecture/import direction, dead code, and
> package whitelist — plus security/resource/API guards are specified in
> **§4A**.

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
    tests.py           # TEST001-TEST008
    types.py           # TYPE001-TYPE012
    comments.py        # COMMENT001-004, SUPPRESS001-002, STUB001
    architecture.py    # ARCH001-ARCH004, import graph/SCC
    dead_code.py       # DEAD001-DEAD004, symbol table
    dependencies.py    # PKG001-PKG004, manifests/import-dist mapping
    security.py        # SEC001-SEC007, secret redaction
    resources.py       # RES001-RES003, API001-002, ASYNC001, COUPLE001-002
  graph.py             # import graph, Tarjan SCC, fan-in/fan-out
  symbols.py           # scope-aware definitions/references
  manifests.py         # requirements.txt / pyproject.toml parsing
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
    enabled: bool = True                  # v2 default; Phase 1 audit preview
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

## 4A. Extended Guardian Families (v2.0 default-on)

The core `SLOP001–008` rules catch mechanical slop. The four families below
close the higher-level escape routes: fake tests, layer inversion, dead code,
and dependency poisoning. They are **default-on in v2.0** for new contracts;
Phase 1 of the roadmap ships the read-only `waker audit` preview first.

Design rules for every family:

1. **Confidence tiers.** `certain` = structural fact (block); `likely` = strong
   heuristic (warn); `heuristic` = informational. Only `certain` rules may
   block by default.
2. **Baseline first.** Existing findings are recorded in
   `.waker/anti-slop-baseline.json`; only new/changed findings fail.
3. **Per-family policy.** `on_violation: kick | revert | abort`; severity can
   be `error | warning | off`; families can be disabled independently.
4. **No LLM in the gate.** The same deterministic AST facts power
   `waker audit`, `waker check`, and the engine. Optional external tools
   (mutation, coverage, type check) are contract commands, never hidden model
   calls.

### 4A.1 Test Integrity Guard (`TEST001–TEST008`)

Waker already hashes test files and reports `TAMPER`. That stops **editing the
exam**, but not **writing a fake exam**. This family checks the structural
quality of tests the agent writes or changes.

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `TEST001` | Test function has no assertion-like check | certain | error |
| `TEST002` | Always-true/tautological assertion (`assert True`, `assert 1`, `assert x == x`, `assert (x, "msg")`) | certain | error |
| `TEST003` | Mock tautology / patch of the system under test | certain | error |
| `TEST004` | Assertion swallowed or unreachable (`except AssertionError: pass`, assert after `return`, all asserts inside `if/for`) | certain | error |
| `TEST005` | Unconditional skip/xfail, or `xfail(strict=True)` used to ship a stub | certain | error |
| `TEST006` | Mock ratio above `max_mock_ratio` | likely | **warning** |
| `TEST007` | `pytest.raises(Exception)` / no `match=` where a specific error is expected | likely | warning |
| `TEST008` | Orphan test (file imports no target / redefines a local fake) | likely | warning |

Assertion inventory per test:

- `assert` statements;
- `pytest.raises`, `pytest.warns`, `pytest.deprecated_call`;
- `unittest` `self.assert*` / `assertRaises`;
- `unittest.mock` `assert_called*` (must be **called**, not referenced);
- framework assertions (`django.test`, `numpy.testing`, etc.) via allowlist.

Do **not** treat a test as good just because it has one assertion; `TEST002`
and `TEST003` catch the classic fake ones. A test that only checks
`result is not None` is a **warning**, not a hard block; it can be legitimate
for crash/smoke tests.

Mock rules in detail:

- **Patch-the-SUT**: `@mock.patch("pkg.svc.fetch")` inside a test of
  `pkg.svc.fetch`, then only asserting on the mock. This is the highest-value
  test-cheating rule.
- **Mock tautology**: configure `mock.return_value = 5` and assert
  `mock() == 5` with no production call in between.
- **Uncalled mock assertion**: `assert mock.assert_called_once` (missing `()`)
  — always passes.
- **Swallowed assertion**: `try: ... assert ... except AssertionError: pass`.
- **Mock ratio**: count mock setups/patches vs real calls/assertions. **This is
  a warning, not a defect.** The number of collaborators varies; some
  integration tests legitimately mock every external boundary. Blocking at
  “70%” would punish correct tests and produce the boy-who-cried-wolf effect.
  `pytest-review` deliberately has no “too many mocks” rule for this reason.
- **Mutation testing is the proof.** Static checks can only prove a test is
  structurally fake; they cannot prove it catches a bug. Add an optional
  contract command (`mutmut run`, `cosmic-ray`) for teams that want the real
  oracle. Coverage (`coverage.py`) is also optional and external.

Config:

```yaml
gates:
  test_integrity:
    enabled: true
    paths: ["tests/**", "**/test_*.py"]
    min_assertions_per_test: 1
    ban_trivial_assertions: true
    ban_mock_of_sut: true
    ban_uncalled_mock_assertions: true
    ban_swallowed_assertions: true
    ban_unconditional_skip: true
    max_mock_ratio: 0.70
    max_mock_ratio_severity: warning
    allow_markers: ["integration", "slow"]
    on_violation: kick
```

### 4A.2 Architecture & Dependency Direction Guard (`ARCH001–ARCH004`)

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `ARCH001` | Forbidden layer/direction import (e.g. core → UI) | certain | error |
| `ARCH002` | Runtime import cycle (SCC in the module graph) | certain | error |
| `ARCH003` | Fan-out / instability above threshold | likely | warning |
| `ARCH004` | Dynamic import with an unresolvable/dotted string target | heuristic | warning |

Module graph algorithm:

1. Map files to modules (support `src/` layout, packages, `__init__.py`).
2. Parse `Import` / `ImportFrom`; resolve relative imports with the current
   package; record `line`, `module`, `target`, `type_only`.
3. `if TYPE_CHECKING:` and `from __future__ import annotations` edges are
   marked **type-only**; they do not count as runtime cycles by default
   (`type_checking: ignore`). Teams can choose `separate` or `enforce`.
4. Add constant dynamic imports (`importlib.import_module("pkg.x")`,
   `__import__("pkg.x")`); non-constant/dotted strings are `ARCH004` warnings.
5. Build a directed graph; Tarjan/Kosaraju SCC finds cycles.
6. Assign layers by glob; an edge `A → B` is allowed only when `B` is in
   `allow[A]`, or `B` is stdlib/first-party/external-allowlisted as configured.
7. Baseline: record existing cycles/layer violations with fingerprints so
   legacy architecture does not block the first run.

Config:

```yaml
gates:
  architecture:
    enabled: true
    layers:
      core: ["src/core/**"]
      services: ["src/services/**"]
      ui: ["src/ui/**"]
    allow:
      core: ["stdlib"]
      services: ["core", "stdlib"]
      ui: ["services", "core", "stdlib"]
    detect_cycles: true
    type_checking: ignore      # ignore | separate | enforce
    max_fan_out: 12
    baseline: auto
    on_violation: kick
```

“Core may only import the standard library” is a **strict profile**, not a
universal law. Many projects need a core that imports a small set of approved
third-party primitives (pydantic, typing_extensions). Make it a config choice;
the standard rule is **explicit direction**, not “stdlib only”.

Prior art: `import-linter` (layers/independence/forbidden), `pyscythe
boundaries`, `layerguard`, `archetype-py`, `code-governance`,
`pymodularity`. They all use an AST/import graph, baselines, and SARIF/JSON.
Borrow that; do not invent a new graph model.

### 4A.3 Dead Code & Unused Import Hunter (`DEAD001–DEAD004`)

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `DEAD001` | New private function/class/method with no reference | high | error |
| `DEAD002` | New unused import | high | error |
| `DEAD003` | Public symbol with no reference | low | warning |
| `DEAD004` | Module/package not reachable from any entry point | low | warning |

This is the highest false-positive family in static analysis. Use confidence
and exemptions:

- **Private-only by default.** `_helper` with no references is a strong signal;
  public `parse()` may be an API, plugin hook, or entry point.
- **References** include `Name`, `Attribute` (attribute resolution is
  conservative), imports/re-exports, `__all__`, decorators, `getattr`,
  `globals()`, string names in registries, and entry points from
  `pyproject.toml`/`setup.cfg`.
- **Exempt** framework hooks (`pytest_*`, test functions/fixtures, Django
  views/models/admin, FastAPI/Flask routes, Celery tasks, Click/Typer commands,
  SQLAlchemy models, Pydantic models, `__init__`, `__enter__`, `__exit__`,
  `__getattr__`, `__all__`, `.pyi` stubs, generated/vendored trees).
- **Module-level `globals()` / `__getattr__` / reflection** disables DEAD for
  that module.
- **Unused imports**: exempt side-effect imports, `__all__`, `*` imports,
  `TYPE_CHECKING`, optional-import fallbacks, and `# noqa: F401` / waker
  suppression.
- **New/changed only**: baseline legacy dead code; do not make a first run
  unusable.
- **Do not auto-delete.** Report and let the agent or human remove; a wrong
  deletion is worse than a warning.

Config:

```yaml
gates:
  dead_code:
    enabled: true
    private_only: true
    unused_imports: true
    public_api: warning
    entry_points: ["pyproject.toml", "setup.cfg"]
    framework_hooks: true
    baseline: auto
    on_violation: kick
```

Prior art: `vulture` (min-confidence, whitelist), `pyscythe dead-code`
(framework plugins, `.pyi`, `globals()`), `jarvis-graph-lite`,
`import-analyzer-py`. All of them document false positives; Waker must too.

### 4A.4 Package Whitelist & Supply-Chain Guard (`PKG001–PKG004`)

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `PKG001` | Import of a third-party package outside the allowlist | certain | error |
| `PKG002` | New dependency added to a manifest without approval | certain | error |
| `PKG003` | Unpinned / URL / VCS dependency | certain | warning |
| `PKG004` | Import name cannot be mapped to a distribution | likely | warning |

Resolution rules:

- **Standard library**: `sys.stdlib_module_names` (no hardcoded list).
- **First-party**: package roots/modules under the repo; `src/` layout aware.
- **Third-party**: allowed list from config; installed distributions via
  `importlib.metadata.packages_distributions()` to map import names to
  distributions (`yaml` → `PyYAML`, `PIL` → `Pillow`, `cv2` →
  `opencv-python`). Unknown mappings are warnings, not guesses.
- **Manifests**: `requirements*.txt`, `pyproject.toml` (`tomllib`), `setup.cfg`
  where present. Diff against the baseline; new dependency names require
  `allow_new: true` or an explicit approval. Flag unpinned/URL/git deps.
- **Hallucinated packages**: optional `pypi_lookup: true` checks the public
  PyPI JSON with a short timeout; offline mode keeps the last known result.
  Never make network access mandatory. A 404 is a warning/error pending
  allowlist review; it is not proof of malice.
- **Typosquatting**: optional similarity warning (Levenshtein to popular
  packages), never a block on its own.
- **Do not intercept live `pip install`**: Waker sees static imports and
  manifests. If the agent runs a shell install, that is outside this gate;
  use a separate command/agent policy if needed.
- **Do not auto-update or auto-install.** The gate only reports; installing is
  the user's explicit action.

Config:

```yaml
gates:
  dependencies:
    enabled: true
    allow: ["stdlib", "pytest", "waker-ai"]
    allow_new: false
    check_manifests: true
    pypi_lookup: false
    pinning: required          # required | warn | off
    on_violation: kick
```

Prior art: `deptry` (unused/missing/transitive deps), `pip-audit`
(vulnerabilities), `pyscythe deps` (declared vs imported), `import-analyzer`.
Waker’s zero-dependency version covers the static subset; vulnerability and
mutation checks remain external commands.

### 4A.5 Security Guard (`SEC001–SEC007`)

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `SEC001` | `eval`, `exec`, `compile` of dynamic input | certain | error |
| `SEC002` | `pickle`/`marshal`/unsafe deserialization | certain | error |
| `SEC003` | `shell=True`, `os.system`, unsanitized shell command | certain | error |
| `SEC004` | `yaml.load` without `SafeLoader` | certain | error |
| `SEC005` | TLS verification disabled (`verify=False`) | certain | error |
| `SEC006` | Hardcoded secret (regex + entropy) | likely | error |
| `SEC007` | SQL built by string interpolation | likely | warning |

Rules:

- Redact secret values in every output; report only the location and a masked
  preview. Never write the secret to events/report/SARIF.
- Exempt test fixtures/examples explicitly, and allow `# waker: ignore` with a
  reason. A test that intentionally exercises `eval` should not block.
- Security findings can use `on_violation: abort` for critical profiles;
  default `kick`.
- No network scanning of the source; this is static AST/regex only.

Prior art: Bandit, Semgrep, Ruff `S` rules. Waker implements a small,
high-confidence subset; users can add Bandit/Semgrep as a contract `check` for
broader coverage.

### 4A.6 Resource, API, Async, and Coupling Guards (optional)

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `RES001` | File/socket opened without a context manager | likely | warning |
| `RES002` | Subprocess/HTTP call without a timeout | likely | warning |
| `RES003` | `tempfile.mktemp` | certain | error |
| `API001` | Public symbol/signature removed or changed vs baseline | certain | warning |
| `API002` | `__all__` lists a missing symbol | certain | error |
| `ASYNC001` | Blocking call (`time.sleep`, sync HTTP) inside `async def` | likely | warning |
| `COUPLE001` | Module fan-out / instability above threshold | heuristic | warning |
| `COUPLE002` | “God module” (symbols × LOC × fan-in) | heuristic | warning |

These are intentionally **warnings** in v2.0; promote to error only with
project-specific thresholds and a baseline. They are useful for `waker audit`
and dashboards, but blocking a run on fan-out is a policy decision, not a
universal defect.

### 4A.7 Prior art — what to borrow, what not to

| Waker family | Established tools | Borrow | Do not copy |
|---|---|---|---|
| Test integrity | pytest-review, exspec, falsegreen, vacuous, testrot, pragma | no-assert/tautology/mock-the-SUT/swallowed-assertion rules; confidence | “mock ratio is a defect” (it is not); LLM judge in core |
| Complexity | Ruff `C901`, Pylint `R0912/R0915`, radon, pyscythe | cyclomatic/cognitive thresholds, line counts | one universal threshold for every project |
| Architecture | import-linter, pyscythe, layerguard, archetype-py, code-governance, pymodularity | layers, cycles, fan-in/out, SARIF, baseline | “core = stdlib only” as a universal law |
| Dead code | vulture, pyscythe, jarvis-graph-lite, import-analyzer-py | confidence, framework hooks, `.pyi`/`globals()` guards | auto-delete; flag every public symbol |
| Dependencies | deptry, pip-audit, pyscythe deps | import↔distribution mapping, manifest diff, allowlist | mandatory network lookup; auto-install |
| Security | Bandit, Semgrep, Ruff `S` | eval/exec/pickle/shell/yaml/TLS/secrets | reporting secret values; false-positive-free claims |
| Mutation/coverage | mutmut, cosmic-ray, coverage.py, pytest-cov | optional external proof | pretending static analysis proves test quality |

### 4A.8 Assessment of the four proposed layers

**Verdict: the direction is right; the defaults need calibration.**

1. **Test-Cheating Guard — keep, but do not make mock ratio a hard error.**
   Structural false-green patterns are excellent blockers:
   no assertion, `assert True`, mock-the-SUT, uncalled mock assertion,
   swallowed assertion, unconditional skip/xfail. “Mock > 70%” is a useful
   signal, not a defect; pytest-review explicitly rejects a “too many mocks”
   rule because collaborator counts vary. Use `warning`, per-marker overrides,
   and optional mutation testing for the real proof.
2. **Import Direction Guard — keep, but use explicit layers, not a universal
   “core only stdlib”.** Model `TYPE_CHECKING`, lazy imports, `.pyi`, and
   dynamic imports. Detect cycles with SCC; baseline existing cycles. The
   strict stdlib-only profile can be a named preset (`strict-core`), not the
   only mode.
3. **Dead Code Hunter — keep, but private-only + confidence + exemptions.**
   Public symbols, framework hooks, entry points, `__all__`, `.pyi`,
   `getattr`/`globals`, and plugin registries create false positives. Use
   high-confidence private findings for blocking; public/dead modules are
   warnings. Baseline legacy. Never auto-delete without human approval.
4. **Package Whitelist — keep, but resolve import↔distribution and diff
   manifests.** `yaml` is not `PyYAML`; use `importlib.metadata` and
   `sys.stdlib_module_names`. Default `allow_new: false` for strict repos;
   `warn` for permissive ones. Optional PyPI lookup only; no mandatory
   network. Do not pretend to intercept live `pip install`.

| Proposed layer | Verdict | Non-negotiable calibration |
|---|---|---|
| Test-cheating guard | **Strong** | block structural false-green only; mock ratio = warning; mutation testing optional |
| Import direction | **Strong** | explicit layer config; `TYPE_CHECKING`/lazy/dynamic handling; SCC cycles; baseline |
| Dead code hunter | **Medium–strong** | private-only + confidence; framework/entry-point/`__all__`/`.pyi` exemptions; baseline; no auto-delete |
| Package whitelist | **Strong** | import↔distribution mapping; manifest diff; offline mode; `allow_new` policy |
| **Security guard (new)** | **Very strong** | high-confidence eval/exec/pickle/shell/yaml/TLS/secrets; redact values |
| **Resource/API/async/coupling (new)** | Medium | warnings by default; promote per project with baseline |
| **Test isolation (new)** | Medium | network/sleep/env/global-state warnings; markers/overrides |

Additional guards I recommend beyond the four:

- **Security Guard** (`SEC001–SEC007`): eval/exec, pickle, shell=True,
  `yaml.load`, `verify=False`, hardcoded secrets. This is the highest-value
  addition; a slop gate that ignores `eval()` and `shell=True` is incomplete.
- **Resource Guard** (`RES001–003`): unclosed files/sockets, subprocess/HTTP
  without timeout, `tempfile.mktemp`. Warnings, not blocks.
- **Public API Guard** (`API001–002`): removed/changed public symbols,
  `__all__` mismatches. Warnings; protects consumers.
- **Async Guard** (`ASYNC001`): blocking calls inside `async def`. Warning.
- **Coupling Guard** (`COUPLE001–002`): fan-out/instability/god modules.
  Informational, dashboard-friendly.
- **Test Isolation Guard** (`TEST006`): network, `time.sleep`, `os.chdir`,
  `os.environ`, global state. Warning; markers for integration tests.

References / prior art (fetched from current ecosystem, 2026):

- Test quality: `pytest-review`, `exspec`, `falsegreen`, `vacuous`,
  `testrot`, `pragma`.
- Architecture: `import-linter`, `pyscythe`, `layerguard`, `archetype-py`,
  `code-governance`, `pymodularity`.
- Dead code: `vulture`, `pyscythe dead-code`, `jarvis-graph-lite`,
  `import-analyzer-py`.
- Dependencies: `deptry`, `pip-audit`, `pyscythe deps`.
- Security: Bandit, Semgrep, Ruff `S` rules.
- Complexity: Ruff `C901`, Pylint `R0912/R0915`, radon.
- Optional proof: `mutmut`, `cosmic-ray`, `coverage.py`, `pytest-cov`.
- URLs: `https://pypi.org/project/pytest-review`,
  `https://github.com/morodomi/exspec`,
  `https://pypi.org/project/falsegreen/`,
  `https://pypi.org/project/vacuous/`,
  `https://github.com/mathewOracle/testrot`,
  `https://github.com/Joncik91/pragma`,
  `https://pypi.org/project/pyscythe/`,
  `https://github.com/justiceandmercy/layerguard`,
  `https://github.com/MossabArektout/archetype-py`,
  `https://github.com/useparadigm/code-governance`,
  `https://pypi.org/project/pymodularity/`,
  `https://github.com/cmyui/import-analyzer-py`.

The common failure mode of all four is **false positives**. Waker’s brand is
“mechanical truth”; a noisy quality gate would destroy trust faster than a
missed slop. Therefore: `certain` rules block, `likely` rules warn, legacy is
baselined, and every suppression requires a reason.

### 4A.9 Feature matrix vs prior art (and what Waker still lacks)

| Capability | Waker spec | dmmulroy/anti-slop | TinyFrontier/anti-slop-py | scanaislop/aislop | dannote/sloplint |
|---|---:|---:|---:|---:|---:|
| Deterministic AST | ✅ | ✅ | ✅ | ✅ | ✅ |
| Zero new runtime deps | ✅ | ❌ Oxlint | ✅ | ❌ Node | ❌ ast-grep |
| Python | ✅ | ❌ | ✅ | ✅ | ✅ |
| TypeScript / JS | ⚠️ adapter only | ✅ | ❌ | ✅ | ✅ |
| Type-evidence rules (`Any`/cast/ignore) | ✅ (new §4A.10) | ✅ | ✅ | ⚠️ partial | ❌ |
| Test integrity / fake tests | ✅ | ❌ | ❌ | ⚠️ partial | ❌ |
| Architecture / layer direction | ✅ | ❌ | ❌ | ⚠️ opt-in | ❌ |
| Dead code / unused imports | ✅ | ❌ | ❌ | ✅ | ❌ |
| Dependency / package whitelist | ✅ | ❌ | ❌ | ⚠️ partial | ❌ |
| Security (eval/shell/secrets) | ✅ | ❌ | ❌ | ✅ | ❌ |
| Comment / suppression slop | ✅ (new §4A.11) | ⚠️ partial | ⚠️ partial | ✅ | ✅ |
| Active kick / rollback | ✅ **unique** | ❌ | ❌ | ⚠️ hook/fix | ❌ |
| Hidden-test blind grading | ✅ **unique** | ❌ | ❌ | ❌ | ❌ |
| Baseline / SARIF | ✅ | ⚠️ | ✅ | ✅ | ⚠️ |
| Auto-fix / score / badge | ❌ | ❌ | ❌ | ✅ | ❌ |

**Verdict:** Waker already has the **watchdog architecture, contract enforcement,
hidden tests, and most quality families**. The review found two clear gaps, now
closed in this revision:

1. **Type-evidence rules** (`Any`, `cast`, `# type: ignore`, ad-hoc
   `isinstance`) — the core thesis of `anti-slop-py`/`dmmulroy/anti-slop`.
   See §4A.10.
2. **Comment/suppression slop** — obvious comments, placeholders, unjustified
   suppressions — the core thesis of `sloplint`/`aislop`. See §4A.11.

`Waker spec` means design coverage in this document; the **v1.2.0 code** does not
implement the gate yet. Multi-language (TS/JS), auto-fix, scoring/badges, and
editor hooks are **intentional non-goals for the zero-dependency Python core**;
integrate them as optional adapters/commands rather than reimplementing 50 rules.

### 4A.10 Type Evidence Guard (`TYPE001–TYPE012`)

Waker’s brand is **evidence**. A type checker permits `Any`, `cast`, and
`# type: ignore` by design; those are legal holes in its own system. This family
bans the holes an agent uses to silence the checker without adding evidence.

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `TYPE001` | `Any`/`object`/`unknown` on a new function parameter | high | error (new/changed) |
| `TYPE002` | `Any`/`unknown` return annotation | high | error |
| `TYPE003` | type alias resolving to `Any`/`unknown` | high | error |
| `TYPE004` | chained casts `cast(T, cast(...))` | high | error |
| `TYPE005` | widen-then-cast (value widened to `Any`/`object`, then cast back) | high | error |
| `TYPE006` | ad-hoc `isinstance`/`issubclass` narrowing outside a type guard | medium | warning |
| `TYPE007` | `cast` without a nearby safety/invariant comment | medium | error (new code) |
| `TYPE008` | `# type: ignore` / `# pyright: ignore` / `# noqa` without a reason | high | error |
| `TYPE009` | `getattr`/`setattr`/`delattr` with string names, or `globals()`/`locals()`/`vars()` dispatch | medium | warning |
| `TYPE010` | known value widened to `Any`/`object`/`dict[str, Any]` | medium | warning |
| `TYPE011` | unsafe dict values (`dict[str, Any]`, `Mapping[str, object]`) | medium | warning |
| `TYPE012` | `isinstance` used as the only runtime contract for a public input | medium | warning |

Python AST sketch:

```python
# Any/object/unknown on parameters or returns
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for arg in [*node.args.args, *node.args.kwonlyargs]:
            if _is_any_or_object(arg.annotation):
                report("TYPE001", node, arg.arg)
        if _is_any_or_object(node.returns):
            report("TYPE002", node, node.name)

# chained cast: Call(func=cast, args[0]=Call(func=cast, ...))
# widen-then-cast: assignment to Any/object, then cast back from that name
# type: ignore: tokenize comments, require `[code]` and reason
# ad-hoc isinstance: Call(func=isinstance) not inside a TypeGuard/TypeIs return
```

TS/JS equivalents (optional adapter, borrowed from `dmmulroy/anti-slop`):
`as unknown as T`, `any`, `unknown` parameters/returns, `@ts-ignore` /
`@ts-expect-error` without a reason, `object` parameters, `Reflect.get/apply`,
runtime `typeof` narrowing, module mocking. Waker’s Python core should not pretend
to parse TypeScript; map these to an optional `aislop`/`oxlint` command.

Why this matters: hidden tests prove behavior, not type contracts. An agent can
pass every test while turning the public API into `Any` soup. Type evidence is
the missing bridge between “tests green” and “maintainable contract”.

False positives / controls:

- `Any` in legacy code is baselined; only new/changed functions block.
- `cast` with a real runtime validation or a `# SAFETY:` invariant is allowed
  (`TYPE007` checks for the comment; `TYPE005` checks the actual flow).
- `isinstance` at an I/O boundary or inside a `TypeGuard` is correct
  (`TYPE006` allows it); ad-hoc narrowing deep in business logic is not.
- `getattr`/`setattr` for framework glue can be allowlisted per path/rule.
- Dynamic `globals()`/`vars()` disables `TYPE009` for that module; do not guess.
- `TYPE001`/`TYPE002` default to **new/changed code only**; existing signatures
  are baselined.

Config:

```yaml
gates:
  type_evidence:
    enabled: true
    paths: ["src/**/*.py"]
    ban_any_parameters: true
    ban_any_returns: true
    ban_any_aliases: true
    ban_chained_casts: true
    ban_widen_then_cast: true
    ban_adhoc_isinstance: warning
    require_safety_comment: true
    ban_unexplained_type_ignore: true
    ban_string_attribute_access: true
    unsafe_dict_values: warning
    new_code_only: true
    baseline: auto
    on_violation: kick
```

Prior art: `dmmulroy/anti-slop` (19 generic + 5 Effect Oxlint rules),
`TinyFrontier/anti-slop-py` (15 core rules + FastAPI group, zero-dep
`ast`+`tokenize`+scope table, baseline/diff/review). Waker borrows the
**evidence-hole** thesis and the actionable “write this instead” diagnostics,
not their vendoring model.

### 4A.11 Comment & Suppression Slop (`COMMENT001–004`, `SUPPRESS001–002`, `STUB001`)

| ID | Rule | Confidence | Default |
|---|---|---|---|
| `COMMENT001` | Obvious/narrator comment restating the code (“This function…”) | medium | warning |
| `COMMENT002` | Step comment (`Step 1:`) or section divider (`==== Helpers ====`) | medium | warning |
| `COMMENT003` | Placeholder/apologetic/AI-generated comment (“… rest of code”, “quick hack”, “replace this”) | high | error |
| `COMMENT004` | TODO/FIXME/HACK without owner/ticket/date | low | warning |
| `SUPPRESS001` | `# type: ignore`, `# noqa`, `@ts-ignore`, `eslint-disable` without a reason | high | error |
| `SUPPRESS002` | Blanket suppression without a rule ID (`# type: ignore` vs `# type: ignore[code]`) | medium | warning |
| `STUB001` | New stub body (`pass`/`...`/`raise NotImplementedError`) in a non-abstract function | high | warning |

Rules:

- Comments should explain **why**, not **what**. A wire-format note, mutex
  ordering invariant, or algorithm provenance is allowed;
  `// Initialize the counter` is not.
- Do not flag comments that contain actual constraints/evidence; sloplint’s
  false-positive tests are the reference.
- Suppressions are not banned, but must be **narrow and justified**:
  ```python
  # waker: ignore[TYPE001] reason="third-party callback signature"
  # type: ignore[arg-type]  # reason: upstream stub is wrong; see #123
  ```
  No reason → error; blanket → warning/error.
- Stubs are warnings, not errors: a deliberate Protocol/ABC method is allowed;
  a new production function that only `raise NotImplementedError` is slop.
- This family is **warning-first** except placeholders and unexplained
  suppressions; comment style is subjective.

Config:

```yaml
gates:
  comments:
    enabled: true
    paths: ["src/**/*.py", "tests/**/*.py"]
    ban_obvious_comments: warning
    ban_step_comments: warning
    ban_placeholder_comments: error
    todo_policy: warning       # warning | off | error
    require_suppression_reason: true
    require_suppression_code: true
    stub_policy: warning
    allow_patterns: ["SAFETY:", "Wire format:", "Mutex order:"]
    on_violation: kick
```

Prior art: `dannote/sloplint` (obvious/narrator/step/section/placeholder/
apologetic/AI-generated comments, empty error handlers; ast-grep, 8 languages),
`scanaislop/aislop` (narrative comments, swallowed exceptions, hidden fallbacks,
todo stubs). Waker adds the **agent kick** and the same suppression-reason
discipline it already uses internally.

---

## 5. Contract schema (v2, backward compatible with v1.x)

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

### 5.1.1 Extended gates block (v2 canonical)

```yaml
version: 2

gates:
  anti_slop:
    enabled: true
    max_function_lines: 100
    max_module_lines: 1000
    max_cyclomatic_complexity: 15
    ban_broad_except: true
    ban_silent_except: true
    ban_duplicate_symbols: true
    track_file_growth: 0.15
    paths: ["src/**/*.py"]
    on_violation: kick

  test_integrity:
    enabled: true
    paths: ["tests/**", "**/test_*.py"]
    min_assertions_per_test: 1
    ban_trivial_assertions: true
    ban_mock_of_sut: true
    ban_uncalled_mock_assertions: true
    ban_swallowed_assertions: true
    ban_unconditional_skip: true
    max_mock_ratio: 0.70
    max_mock_ratio_severity: warning
    on_violation: kick

  type_evidence:
    enabled: true
    paths: ["src/**/*.py"]
    ban_any_parameters: true
    ban_any_returns: true
    ban_any_aliases: true
    ban_chained_casts: true
    ban_widen_then_cast: true
    ban_adhoc_isinstance: warning
    require_safety_comment: true
    ban_unexplained_type_ignore: true
    new_code_only: true
    baseline: auto
    on_violation: kick

  comments:
    enabled: true
    paths: ["src/**/*.py", "tests/**/*.py"]
    ban_obvious_comments: warning
    ban_step_comments: warning
    ban_placeholder_comments: error
    require_suppression_reason: true
    require_suppression_code: true
    stub_policy: warning
    allow_patterns: ["SAFETY:", "Wire format:", "Mutex order:"]
    on_violation: kick

  architecture:
    enabled: true
    layers:
      core: ["src/core/**"]
      services: ["src/services/**"]
      ui: ["src/ui/**"]
    allow:
      core: ["stdlib"]
      services: ["core", "stdlib"]
      ui: ["services", "core", "stdlib"]
    detect_cycles: true
    type_checking: ignore
    on_violation: kick

  dead_code:
    enabled: true
    private_only: true
    unused_imports: true
    public_api: warning
    baseline: auto
    on_violation: kick

  dependencies:
    enabled: true
    allow: ["stdlib", "pytest", "waker-ai"]
    allow_new: false
    check_manifests: true
    pypi_lookup: false
    pinning: required
    on_violation: kick

  security:
    enabled: true
    ban: ["eval", "exec", "pickle", "shell=True", "yaml.load", "verify=False"]
    on_violation: kick
```

`anti_slop` at the top level remains accepted as an alias for
`gates.anti_slop` in v1.x/v2.0; `gates` is canonical. Per-family `on_violation`
overrides the global policy. A family with `enabled: false` is omitted from
the run and from `waker lint` blocking (but still shown by
`waker audit --all-gates` if explicitly requested).

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
- `EngineConfig` gets `gates: GatesConfig` (with `anti_slop` as an alias);
  built from the global `gates` block + `kind: anti_slop` constraints, with
  per-task overrides.
- Each family gets its own immutable config dataclass
  (`AntiSlopConfig`, `TestIntegrityConfig`, `ArchitectureConfig`,
  `DeadCodeConfig`, `DependencyConfig`, `SecurityConfig`) and a
  `QualityConfig` aggregate.
- `PlanBundle` gets `gates: dict[str, Any]`.
- `Observation` gets `quality_families: dict[str, FamilySummary]` and
  `quality_abort: bool` in addition to the flat `slop_*` fields.
- `RunState` persists the normalized config + its hash, so resume is
  deterministic across releases.

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

Each finding carries a `family` (`anti_slop`, `test_integrity`,
`architecture`, `dead_code`, `dependencies`, `security`). The engine keeps a
per-family summary:

```python
@dataclass
class FamilySummary:
    family: str
    errors: int
    warnings: int
    findings: list[Finding]
    abort: bool = False
```

`SLOP` remains the umbrella diagnosis. The wake prompt is grouped by family so
the agent sees one prioritized list, not six disconnected streams.

Gate order (cheap AST first, then expensive execution):

1. Syntax/parse errors (`SLOP000`) and tamper/vault checks.
2. Security blocklist (`SEC*`) — do not run untrusted shell/test code first.
3. Test integrity (`TEST*`) on changed test files, if tests are writable in the
   contract; if Waker’s `test_globs` protects tests, only audit/report.
4. Architecture, dead code, dependencies (`ARCH*`, `DEAD*`, `PKG*`).
5. Anti-slop (`SLOP*`).
6. Public `verify`, then hidden tests.
7. `DONE` only when all enabled families are green.

A family marked `warning` contributes to the report but not to
`obs.slop_ok`. A family marked `abort` sets `quality_abort=True`, which maps to
terminal `SLOP`/exit 6 after the finding is recorded.

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

`on_violation` is resolved **per family**, with a global fallback. A strict
security profile can set `security.on_violation: abort` while
`dead_code.on_violation: kick`; `test_integrity` and `architecture` default to
`kick`. A revert from one family must not silently undo another family’s
valid fix; record the family and checkpoint in the event.

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
waker audit --gates anti_slop,test_integrity,architecture
waker audit --tests --architecture --dead-code --deps --security
waker audit --all-gates             # every family, read-only
waker check --anti-slop             # core family only
waker check --gates all             # CI/pre-commit gate for every family
waker gate rules                    # list rule IDs/defaults
waker gate explain TEST003          # rule docs + examples
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

### 8.2 Release train

| Version | Content | Default |
|---|---|---|
| **v2.0.0** | default-on for new `version: 2` contracts; core + test + type-evidence + comments + architecture + dead-code + dependencies + security families; rollback policies | on for new contracts |
| **v2.1.0** | API/async/coupling rules, JS/TS plugin interface, hunk-level revert, mutation/coverage adapters | opt-in |

If a single major release is required, ship **v2.0.0** and keep `v1.2.x`
maintained for one release cycle.

### 8.3 Migration

- v1.x `constraints` with `check`/`verify` remain valid.
- v2 accepts schema v1 contracts; `waker lint` prints a migration hint.
- New `gates` block is default-on for new `version: 2` contracts in v2; top-level
  `anti_slop` remains an alias.
- Existing repos can opt out per family with `<family>.enabled: false` or the
  global `WAKER_QUALITY_GATE=0`.
- Baseline old violations with `waker audit --write-baseline --all-gates`
  before enabling blocking; this is the recommended onboarding path.
- `waker doctor` reports: gate version, enabled families, files scanned,
  baseline age, and whether the gate is enabled.

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
- `tests/fixtures/guardians/tests_fake/` — no-assert, `assert True`,
  mock-the-SUT, uncalled mock assertion, swallowed assertion, unconditional
  skip.
- `tests/fixtures/guardians/tests_real/` — meaningful assertions, specific
  `pytest.raises`, property-based test (allowed), integration marker.
- `tests/fixtures/guardians/types/` — `Any` params/returns, chained casts,
  widen-then-cast, unexplained `# type: ignore`, ad-hoc `isinstance`, safe
  `TypeGuard`/boundary parsing (allowed).
- `tests/fixtures/guardians/comments/` — obvious/narrator/step/placeholder
  comments, valid why-comments, suppression with/without reason.
- `tests/fixtures/guardians/architecture/` — core→ui inversion, cycle,
  `TYPE_CHECKING` false positive.
- `tests/fixtures/guardians/dead_code/` — unused private function, unused
  import, public API (must not flag), framework hook (must not flag).
- `tests/fixtures/guardians/deps/` — stdlib, first-party, allowlisted third
  party, blocked package, new manifest dep, unpinned dep.
- `tests/fixtures/guardians/security/` — eval/exec, pickle, shell=True,
  yaml.load, verify=False, secret fixture (must be redacted).

### 9.2 Tests

- Unit: each rule; line/column/fingerprint stability; severity; suppression.
- Test integrity: no-assert, tautology, mock-the-SUT, uncalled mock assert,
  swallowed assert, skip/xfail; real tests and property-based tests must pass;
  mock-ratio warning must not block.
- Type evidence: `Any`/`object` params/returns, chained casts, widen-then-cast,
  unexplained `# type: ignore`, ad-hoc `isinstance`; `TypeGuard`/boundary
  parsing and safety-commented casts pass; new-code-only baseline works.
- Comments/suppression: obvious/step/placeholder comments; valid why-comments
  pass; suppression without reason/code fails; stub warnings.
- Architecture: forbidden layer, cycle, `TYPE_CHECKING` false positive,
  baseline; dynamic import warning.
- Dead code: private unused blocks; public API/framework/entry point/`.pyi`
  and `__all__` are not flagged; unused import exemptions.
- Dependencies: stdlib/first-party/allowlist mapping (`yaml` → PyYAML),
  blocked import, manifest diff, unpinned warning, offline mode.
- Security: all `SEC*` patterns; secret redaction; test fixture exemptions.
- False positives: overloads, property setters, conditional definitions,
  optional imports, dataclasses, `__init__.py` re-exports, framework hooks.
- Config: defaults, overrides, invalid values, unknown keys, path/exclude,
  family `enabled`/`on_violation`.
- Baseline: write/read, stale fingerprints, new vs old findings.
- Engine: `SLOP` at kick 0 → clean at kick 1 with a fake agent; `DONE` requires
  `slop_ok`; `kick`/`revert`/`abort`; no false `TAMPER` from the gate cache.
- CLI: exit codes, JSON schema, SARIF, TTY vs pipe, `--strict`, `--all`,
  `--gates`, family selectors.
- Performance: 200 changed files under the soft budget; cache hit avoids parse;
  `--all` on a 2,000-file tree.
- Cross-platform: Windows/Linux; no console windows; UTF-8 and cp1252 fallback.
- Security: symlink escape, huge file, invalid syntax, non-UTF8, no execution.

### 9.3 Acceptance

- [ ] `waker audit` finds the fixture slop and returns 2.
- [ ] Clean fixture returns 0; no network.
- [ ] `waker run` rejects a slop-producing fake agent (`SLOP`), wakes it, then
  accepts a clean turn (`DONE`).
- [ ] Fake test fixture is rejected (`TEST003`); real/property-based tests pass.
- [ ] `Any`/chained-cast fixture is rejected (`TYPE001`/`TYPE004`);
  `TypeGuard`/boundary parsing and safety-commented casts pass.
- [ ] Unexplained `# type: ignore` is rejected (`TYPE008`); a scoped,
  reasoned suppression passes.
- [ ] Placeholder comment fails (`COMMENT003`); a wire-format/why comment and a
  reasoned suppression pass.
- [ ] Core→UI import is rejected (`ARCH001`); a cycle is rejected (`ARCH002`);
  `TYPE_CHECKING` alone does not create a cycle.
- [ ] Private unused function is rejected (`DEAD001`); public API/framework hook
  is not; unused import is flagged; `__all__` re-export is not.
- [ ] Blocked package (`PKG001`) and new manifest dep (`PKG002`) fail; stdlib
  and allowlisted packages pass offline.
- [ ] Security fixture fails with redacted output; intentional test `eval` can
  be suppressed with a reason.
- [ ] Baseline suppresses legacy findings; only new ones block.
- [ ] `waker status --format json` exposes per-family quality counts; stdout
  remains parseable when the update banner is enabled.
- [ ] `pytest` green on Windows and Linux; no new runtime dependencies.
- [ ] A v1.x contract still runs unchanged.

---

## 10. Risks and decisions

| Risk | Mitigation |
|---|---|
| False positives (metaprogramming, generated code) | baseline, exclusions, suppression with reason, warn-first rollout |
| Duplicate detection noise | scope-aware, decorator/platform exemptions, thresholds, cross-file only for copy-paste |
| Test guard false positives (property tests, integration mocks) | confidence tiers, markers/overrides, mutation testing as optional proof |
| Type-evidence false positives (dynamic code, legacy `Any`) | new-code-only, baseline, `TypeGuard`/boundary allowlist, safety-comment escape |
| Comment-style subjectivity | warning-first, allow why-comments, block only placeholders/unexplained suppression |
| Suppression fatigue | require narrow code + reason; baseline legacy suppressions; no blanket rules |
| Mock ratio treated as a defect | warning/info only; structural fake-test rules block |
| Architecture false positives (`TYPE_CHECKING`, lazy/dynamic imports) | type-only edges separate, allowlist, baseline, warning for dynamic |
| Dead-code false positives (public API, framework hooks) | private-only + confidence + entry-point/framework/`.pyi` exemptions |
| Package mapping errors (`yaml` vs PyYAML) | `importlib.metadata`, `sys.stdlib_module_names`, allowlist, offline mode |
| Security false positives (intentional test fixtures) | path exemptions, suppression reason, secret redaction |
| God-function threshold subjective | configurable per task; baseline; warn for 100–150, error >150? default 100 error |
| Rollback destroys valid work | default `kick`; `revert` opt-in + file-scoped; log every revert |
| Python-only AST | state clearly; external commands for other languages; future plugin |
| Performance on huge diffs | changed-only, content-hash cache, limits, soft timeout |
| Gate bug bricks runs | scanner errors are non-fatal; tests + fallback to verify-only |
| “Slop” becomes a style war | rule IDs are narrow and mechanical; no formatting/naming rules |
| v2 breaks existing contracts | v2 default-on with schema v1 accepted, baseline, env/family opt-out, v1.2 pin |

**Key decisions:**

1. Default `on_violation: kick`, not rollback. Rejecting the turn is a soft
   rollback; destructive file restore must be explicit.
2. Quality is blocking only for **new** findings; legacy is baselined.
3. `waker.gate` is stdlib-only; Rich stays in the CLI layer.
4. Python AST only in v2; no false multi-language claims.
5. Current version is v1.2.0; the Guardian ships directly in **v2.0.0**;
   Phase 1 is the read-only `waker audit` preview.
6. Mock ratio is a **warning**, never a hard defect; the hard test rules are
   structural false-green facts.
7. Import direction is **explicit config**, not a universal “core only stdlib”.
8. Dead code is **private-only + confidence** by default; public API and
   framework hooks are warnings/exemptions.
9. New dependencies require explicit approval (`allow_new: false`) in strict
   repos; package resolution uses `importlib.metadata`, not guesses.
10. Security findings are high-confidence blocks; secret values are always
    redacted.

---

## 11. Implementation phases

| Phase | Deliverable | Exit criteria |
|---|---|---|
| 0 | This spec + rule IDs + fixtures | reviewed |
| 1 | `waker.gate` core + `waker audit` read-only | unit tests, clean/slop fixtures |
| 2 | Test-integrity + type-evidence + comment scanners in `audit` | false-positive fixtures, JSON/SARIF |
| 3 | Contract schema + engine `SLOP` + wake prompt | fake-agent E2E, no regression |
| 4 | Dead-code + dependency + security scanners | fixtures, redaction, offline mode |
| 5 | Baseline, suppression, TUI/status, perf budget | CLI acceptance, 200-file scan |
| 6 | v2.0.0 default-on release | PyPI, update notifier, docs |
| 7 | v2.1 optional extensions | JS/TS adapter, score refinements, auto-fix only after review |

---

## Appendix A — Example engine observation

```python
obs = Observation(
    ...,
    slop_ok=False,
    slop_blocking=3,
    slop_warnings=2,
    slop_findings=[
        {"rule": "TEST003", "family": "test_integrity", "path": "tests/test_pay.py", ...},
        {"rule": "ARCH001", "family": "architecture", "path": "src/core/engine.py", ...},
        {"rule": "SLOP002", "family": "anti_slop", "path": "src/pay.py", "line": 42, ...},
    ],
    quality_families={
        "test_integrity": {"errors": 1, "warnings": 0},
        "architecture": {"errors": 1, "warnings": 0},
        "anti_slop": {"errors": 1, "warnings": 2},
    },
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

# extended families (v2 default)
test_integrity.min_assertions_per_test   1
test_integrity.max_mock_ratio            0.70 (warning)
test_integrity.ban_mock_of_sut           true
architecture.detect_cycles               true
architecture.type_checking               ignore
dead_code.private_only                   true
dead_code.unused_imports                 true
dependencies.allow_new                   false
dependencies.pypi_lookup                 false
security.ban                             eval, exec, pickle, shell=True, yaml.load, verify=False
type_evidence.new_code_only              true
type_evidence.ban_any_parameters         true
type_evidence.ban_adhoc_isinstance       warning
comments.ban_obvious_comments            warning
comments.ban_placeholder_comments        error
comments.require_suppression_reason      true
```
