"""CLI entrypoint: ``waker plan | lint | run | status | watch | report``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, planner
from .engine import Engine, EngineConfig
from .models import Task
from .state import RunPaths, RunState, latest_run, read_json
from .ui import build_rich, load_latest, render_markdown, watch as watch_run


def _parse_bundle(args) -> planner.PlanBundle:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.prompt:
        text = args.prompt
    else:
        raise SystemExit("cần --prompt hoặc --file")
    if args.planner != "rules":
        raise SystemExit(
            f"--planner {args.planner} chưa có trong Phase 1 (chỉ 'rules', 0 token)."
        )
    return planner.parse_prompt(text)


def _load_contract(args) -> tuple[list[Task], list[Task]]:
    bundle = planner.load_contract(getattr(args, "tasks", None), getattr(args, "prompt", None))
    return bundle.tasks, bundle.constraints


def cmd_plan(args) -> int:
    bundle = _parse_bundle(args)
    out = Path(args.out)
    planner.write_tasks(out, bundle)
    text = planner.render_yaml(bundle)
    if args.json:
        print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(text)
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
    issues = planner.lint_tasks([*tasks, *constraints], repo=args.repo)
    if issues and not args.no_lint:
        print(planner.format_issues(issues), file=sys.stderr)
        if planner.has_errors(issues):
            print("\nContract không hợp lệ - dừng (fail closed).", file=sys.stderr)
            return 2
    config = EngineConfig(
        repo=args.repo,
        tasks=tasks,
        constraints=constraints,
        agent_command=args.agent,
        test_command=args.test,
        prompt=args.prompt or "",
        contract_path=args.tasks,
        max_kicks=args.max_kicks,
        turn_timeout=args.turn_timeout,
        verify_timeout=args.verify_timeout,
        freeze_after=args.freeze_after,
        max_wall_clock=args.max_wall_clock,
        run_id=args.run_id,
    )
    result = Engine(config).run()
    print(render_markdown(RunState.load(RunPaths(args.repo, result.run_id).state), read_json(RunPaths(args.repo, result.run_id).ledger)))
    print(f"\nreport: {result.report_path}")
    print(f"kết luận: {result.diagnosis.value} (exit {result.exit_code})")
    return result.exit_code


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
    print(paths.report.read_text(encoding="utf-8"))
    return 0


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

    run = sub.add_parser("run", help="chạy supervisor")
    run.add_argument("--tasks")
    run.add_argument("--prompt")
    run.add_argument("--test", default=None)
    run.add_argument("--agent", required=True, help="lệnh chạy agent, có thể dùng {prompt}")
    run.add_argument("--repo", default=".")
    run.add_argument("--max-kicks", type=int, default=5)
    run.add_argument("--turn-timeout", type=float, default=900.0)
    run.add_argument("--verify-timeout", type=float, default=300.0)
    run.add_argument("--freeze-after", type=float, default=300.0)
    run.add_argument("--max-wall-clock", type=float, default=5400.0)
    run.add_argument("--run-id")
    run.add_argument("--no-lint", action="store_true")
    run.set_defaults(func=cmd_run)

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
