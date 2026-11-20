"""CLI entrypoint.

Commands: plan | lint | run | start | stop | serve | status | watch | report |
install-skill
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, planner, update
from . import doctor as doctor_module
from .budget import PROFILE_NAMES, parse_duration, resolve_profile
from .adapters.claude import ClaudeAdapter
from .adapters.generic import GenericProcessAdapter
from .adapters.opencode import OpenCodeAdapter
from .adapters.pty import PtyAdapter
from .daemon import serve, start_detached, stop_run
from .dashboard import serve_dashboard, write_static
from .engine import Engine, EngineConfig
from .gate import AntiSlopConfig, baseline_path, scan_paths, write_baseline
from .gate.sarif import to_sarif
from .models import Task
from .skill_install import PROVIDERS, install_skill
from .state import (
    RunPaths,
    RunState,
    latest_run,
    new_run_id,
    read_json,
    run_is_active,
    run_lock_pid,
)
from .ui import load_latest, render_markdown, watch as watch_run
from .vault import Vault
from .vault_validate import validate_vault


def _parse_bundle(args) -> planner.PlanBundle:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8-sig")
    elif args.prompt:
        text = args.prompt
    else:
        raise SystemExit("requires --prompt or --file")
    if args.via == "rules":
        return planner.parse_prompt(text)
    from .llm_plan import generate_contract

    try:
        return generate_contract(
            text, args.repo, model=args.model, binary=args.binary
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"planner error: {exc}")


def _runtime_settings(args) -> dict[str, float | int | str]:
    """Resolve a profile and let explicit CLI values win."""
    profile_name = getattr(args, "profile", None) or "medium"
    profile = resolve_profile(profile_name)

    def pick(field: str) -> float | int:
        raw = getattr(args, field, None)
        return getattr(profile, field) if raw is None else raw

    return {
        "profile": profile.name,
        "max_kicks": pick("max_kicks"),
        "turn_timeout": pick("turn_timeout"),
        "verify_timeout": pick("verify_timeout"),
        "freeze_after": pick("freeze_after"),
        "max_wall_clock": pick("max_wall_clock"),
    }


def _load_contract(args) -> planner.PlanBundle:
    if not getattr(args, "tasks", None) and not getattr(args, "prompt", None):
        raise SystemExit("requires --tasks or --prompt")
    return planner.load_contract(getattr(args, "tasks", None), getattr(args, "prompt", None))


def _lint_or_fail(args, bundle: planner.PlanBundle) -> int | None:
    issues = planner.lint_contract(bundle, repo=args.repo)
    if issues:
        print(planner.format_issues(issues), file=sys.stderr)
    if issues and not getattr(args, "no_lint", False) and planner.has_errors(issues):
        print("Invalid contract - stopping (fail closed).", file=sys.stderr)
        return 2
    return None


def _build_adapter(args):
    adapter = args.adapter or "generic"
    if adapter == "opencode":
        return OpenCodeAdapter(model=args.model, binary=args.binary or "opencode")
    if adapter == "claude":
        return ClaudeAdapter(
            binary=args.binary or "claude",
            permission_mode=args.permission_mode or "acceptEdits",
        )
    if adapter == "pty":
        if not args.agent:
            raise SystemExit("--agent is required with --adapter pty")
        return PtyAdapter(args.agent)
    if not args.agent:
        raise SystemExit("--agent is required with --adapter generic")
    return GenericProcessAdapter(args.agent)


def cmd_plan(args) -> int:
    bundle = planner.apply_phase_mode(
        _parse_bundle(args),
        getattr(args, "phases", "none"),
        getattr(args, "profile", None),
    )
    if getattr(args, "via", "rules") == "rules":
        work = [task for task in bundle.tasks if task.kind == "work"]
        if len(work) >= 6 and not any(task.scope for task in work):
            print(
                "\n# Hint: this prompt looks like prose/an instruction, not a "
                "task list. Use `--via opencode` to let a model fill scope/verify.",
                file=sys.stderr,
            )
    out = Path(args.out)
    planner.write_tasks(out, bundle)
    if args.json:
        print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(planner.render_yaml(bundle))
    issues = planner.lint_contract(bundle, repo=args.repo)
    if issues:
        print("\n# lint", file=sys.stderr)
        print(planner.format_issues(issues), file=sys.stderr)
    print(f"\n# wrote {out}", file=sys.stderr)
    return 2 if planner.has_errors(issues) else 0


def cmd_lint(args) -> int:
    bundle = planner.load_contract(args.tasks)
    issues = planner.lint_contract(bundle, repo=args.repo)
    print(planner.format_issues(issues))
    return 2 if planner.has_errors(issues) else 0


def cmd_run(args) -> int:
    if args.resume:
        paths = RunPaths(args.repo, args.resume)
        state = RunState.load(paths.state)
        adapter = None
        if args.adapter is not None or args.agent is not None:
            adapter = _build_adapter(args)
        engine = Engine.from_run(
            args.repo, args.resume, adapter=adapter, max_kicks=args.max_kicks
        )
        engine.config.slop_baseline = args.slop_baseline
        result = engine.run()
        print(render_markdown(RunState.load(paths.state), read_json(paths.ledger)))
        print(f"\nreport: {result.report_path}")
        print(f"result: {result.diagnosis.value} (exit {result.exit_code})")
        return result.exit_code

    bundle = _load_contract(args)
    tasks, constraints = bundle.tasks, bundle.constraints
    failed = _lint_or_fail(args, bundle)
    if failed is not None:
        return failed
    if any(task.blind for task in tasks) and not args.vault:
        print(
            "task has `blind` but no `--vault <id>`; stopping (fail closed).",
            file=sys.stderr,
        )
        return 2
    adapter_name = args.adapter or "generic"
    settings = _runtime_settings(args)
    config = EngineConfig(
        repo=args.repo,
        tasks=tasks,
        constraints=constraints,
        agent_command=args.agent or f"opencode:{args.model or 'default'}",
        test_command=args.test,
        prompt=args.prompt or "",
        contract_path=args.tasks,
        max_kicks=int(settings["max_kicks"]),
        profile=str(settings["profile"]),
        phases=bundle.phases,
        turn_timeout=float(settings["turn_timeout"]),
        verify_timeout=float(settings["verify_timeout"]),
        freeze_after=float(settings["freeze_after"]),
        max_wall_clock=float(settings["max_wall_clock"]),
        max_cost_usd=args.max_cost,
        freeze_probe=not args.no_freeze_probe,
        use_job=not args.no_job,
        full_suite_every=args.full_suite_every,
        adapter_name=adapter_name,
        model=args.model,
        permission_mode=args.permission_mode or "acceptEdits",
        binary=args.binary,
        vault_id=args.vault,
        vault_dir=args.vault_dir,
        run_id=args.run_id,
        slop_baseline=args.slop_baseline,
    )
    result = Engine(config, _build_adapter(args)).run()
    paths = RunPaths(args.repo, result.run_id)
    print(render_markdown(RunState.load(paths.state), read_json(paths.ledger)))
    print(f"\nreport: {result.report_path}")
    print(f"result: {result.diagnosis.value} (exit {result.exit_code})")
    return result.exit_code


def _run_flags(args) -> list[str]:
    flags: list[str] = ["--repo", str(Path(args.repo).resolve())]
    if args.resume:
        flags.extend(["--resume", args.resume])
    else:
        for flag, value in (("--tasks", args.tasks), ("--prompt", args.prompt)):
            if value not in (None, ""):
                flags.extend([flag, str(value)])
    for flag, value in (
        ("--test", args.test),
        ("--agent", args.agent),
        ("--model", args.model),
        ("--binary", args.binary),
        ("--permission-mode", args.permission_mode),
        ("--vault", args.vault),
        ("--vault-dir", args.vault_dir),
    ):
        if value not in (None, ""):
            flags.extend([flag, str(value)])
    if args.adapter:
        flags.extend(["--adapter", args.adapter])
    settings = _runtime_settings(args)
    flags.extend(["--profile", str(settings["profile"])])
    flags.extend(["--max-kicks", str(settings["max_kicks"])])
    flags.extend(["--turn-timeout", str(settings["turn_timeout"])])
    flags.extend(["--verify-timeout", str(settings["verify_timeout"])])
    flags.extend(["--freeze-after", str(settings["freeze_after"])])
    flags.extend(["--max-wall-clock", str(settings["max_wall_clock"])])
    flags.extend(["--full-suite-every", str(args.full_suite_every)])
    if args.max_cost:
        flags.extend(["--max-cost", str(args.max_cost)])
    if args.no_freeze_probe:
        flags.append("--no-freeze-probe")
    if args.no_job:
        flags.append("--no-job")
    if args.no_lint:
        flags.append("--no-lint")
    if not args.slop_baseline:
        flags.append("--no-baseline")
    return flags


def cmd_resume(args) -> int:
    extend_seconds: float | None = None
    if args.extend:
        try:
            extend_seconds = parse_duration(args.extend)
        except (TypeError, ValueError) as exc:
            print(f"invalid --extend duration: {exc}", file=sys.stderr)
            return 2
        if extend_seconds <= 0:
            print("invalid --extend duration: must be > 0", file=sys.stderr)
            return 2
    try:
        engine = Engine.from_run(
            args.repo,
            args.run_id,
            extend_seconds=extend_seconds,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = engine.run()
    paths = RunPaths(args.repo, result.run_id)
    print(render_markdown(RunState.load(paths.state), read_json(paths.ledger)))
    print(f"\nreport: {result.report_path}")
    print(f"result: {result.diagnosis.value} (exit {result.exit_code})")
    return result.exit_code


def cmd_start(args) -> int:
    if not args.resume:
        bundle = _load_contract(args)
        tasks, constraints = bundle.tasks, bundle.constraints
        failed = _lint_or_fail(args, bundle)
        if failed is not None:
            return failed
        if any(task.blind for task in tasks) and not args.vault:
            print(
                "task has `blind` but no `--vault <id>`; stopping (fail closed).",
                file=sys.stderr,
            )
            return 2
    run_id = args.resume or args.run_id or new_run_id()
    paths = RunPaths(args.repo, run_id)
    if run_is_active(paths):
        print(
            f"run {run_id} is active (pid {run_lock_pid(paths)}); "
            "stop it before starting/resuming again.",
            file=sys.stderr,
        )
        return 2
    record = start_detached(args.repo, _run_flags(args), run_id)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"\nRunning in the background. Track: waker status --repo {args.repo} --run {run_id}")
    print(f"Live view: waker watch --repo {args.repo}")
    return 0


def cmd_stop(args) -> int:
    stopped = stop_run(args.repo, args.run)
    print("stopped" if stopped else "no active run found")
    return 0 if stopped else 1


def cmd_serve(args) -> int:
    serve(args.repo, host=args.host, port=args.port)
    return 0


def cmd_install_skill(args) -> int:
    target = install_skill(args.provider, args.dir, global_=args.global_)
    print(f"installed skill for {args.provider}: {target}")
    return 0


def _providers_from(tools, home: Path) -> list[str]:
    found = {tool.name: tool.found for tool in tools}
    providers = [name for name in ("opencode", "claude", "gemini") if found.get(name)]
    if providers:
        return providers
    # No CLI on PATH: fall back to existing config dirs (e.g. a wrapper install).
    return [
        name
        for name, folder in (
            ("opencode", ".opencode"),
            ("claude", ".claude"),
            ("gemini", ".gemini"),
        )
        if (home / folder).exists()
    ]


def cmd_setup(args) -> int:
    from .doctor import detect_tools

    providers = list(args.providers or [])
    if not providers:
        providers = _providers_from(detect_tools(), Path.home())
    if not providers:
        print(
            "No CLI detected. Use --for opencode|claude|gemini|generic.",
            file=sys.stderr,
        )
        return 1

    installed = []
    for provider in dict.fromkeys(providers):
        if args.dry_run:
            print(f"[dry-run] would install skill for {provider}")
            continue
        target = install_skill(provider, args.dir, global_=not args.local)
        print(f"{provider}: {target}")
        installed.append(target)

    if installed:
        print(
            "\nDone. Restart the chat/OpenCode session so the `waker` skill is loaded."
        )
        print("Live progress: waker watch")
        print('Or ask "progress" in chat — the agent will paste the status table.')
    return 0


def cmd_status(args) -> int:
    if args.run:
        paths = RunPaths(args.repo, args.run)
        state = RunState.load(paths.state)
        ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
    else:
        state, ledger, _ = load_latest(args.repo)
    if args.format == "json":
        payload = {
            "run_id": state.run_id,
            "status": state.status,
            "diagnosis": state.diagnosis,
            "kicks": state.kicks,
            "max_kicks": state.max_kicks,
            "profile": state.profile,
            "elapsed": round(state.elapsed, 1),
            "timeouts": {
                "turn_timeout": state.turn_timeout,
                "max_wall_clock": state.max_wall_clock,
                "verify_timeout": state.verify_timeout,
                "freeze_after": state.freeze_after,
            },
            "cost_usd": round(state.cost_usd, 6),
            "max_cost_usd": state.max_cost_usd,
            "tasks": ledger.get("tasks", {}),
            "test": ledger.get("test", {}),
            "quality": ledger.get("quality", {}),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(state, ledger))
    return 0


def cmd_watch(args) -> int:
    if args.window:
        from .ui import open_watch_window

        if open_watch_window(args.repo, args.run, no_fx=args.no_fx, hold=True):
            print("Waker Cyber-Deck opened in a separate terminal.")
            return 0
        print("could not open a separate window; falling back to this terminal.", file=sys.stderr)
    try:
        watch_run(
            args.repo,
            args.run,
            interval=args.interval,
            no_fx=args.no_fx,
            mini=args.mini,
            hold=getattr(args, "hold", False),
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_doctor(args) -> int:
    return doctor_module.report(as_json=args.json, inject_test=args.inject_test)


def cmd_dashboard(args) -> int:
    if args.out:
        target = write_static(args.repo, args.out, args.run)
        print(f"dashboard: {target}")
        return 0
    serve_dashboard(
        args.repo,
        run_id=args.run,
        host=args.host,
        port=args.port,
        open_browser=args.open_browser,
    )
    return 0


def cmd_detect(args) -> int:
    from .detect import detect_test_commands

    results = detect_test_commands(args.repo)
    if args.json:
        print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
    elif not results:
        print(
            "no test runner detected. Use --test to specify one.",
            file=sys.stderr,
        )
    else:
        for item in results:
            print(f"{item.confidence:3d}%  {item.command:<24} ({item.source})")
    return 0 if results else 1


def _audit_exit(result, strict: bool) -> int:
    if result.errors:
        return 1
    if result.errors_count or (strict and result.warnings_count):
        return 2
    return 0


def cmd_audit(args) -> int:
    base = AntiSlopConfig()
    overrides: dict = {}
    baseline_ref = args.baseline or "HEAD"
    baseline_file = args.baseline_file
    if baseline_file is None and str(baseline_ref).lower().endswith(".json"):
        baseline_file = baseline_ref
        baseline_ref = "HEAD"
    if args.max_function_lines is not None:
        overrides["max_function_lines"] = args.max_function_lines
    if args.max_module_lines is not None:
        overrides["max_module_lines"] = args.max_module_lines
    if args.max_complexity is not None:
        overrides["max_cyclomatic_complexity"] = args.max_complexity
    if args.max_nesting is not None:
        overrides["max_nesting_depth"] = args.max_nesting
    if args.max_parameters is not None:
        overrides["max_parameters"] = args.max_parameters
    if args.paths:
        overrides["paths"] = tuple(args.paths)
    if args.exclude:
        overrides["exclude"] = (*base.exclude, *args.exclude)
    if baseline_file:
        overrides["baseline"] = baseline_file
    if args.no_baseline:
        overrides["baseline"] = "off"
    if args.tests:
        overrides["enable_tests"] = True
    if args.types:
        overrides["enable_types"] = True
    if args.comments:
        overrides["enable_comments"] = True
    if args.arch:
        overrides["enable_arch"] = True
    if args.dead_code:
        overrides["enable_dead_code"] = True
    if args.deps:
        overrides["enable_deps"] = True
    if args.security:
        overrides["enable_security"] = True
    if args.all_gates:
        overrides["enable_core"] = True
        overrides["enable_tests"] = True
        overrides["enable_types"] = True
        overrides["enable_comments"] = True
        overrides["enable_arch"] = True
        overrides["enable_dead_code"] = True
        overrides["enable_deps"] = True
        overrides["enable_security"] = True
    try:
        config = base.with_overrides(**overrides)

        def scan_now():
            return scan_paths(
                args.repo,
                paths=args.paths,
                config=config,
                changed_only=not args.all,
                baseline_ref=baseline_ref,
                use_baseline=not args.no_baseline,
            )

        result = scan_now()
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.fix:
        from .gate import fix_paths

        fixes = fix_paths(args.repo, result.findings, dry_run=args.dry_run)
        changed = [item for item in fixes if item.changed]
        label = "would fix" if args.dry_run else "fixed"
        print(f"autofix: {label} {len(changed)} file(s)", file=sys.stderr)
        if changed and not args.dry_run:
            result = scan_now()

    if args.external:
        from . import evidence as evidence_module
        from .gate import badge_markdown, grade_for, score_findings
        from .gate.external import run_external_linters

        if args.paths:
            external_files = list(args.paths)
        elif args.all:
            external_files = [
                str(path.relative_to(Path(args.repo).resolve()))
                for path in Path(args.repo).resolve().rglob("*")
                if path.is_file()
            ]
        else:
            try:
                external_files = evidence_module.changed_files(args.repo, baseline_ref)
            except OSError:
                external_files = []
        external = run_external_linters(args.repo, external_files)
        result.findings.extend(external.findings)
        for message in external.errors:
            print(f"external: {message}", file=sys.stderr)
        result.score = score_findings(result.actionable)
        result.grade = grade_for(result.score)
        result.badge = badge_markdown(result.score)

    if result.errors:
        for message in result.errors:
            print(f"scan error: {message}", file=sys.stderr)

    if args.write_baseline:
        target = baseline_path(args.repo, config)
        if target is None:
            print("error: baseline is disabled (--no-baseline)", file=sys.stderr)
            return 3
        write_baseline(target, result.findings)
        print(f"baseline: {target}")
        print(f"wrote {len(result.findings)} finding(s)")
        return 0

    if args.format == "badge":
        print(result.badge)
        return _audit_exit(result, args.strict)
    if args.badge:
        print(result.badge)
        return _audit_exit(result, args.strict)
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.format == "sarif":
        print(json.dumps(to_sarif(result), ensure_ascii=False, indent=2))
    else:
        actionable = [finding for finding in result.findings if not finding.baseline]
        print(
            f"Anti-Slop Audit — {len(actionable)} finding(s) "
            f"({result.errors_count} blocking, {result.warnings_count} warning)"
        )
        print(f"Cleanliness: {result.score}/100 ({result.grade})")
        if result.files_scanned or result.files_skipped:
            print(
                f"Files: {result.files_scanned} scanned, "
                f"{result.files_skipped} skipped · {result.duration_ms} ms"
            )
        if result.baseline_suppressed:
            print(f"Baseline: {result.baseline_suppressed} legacy finding(s) suppressed")
        order = {"error": 0, "warning": 1, "info": 2}
        actionable.sort(
            key=lambda finding: (
                order.get(finding.severity, 3),
                finding.path,
                finding.line,
                finding.rule,
            )
        )
        for finding in actionable:
            print(
                f"{finding.path}:{finding.line}:{finding.col}  "
                f"{finding.rule}  {finding.severity}  {finding.message}"
            )
            if finding.suggestion:
                print(f"  Fix: {finding.suggestion}")
        print(result.badge)
    return _audit_exit(result, args.strict)


def cmd_vault_init(args) -> int:
    vault = Vault.create(args.repo, vault_id=args.id, base_dir=args.vault_dir)
    payload = {
        "vault_id": vault.vault_id,
        "path": str(vault.path),
        "repo": vault.manifest["repo"],
        "created_at": vault.manifest["created_at"],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"vault_id : {vault.vault_id}")
        print(f"path     : {vault.path}")
        print(f"repo     : {vault.manifest['repo']}")
    return 0


def cmd_vault_add(args) -> int:
    vault = Vault.load(args.vault, base_dir=args.vault_dir)
    entry = vault.add_suite(
        args.suite,
        args.files,
        task=args.task,
        baseline=args.baseline,
        timeout=args.timeout,
        leak=args.leak,
    )
    payload = {
        "vault_id": vault.vault_id,
        "suite": args.suite,
        "files": [item["name"] for item in entry["files"]],
        "hash": entry["hash"],
        "baseline": entry["baseline"],
        "leak": entry["leak"],
        "validated": False,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"suite    : {args.suite}")
        print(f"files    : {len(entry['files'])}")
        print(f"hash     : {entry['hash']}")
        print(f"baseline : {entry['baseline']}")
        print("validated: false (run `waker vault validate` before start)")
    return 0


def cmd_vault_list(args) -> int:
    vault = Vault.load(args.vault, base_dir=args.vault_dir)
    rows = vault.summary()
    if args.json:
        print(
            json.dumps(
                {
                    "vault_id": vault.vault_id,
                    "path": str(vault.path),
                    "repo": vault.manifest.get("repo"),
                    "suites": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not rows:
        print("(empty vault)")
        return 0
    print(f"{'suite':<16} {'task':<8} {'files':<6} {'hash':<18} {'validated':<10} leak")
    for row in rows:
        print(
            f"{row['suite']:<16} {str(row['task'] or '-'):<8} {row['files']:<6} "
            f"{row['hash']:<18} {str(row['validated']):<10} {row['leak']}"
        )
    return 0


def cmd_vault_rm(args) -> int:
    if not args.yes:
        print("use --yes to remove the suite from the vault", file=sys.stderr)
        return 2
    vault = Vault.load(args.vault, base_dir=args.vault_dir)
    removed = vault.remove_suite(args.suite)
    print(f"removed suite {args.suite}" if removed else f"no such suite {args.suite}")
    return 0 if removed else 1


def cmd_vault_validate(args) -> int:
    vault = Vault.load(args.vault, base_dir=args.vault_dir)
    results = validate_vault(vault, args.repo, suite=args.suite, runs=args.runs)
    payload = {
        "vault_id": vault.vault_id,
        "ok": all(result.ok for result in results),
        "results": [result.to_dict() for result in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for result in results:
            status = "OK" if result.ok else "FAIL"
            print(
                f"{status:<4} {result.suite:<16} tests={result.tests:<3} "
                f"baseline={result.baseline} flaky={result.flaky}"
            )
            for message in result.messages:
                print(f"     - {message}")
    return 0 if payload["ok"] else 1


def cmd_report(args) -> int:
    if args.run:
        paths = RunPaths(args.repo, args.run)
    else:
        run_id = latest_run(args.repo)
        if not run_id:
            print("no runs yet", file=sys.stderr)
            return 1
        paths = RunPaths(args.repo, run_id)
    if not paths.report.exists():
        print("no report yet", file=sys.stderr)
        return 1
    print(paths.report.read_text(encoding="utf-8", errors="replace"))
    return 0


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tasks")
    parser.add_argument("--prompt")
    parser.add_argument("--resume", default=None, help="run id to resume")
    parser.add_argument("--test", default=None)
    parser.add_argument("--agent", default=None, help="agent command for generic/pty adapter")
    parser.add_argument("--adapter", choices=["generic", "opencode", "claude", "pty"], default=None)
    parser.add_argument("--model", default=None, help="provider/model for OpenCode")
    parser.add_argument("--binary", default=None, help="CLI path (opencode/claude)")
    parser.add_argument("--permission-mode", default=None, help="Claude Code permission mode")
    parser.add_argument("--vault", default=None, help="hidden test vault id (blind)")
    parser.add_argument("--vault-dir", default=None, help="vault base dir (test/CI)")
    parser.add_argument(
        "--baseline",
        dest="slop_baseline",
        action="store_true",
        default=True,
        help="ignore pre-existing anti-slop debt in changed files (default)",
    )
    parser.add_argument(
        "--no-baseline",
        dest="slop_baseline",
        action="store_false",
        help="do not suppress pre-existing anti-slop debt",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--profile", choices=PROFILE_NAMES, default=None)
    parser.add_argument("--max-kicks", type=int, default=None)
    parser.add_argument("--max-cost", type=float, default=0.0, help="USD; 0 = disable cost guard")
    parser.add_argument("--full-suite-every", type=int, default=0, help="run the full suite every N kicks")
    parser.add_argument("--turn-timeout", type=float, default=None)
    parser.add_argument("--verify-timeout", type=float, default=None)
    parser.add_argument("--freeze-after", type=float, default=None)
    parser.add_argument("--max-wall-clock", type=float, default=None)
    parser.add_argument("--no-freeze-probe", action="store_true")
    parser.add_argument("--no-job", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--no-lint", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="waker",
        description="Watchdog & supervisor for AI coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"waker {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="turn a prompt into a contract (0 tokens)")
    plan.add_argument("--prompt")
    plan.add_argument("--file")
    plan.add_argument("--out", default=".waker/tasks.yaml")
    plan.add_argument("--repo", default=".")
    plan.add_argument("--via", "--planner", dest="via", choices=["rules", "opencode"], default="rules")
    plan.add_argument("--model", default=None)
    plan.add_argument("--binary", default=None)
    plan.add_argument(
        "--phases",
        choices=["none", "manual", "auto"],
        default="none",
        help="phase selection: none (one implicit P1), manual, or rule-based auto",
    )
    plan.add_argument(
        "--profile",
        choices=PROFILE_NAMES,
        default=None,
        help="timeout profile used for auto phase budgets",
    )
    plan.add_argument("--json", action="store_true", help="emit machine-readable plan JSON")
    plan.set_defaults(func=cmd_plan)

    lint = sub.add_parser("lint", help="validate the contract (0 tokens)")
    lint.add_argument("--tasks", required=True)
    lint.add_argument("--repo", default=".")
    lint.set_defaults(func=cmd_lint)

    run = sub.add_parser("run", help="run the supervisor in the foreground")
    _add_run_arguments(run)
    run.set_defaults(func=cmd_run)

    start = sub.add_parser("start", help="run the supervisor in the background (detached)")
    _add_run_arguments(start)
    start.add_argument("--detach", action="store_true", help="run detached (default)")
    start.set_defaults(func=cmd_start, detach=True)

    resume = sub.add_parser("resume", help="resume a timed-out run")
    resume.add_argument("run_id")
    resume.add_argument("--repo", default=".")
    resume.add_argument("--extend", default=None, help="extend the timed-out phase budget")
    resume.set_defaults(func=cmd_resume)

    stop = sub.add_parser("stop", help="stop the active run")
    stop.add_argument("--repo", default=".")
    stop.add_argument("--run")
    stop.set_defaults(func=cmd_stop)

    serve_parser = sub.add_parser("serve", help="HTTP daemon on loopback")
    serve_parser.add_argument("--repo", default=".")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=47821)
    serve_parser.set_defaults(func=cmd_serve)

    status = sub.add_parser("status", help="progress table")
    status.add_argument("--repo", default=".")
    status.add_argument("--run")
    status.add_argument("--format", choices=["md", "json"], default="md")
    status.set_defaults(func=cmd_status)

    watch = sub.add_parser("watch", help="live TUI (Rich Live)")
    watch.add_argument("--repo", default=".")
    watch.add_argument("--run")
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("--no-fx", action="store_true", help="disable cinema effects")
    watch.add_argument("--mini", action="store_true", help="print one plain status line and exit")
    watch.add_argument("--hold", action="store_true", help="wait for Enter after a completed static deck (TTY only)")
    watch.add_argument("--window", action="store_true", help="open the Cyber-Deck in a separate terminal (Windows)")
    watch.set_defaults(func=cmd_watch)

    report = sub.add_parser("report", help="in report.md")
    report.add_argument("--repo", default=".")
    report.add_argument("--run")
    report.set_defaults(func=cmd_report)

    detect_parser = sub.add_parser("detect", help="detect test runners in the repo")
    detect_parser.add_argument("--repo", default=".")
    detect_parser.add_argument("--json", action="store_true")
    detect_parser.set_defaults(func=cmd_detect)

    audit = sub.add_parser(
        "audit", help="read-only anti-slop audit and cleanliness score"
    )
    audit.add_argument(
        "--anti-slop",
        action="store_true",
        help="run the core anti-slop gate (default)",
    )
    audit.add_argument(
        "--all",
        action="store_true",
        help="scan every Python file instead of only changed files",
    )
    audit.add_argument(
        "--changed-only",
        action="store_true",
        help="scan changed files only (default)",
    )
    audit.add_argument(
        "--baseline",
        nargs="?",
        const="HEAD",
        default="HEAD",
        help="git revision for changed-file detection; a *.json value is treated as a baseline file",
    )
    audit.add_argument(
        "--baseline-file",
        default=None,
        help="baseline JSON path (default: .waker/anti-slop-baseline.json)",
    )
    audit.add_argument(
        "--no-baseline",
        action="store_true",
        help="ignore the baseline file",
    )
    audit.add_argument(
        "--write-baseline",
        action="store_true",
        help="write current findings to the baseline file",
    )
    audit.add_argument(
        "--format",
        choices=["md", "json", "badge", "sarif"],
        default="md",
    )
    audit.add_argument(
        "--badge",
        action="store_true",
        help="print only the Markdown badge",
    )
    audit.add_argument(
        "--tests",
        action="store_true",
        help="enable test-integrity rules (TEST001-008)",
    )
    audit.add_argument(
        "--types",
        action="store_true",
        help="enable type-evidence rules (TYPE001-012)",
    )
    audit.add_argument(
        "--comments",
        action="store_true",
        help="enable comment/suppression/stub rules",
    )
    audit.add_argument(
        "--arch",
        action="store_true",
        help="enable architecture/layer/import-cycle rules",
    )
    audit.add_argument(
        "--dead-code",
        action="store_true",
        help="enable dead-code and unused-import rules",
    )
    audit.add_argument(
        "--deps",
        action="store_true",
        help="enable package/dependency allowlist rules",
    )
    audit.add_argument(
        "--security",
        action="store_true",
        help="enable security rules",
    )
    audit.add_argument(
        "--all-gates",
        action="store_true",
        help="enable every anti-slop gate family",
    )
    audit.add_argument(
        "--fix",
        action="store_true",
        help="apply safe auto-fixes (TYPE007 safety note, single unused imports)",
    )
    audit.add_argument(
        "--dry-run",
        action="store_true",
        help="show auto-fix results without writing files",
    )
    audit.add_argument(
        "--external",
        action="store_true",
        help="run optional installed oxlint/eslint adapters for JS/TS files",
    )
    audit.add_argument(
        "--strict",
        action="store_true",
        help="make warnings exit 2 as well",
    )
    audit.add_argument("--paths", action="append", default=None)
    audit.add_argument("--exclude", action="append", default=None)
    audit.add_argument("--max-function-lines", type=int, default=None)
    audit.add_argument("--max-module-lines", type=int, default=None)
    audit.add_argument("--max-complexity", type=int, default=None)
    audit.add_argument("--max-nesting", type=int, default=None)
    audit.add_argument("--max-parameters", type=int, default=None)
    audit.add_argument("--repo", default=".")
    audit.set_defaults(func=cmd_audit)

    vault_parser = sub.add_parser("vault", help="Hidden test vault (blind evaluation)")
    vault_sub = vault_parser.add_subparsers(dest="vault_command", required=True)

    v_init = vault_sub.add_parser("init", help="create a vault outside the repo")
    v_init.add_argument("--repo", default=".")
    v_init.add_argument("--id", default=None)
    v_init.add_argument("--vault-dir", default=None)
    v_init.add_argument("--json", action="store_true")
    v_init.set_defaults(func=cmd_vault_init)

    v_add = vault_sub.add_parser("add", help="add test files to a suite")
    v_add.add_argument("--vault", required=True)
    v_add.add_argument("--suite", required=True)
    v_add.add_argument("--task", default=None)
    v_add.add_argument("--baseline", choices=["red", "green"], default="red")
    v_add.add_argument("--timeout", type=int, default=120)
    v_add.add_argument("--leak", choices=["minimal", "message"], default="message")
    v_add.add_argument("--vault-dir", default=None)
    v_add.add_argument("--json", action="store_true")
    v_add.add_argument("files", nargs="+")
    v_add.set_defaults(func=cmd_vault_add)

    v_list = vault_sub.add_parser("list", help="list suites in the vault")
    v_list.add_argument("--vault", required=True)
    v_list.add_argument("--vault-dir", default=None)
    v_list.add_argument("--json", action="store_true")
    v_list.set_defaults(func=cmd_vault_list)

    v_rm = vault_sub.add_parser("rm", help="remove a suite from the vault")
    v_rm.add_argument("--vault", required=True)
    v_rm.add_argument("--suite", required=True)
    v_rm.add_argument("--yes", action="store_true")
    v_rm.add_argument("--vault-dir", default=None)
    v_rm.set_defaults(func=cmd_vault_rm)

    v_val = vault_sub.add_parser("validate", help="validate the suite on the baseline")
    v_val.add_argument("--vault", required=True)
    v_val.add_argument("--repo", default=".")
    v_val.add_argument("--suite", default=None)
    v_val.add_argument("--runs", type=int, default=2)
    v_val.add_argument("--vault-dir", default=None)
    v_val.add_argument("--json", action="store_true")
    v_val.set_defaults(func=cmd_vault_validate)

    doctor = sub.add_parser("doctor", help="check the environment and adapter tier")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--inject-test", action="store_true", help="self-test PTY keystroke injection")
    doctor.set_defaults(func=cmd_doctor)

    dash = sub.add_parser("dashboard", help="HTML dashboard (static or live)")
    dash.add_argument("--repo", default=".")
    dash.add_argument("--run")
    dash.add_argument("--out", default=None, help="write a static HTML file")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=47822)
    dash.add_argument("--open", dest="open_browser", action="store_true")
    dash.set_defaults(func=cmd_dashboard)

    skill = sub.add_parser("install-skill", help="install the skill for a chat CLI")
    skill.add_argument("--for", dest="provider", choices=list(PROVIDERS), required=True)
    skill.add_argument("--dir", default=".")
    skill.add_argument("--global", dest="global_", action="store_true")
    skill.set_defaults(func=cmd_install_skill)

    setup = sub.add_parser("setup", help="detect installed CLIs and install the skill (one command)")
    setup.add_argument("--for", dest="providers", action="append", choices=list(PROVIDERS))
    setup.add_argument("--dir", default=".")
    setup.add_argument("--local", action="store_true", help="install into the current repo instead of home")
    setup.add_argument("--dry-run", action="store_true")
    setup.set_defaults(func=cmd_setup)

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover - exotic stream
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    notice = update.check_for_update() if update.should_check() else None
    try:
        code = int(args.func(args))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        code = 1
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 1
    if notice:
        update.print_notice(notice)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
