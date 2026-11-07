"""CLI entrypoint.

Commands: plan | lint | run | start | stop | serve | status | watch | report |
install-skill
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, planner
from . import doctor as doctor_module
from .adapters.claude import ClaudeAdapter
from .adapters.generic import GenericProcessAdapter
from .adapters.opencode import OpenCodeAdapter
from .adapters.pty import PtyAdapter
from .daemon import serve, start_detached, stop_run
from .dashboard import serve_dashboard, write_static
from .engine import Engine, EngineConfig
from .models import Task
from .skill_install import PROVIDERS, install_skill
from .state import RunPaths, RunState, latest_run, new_run_id, read_json
from .ui import load_latest, render_markdown, watch as watch_run


def _parse_bundle(args) -> planner.PlanBundle:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8-sig")
    elif args.prompt:
        text = args.prompt
    else:
        raise SystemExit("cần --prompt hoặc --file")
    if args.planner != "rules":
        raise SystemExit(
            f"--planner {args.planner} chưa có trong Phase 2 (chỉ 'rules', 0 token)."
        )
    return planner.parse_prompt(text)


def _load_contract(args) -> tuple[list[Task], list[Task]]:
    if not getattr(args, "tasks", None) and not getattr(args, "prompt", None):
        raise SystemExit("cần --tasks hoặc --prompt")
    bundle = planner.load_contract(getattr(args, "tasks", None), getattr(args, "prompt", None))
    return bundle.tasks, bundle.constraints


def _lint_or_fail(args, tasks: list[Task], constraints: list[Task]) -> int | None:
    issues = planner.lint_tasks([*tasks, *constraints], repo=args.repo)
    if issues:
        print(planner.format_issues(issues), file=sys.stderr)
    if issues and not getattr(args, "no_lint", False) and planner.has_errors(issues):
        print("Contract không hợp lệ - dừng (fail closed).", file=sys.stderr)
        return 2
    return None


def _build_adapter(args):
    if args.adapter == "opencode":
        return OpenCodeAdapter(model=args.model, binary=args.binary or "opencode")
    if args.adapter == "claude":
        return ClaudeAdapter(
            binary=args.binary or "claude", permission_mode=args.permission_mode
        )
    if args.adapter == "pty":
        if not args.agent:
            raise SystemExit("--agent bắt buộc khi dùng --adapter pty")
        return PtyAdapter(args.agent)
    if not args.agent:
        raise SystemExit("--agent bắt buộc khi dùng --adapter generic")
    return GenericProcessAdapter(args.agent)


def cmd_plan(args) -> int:
    bundle = _parse_bundle(args)
    out = Path(args.out)
    planner.write_tasks(out, bundle)
    if args.json:
        print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(planner.render_yaml(bundle))
    issues = planner.lint_tasks(bundle.all_tasks(), repo=args.repo)
    if issues:
        print("\n# lint", file=sys.stderr)
        print(planner.format_issues(issues), file=sys.stderr)
    print(f"\n# đã ghi {out}", file=sys.stderr)
    return 2 if planner.has_errors(issues) else 0


def cmd_lint(args) -> int:
    tasks = planner.load_tasks(args.tasks)
    issues = planner.lint_tasks(tasks, repo=args.repo)
    print(planner.format_issues(issues))
    return 2 if planner.has_errors(issues) else 0


def cmd_run(args) -> int:
    tasks, constraints = _load_contract(args)
    failed = _lint_or_fail(args, tasks, constraints)
    if failed is not None:
        return failed
    config = EngineConfig(
        repo=args.repo,
        tasks=tasks,
        constraints=constraints,
        agent_command=args.agent or f"opencode:{args.model or 'default'}",
        test_command=args.test,
        prompt=args.prompt or "",
        contract_path=args.tasks,
        max_kicks=args.max_kicks,
        turn_timeout=args.turn_timeout,
        verify_timeout=args.verify_timeout,
        freeze_after=args.freeze_after,
        max_wall_clock=args.max_wall_clock,
        max_cost_usd=args.max_cost,
        freeze_probe=not args.no_freeze_probe,
        use_job=not args.no_job,
        full_suite_every=args.full_suite_every,
        run_id=args.run_id,
    )
    result = Engine(config, _build_adapter(args)).run()
    paths = RunPaths(args.repo, result.run_id)
    print(render_markdown(RunState.load(paths.state), read_json(paths.ledger)))
    print(f"\nreport: {result.report_path}")
    print(f"kết luận: {result.diagnosis.value} (exit {result.exit_code})")
    return result.exit_code


def _run_flags(args) -> list[str]:
    flags: list[str] = ["--repo", str(Path(args.repo).resolve())]
    for flag, value in (
        ("--tasks", args.tasks),
        ("--prompt", args.prompt),
        ("--test", args.test),
        ("--agent", args.agent),
        ("--model", args.model),
    ):
        if value not in (None, ""):
            flags.extend([flag, str(value)])
    flags.extend(["--adapter", args.adapter])
    flags.extend(["--max-kicks", str(args.max_kicks)])
    flags.extend(["--turn-timeout", str(args.turn_timeout)])
    flags.extend(["--verify-timeout", str(args.verify_timeout)])
    flags.extend(["--freeze-after", str(args.freeze_after)])
    flags.extend(["--max-wall-clock", str(args.max_wall_clock)])
    flags.extend(["--full-suite-every", str(args.full_suite_every)])
    if args.permission_mode:
        flags.extend(["--permission-mode", args.permission_mode])
    if args.binary:
        flags.extend(["--binary", args.binary])
    if args.max_cost:
        flags.extend(["--max-cost", str(args.max_cost)])
    if args.no_freeze_probe:
        flags.append("--no-freeze-probe")
    if args.no_job:
        flags.append("--no-job")
    if args.no_lint:
        flags.append("--no-lint")
    return flags


def cmd_start(args) -> int:
    tasks, constraints = _load_contract(args)
    failed = _lint_or_fail(args, tasks, constraints)
    if failed is not None:
        return failed
    run_id = args.run_id or new_run_id()
    record = start_detached(args.repo, _run_flags(args), run_id)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"\nĐang chạy ngầm. Theo dõi: waker status --repo {args.repo} --run {run_id}")
    return 0


def cmd_stop(args) -> int:
    stopped = stop_run(args.repo, args.run)
    print("đã dừng" if stopped else "không tìm thấy run đang chạy")
    return 0 if stopped else 1


def cmd_serve(args) -> int:
    serve(args.repo, host=args.host, port=args.port)
    return 0


def cmd_install_skill(args) -> int:
    target = install_skill(args.provider, args.dir, global_=args.global_)
    print(f"đã cài skill cho {args.provider}: {target}")
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
            "elapsed": round(state.elapsed, 1),
            "cost_usd": round(state.cost_usd, 6),
            "max_cost_usd": state.max_cost_usd,
            "tasks": ledger.get("tasks", {}),
            "test": ledger.get("test", {}),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(state, ledger))
    return 0


def cmd_watch(args) -> int:
    try:
        watch_run(args.repo, args.run, interval=args.interval)
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


def cmd_report(args) -> int:
    if args.run:
        paths = RunPaths(args.repo, args.run)
    else:
        run_id = latest_run(args.repo)
        if not run_id:
            print("chưa có run nào", file=sys.stderr)
            return 1
        paths = RunPaths(args.repo, run_id)
    if not paths.report.exists():
        print("chưa có report", file=sys.stderr)
        return 1
    print(paths.report.read_text(encoding="utf-8", errors="replace"))
    return 0


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tasks")
    parser.add_argument("--prompt")
    parser.add_argument("--test", default=None)
    parser.add_argument("--agent", default=None, help="lệnh agent cho adapter generic/pty")
    parser.add_argument("--adapter", choices=["generic", "opencode", "claude", "pty"], default="generic")
    parser.add_argument("--model", default=None, help="provider/model cho OpenCode")
    parser.add_argument("--binary", default=None, help="đường dẫn CLI (opencode/claude)")
    parser.add_argument("--permission-mode", default="acceptEdits", help="Claude Code permission mode")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--max-kicks", type=int, default=5)
    parser.add_argument("--max-cost", type=float, default=0.0, help="USD; 0 = tắt cost guard")
    parser.add_argument("--full-suite-every", type=int, default=0, help="chạy full suite mỗi N kick")
    parser.add_argument("--turn-timeout", type=float, default=900.0)
    parser.add_argument("--verify-timeout", type=float, default=300.0)
    parser.add_argument("--freeze-after", type=float, default=300.0)
    parser.add_argument("--max-wall-clock", type=float, default=5400.0)
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

    plan = sub.add_parser("plan", help="bóc prompt thành hợp đồng (0 token)")
    plan.add_argument("--prompt")
    plan.add_argument("--file")
    plan.add_argument("--out", default=".waker/tasks.yaml")
    plan.add_argument("--repo", default=".")
    plan.add_argument("--planner", default="rules", choices=["rules"])
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(func=cmd_plan)

    lint = sub.add_parser("lint", help="kiểm tra hợp đồng (0 token)")
    lint.add_argument("--tasks", required=True)
    lint.add_argument("--repo", default=".")
    lint.set_defaults(func=cmd_lint)

    run = sub.add_parser("run", help="chạy supervisor ở foreground")
    _add_run_arguments(run)
    run.set_defaults(func=cmd_run)

    start = sub.add_parser("start", help="chạy supervisor ở background (detached)")
    _add_run_arguments(start)
    start.set_defaults(func=cmd_start, detach=True)

    stop = sub.add_parser("stop", help="dừng run đang chạy")
    stop.add_argument("--repo", default=".")
    stop.add_argument("--run")
    stop.set_defaults(func=cmd_stop)

    serve_parser = sub.add_parser("serve", help="HTTP daemon trên loopback")
    serve_parser.add_argument("--repo", default=".")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=47821)
    serve_parser.set_defaults(func=cmd_serve)

    status = sub.add_parser("status", help="bảng tiến độ")
    status.add_argument("--repo", default=".")
    status.add_argument("--run")
    status.add_argument("--format", choices=["md", "json"], default="md")
    status.set_defaults(func=cmd_status)

    watch = sub.add_parser("watch", help="TUI sống (Rich Live)")
    watch.add_argument("--repo", default=".")
    watch.add_argument("--run")
    watch.add_argument("--interval", type=float, default=1.0)
    watch.set_defaults(func=cmd_watch)

    report = sub.add_parser("report", help="in report.md")
    report.add_argument("--repo", default=".")
    report.add_argument("--run")
    report.set_defaults(func=cmd_report)

    doctor = sub.add_parser("doctor", help="kiểm tra môi trường và adapter tier")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--inject-test", action="store_true", help="tự test bơm phím qua PTY")
    doctor.set_defaults(func=cmd_doctor)

    dash = sub.add_parser("dashboard", help="dashboard HTML (static hoặc live)")
    dash.add_argument("--repo", default=".")
    dash.add_argument("--run")
    dash.add_argument("--out", default=None, help="ghi file HTML tĩnh")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=47822)
    dash.add_argument("--open", dest="open_browser", action="store_true")
    dash.set_defaults(func=cmd_dashboard)

    skill = sub.add_parser("install-skill", help="cài skill cho chatbox CLI")
    skill.add_argument("--for", dest="provider", choices=list(PROVIDERS), required=True)
    skill.add_argument("--dir", default=".")
    skill.add_argument("--global", dest="global_", action="store_true")
    skill.set_defaults(func=cmd_install_skill)

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
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"lỗi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
