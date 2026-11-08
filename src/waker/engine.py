"""The loop: spawn a turn, observe the disk, verify, diagnose, wake, repeat."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import detector, evidence, injector, scheduler
from .adapters.base import Adapter, TurnContext
from .adapters.generic import GenericProcessAdapter
from .models import (
    EXIT_CODES,
    TERMINAL,
    Diagnosis,
    Failure,
    Observation,
    RunResult,
    Task,
    TurnResult,
)
from .state import (
    EventLog,
    RunPaths,
    RunState,
    acquire_run_lock,
    checkpoint,
    done_ids,
    ensure_runtime_excluded,
    file_sha256,
    git_dirty,
    git_head,
    is_git_repo,
    new_ledger,
    new_run_id,
    read_json,
    release_run_lock,
    set_task,
    sha256_bytes,
    utcnow,
    write_json_atomic,
)
from .ui import render_markdown

DEFAULT_TEST_GLOBS = [
    "tests/**",
    "test/**",
    "**/test_*.py",
    "**/*_test.py",
]


def build_adapter_from_state(state: RunState):
    """Recreate the adapter used by an existing run (for ``--resume``)."""
    from .adapters.claude import ClaudeAdapter
    from .adapters.opencode import OpenCodeAdapter
    from .adapters.pty import PtyAdapter

    name = state.adapter or "generic"
    if name == "opencode":
        return OpenCodeAdapter(model=state.model, binary=state.binary or "opencode")
    if name == "claude":
        return ClaudeAdapter(
            binary=state.binary or "claude", permission_mode=state.permission_mode
        )
    if name == "pty":
        return PtyAdapter(state.agent_command)
    if not state.agent_command:
        raise RuntimeError("run has no agent command to resume")
    return GenericProcessAdapter(state.agent_command)


@dataclass
class EngineConfig:
    repo: str
    tasks: list[Task]
    agent_command: str
    test_command: str | None = None
    prompt: str = ""
    constraints: list[Task] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    contract_path: str | None = None
    test_globs: list[str] = field(default_factory=lambda: list(DEFAULT_TEST_GLOBS))
    max_kicks: int = 5
    turn_timeout: float = 900.0
    verify_timeout: float = 300.0
    freeze_after: float = 300.0
    alive_threshold: float = 120.0
    max_wall_clock: float = 5400.0
    max_cost_usd: float = 0.0
    freeze_probe: bool = True
    use_job: bool = True
    full_suite_every: int = 0
    adapter_name: str = "generic"
    model: str | None = None
    permission_mode: str = "acceptEdits"
    binary: str | None = None
    run_id: str | None = None


class Engine:
    def __init__(self, config: EngineConfig, adapter: Adapter | None = None) -> None:
        self.config = config
        self.repo = Path(config.repo).resolve()
        self.adapter = adapter or GenericProcessAdapter(config.agent_command)
        self.state: RunState | None = None
        self.paths: RunPaths | None = None
        self.events: EventLog | None = None
        self._next_prompt: str = ""
        self._failures: list[Failure] = []
        self._baseline_test: dict = {}
        self._verify_results: dict = {}
        self._constraint_results: dict = {}
        self._verify_cache: dict = {}
        self._test_skipped: bool = False

    # ------------------------------------------------------------------ prepare

    def prepare(self) -> RunState:
        cfg = self.config
        if not is_git_repo(self.repo):
            raise RuntimeError(
                f"{self.repo} is not a git repository. waker needs git for evidence "
                "(diff + tamper detection + checkpoints)."
            )
        ensure_runtime_excluded(self.repo)

        if git_dirty(self.repo):
            checkpoint(self.repo, "waker: baseline")
        baseline_commit = git_head(self.repo)
        baseline_hash = evidence.hash_globs(self.repo, cfg.test_globs)

        all_tasks = [*cfg.tasks, *cfg.constraints]
        contract_hash = (
            file_sha256(cfg.contract_path)
            if cfg.contract_path and Path(cfg.contract_path).exists()
            else sha256_bytes(
                json.dumps([t.to_dict() for t in all_tasks], sort_keys=True).encode("utf-8")
            )
        )

        run_id = cfg.run_id or new_run_id()
        paths = RunPaths(self.repo, run_id)
        acquire_run_lock(paths, run_id)
        events = EventLog(paths.events)
        state = RunState(
            run_id=run_id,
            repo=str(self.repo),
            prompt=cfg.prompt,
            agent_command=cfg.agent_command,
            test_command=cfg.test_command,
            baseline_commit=baseline_commit,
            baseline_test_hash=baseline_hash,
            test_globs=list(cfg.test_globs),
            started_at=utcnow(),
            tasks=[t.to_dict() for t in cfg.tasks],
            session_id=f"ses_waker_{run_id}",
            constraints=[t.to_dict() for t in cfg.constraints],
            adapter=cfg.adapter_name,
            model=cfg.model,
            permission_mode=cfg.permission_mode,
            binary=cfg.binary,
            contract_path=str(Path(cfg.contract_path).resolve())
            if cfg.contract_path
            else None,
            max_kicks=cfg.max_kicks,
            turn_timeout=cfg.turn_timeout,
            freeze_after=cfg.freeze_after,
            alive_threshold=cfg.alive_threshold,
            max_wall_clock=cfg.max_wall_clock,
            contract_hash=contract_hash,
            max_cost_usd=cfg.max_cost_usd,
        )
        state.save(paths.state)
        cache_path = paths.root / "verify_cache.json"
        if cache_path.exists():
            try:
                self._verify_cache = read_json(cache_path)
            except (ValueError, OSError):
                self._verify_cache = {}
        write_json_atomic(paths.ledger, new_ledger(all_tasks))
        events.append(
            "prepare",
            run_id=run_id,
            repo=str(self.repo),
            baseline_commit=baseline_commit,
            tasks_hash=contract_hash,
            test_globs=list(cfg.test_globs),
        )

        if cfg.test_command:
            baseline_test = evidence.run_command(
                cfg.test_command, self.repo, timeout=cfg.verify_timeout
            )
            self._baseline_test = baseline_test.to_dict()
            write_json_atomic(
                paths.root / "baseline_test.json",
                {
                    **baseline_test.to_dict(),
                    "failures": [f.to_dict() for f in evidence.parse_failures(baseline_test.output)],
                },
            )
            events.append("baseline_test", **baseline_test.to_dict())

        initial = injector.build_initial_prompt(
            cfg.tasks, cfg.constraints, cfg.preferences, cfg.test_command
        )
        self._next_prompt = initial
        paths.kick_prompt(0).write_text(initial, encoding="utf-8")

        self.state = state
        self.paths = paths
        self.events = events
        return state

    @classmethod
    def from_run(
        cls,
        repo: str | Path,
        run_id: str,
        adapter: Adapter | None = None,
        max_kicks: int | None = None,
    ) -> "Engine":
        """Attach to an interrupted (or failed) run and continue it."""
        root = Path(repo).resolve()
        paths = RunPaths(root, run_id)
        if not paths.state.exists():
            raise FileNotFoundError(f"run {run_id} not found in {root}")
        state = RunState.load(paths.state)
        if Path(state.repo).resolve() != root:
            raise RuntimeError(
                f"run {run_id} belongs to {state.repo}, not {root}"
            )
        acquire_run_lock(paths, run_id)

        tasks = [Task.from_dict(item) for item in state.tasks]
        constraints = [Task.from_dict(item) for item in state.constraints]
        cfg = EngineConfig(
            repo=str(root),
            tasks=tasks,
            constraints=constraints,
            agent_command=state.agent_command,
            test_command=state.test_command,
            prompt=state.prompt,
            contract_path=state.contract_path,
            max_kicks=max_kicks or state.max_kicks,
            turn_timeout=state.turn_timeout,
            freeze_after=state.freeze_after,
            alive_threshold=state.alive_threshold,
            max_wall_clock=state.max_wall_clock,
            max_cost_usd=state.max_cost_usd,
            adapter_name=state.adapter,
            model=state.model,
            permission_mode=state.permission_mode,
            binary=state.binary,
            run_id=run_id,
        )
        engine = cls(cfg, adapter or build_adapter_from_state(state))
        engine.state = state
        engine.paths = paths
        engine.events = EventLog(paths.events)
        cache_path = paths.root / "verify_cache.json"
        if cache_path.exists():
            try:
                engine._verify_cache = read_json(cache_path)
            except (ValueError, OSError):
                engine._verify_cache = {}

        previous_status = state.status
        state.generation += 1
        state.elapsed_offset += state.elapsed
        state.started_ts = time.time()
        state.ended_ts = None
        state.status = "running"
        state.diagnosis = None
        if max_kicks:
            state.max_kicks = max(max_kicks, state.kicks + 1)
        else:
            state.max_kicks = state.kicks + max(1, state.max_kicks)
        state.save(paths.state)

        ledger = (
            read_json(paths.ledger)
            if paths.ledger.exists()
            else new_ledger([*tasks, *constraints])
        )
        engine._next_prompt = injector.build_wake_prompt(
            Diagnosis.PARTIAL,
            tasks,
            constraints,
            ledger,
            [],
            state.test_command,
            state.kicks,
            state.max_kicks,
            notes=["Run khôi phục sau khi bị gián đoạn. Tiếp tục từ chỗ còn thiếu."],
        )
        engine.events.append(
            "resume",
            run_id=run_id,
            generation=state.generation,
            previous_status=previous_status,
            kicks=state.kicks,
            max_kicks=state.max_kicks,
        )
        return engine

    # ---------------------------------------------------------------------- run

    def run(self) -> RunResult:
        state = self.state or self.prepare()
        assert self.paths is not None and self.events is not None
        started = time.time()

        try:
            while True:
                kick = state.kicks
                prompt = self._next_prompt
                prompt_path = self.paths.kick_prompt(kick, state.generation)
                prompt_path.write_text(prompt, encoding="utf-8")
                ctx = TurnContext(
                    repo=str(self.repo),
                    run_id=state.run_id,
                    session_id=state.session_id,
                    kick=kick,
                    timeout=state.turn_timeout,
                    prompt_file=str(prompt_path),
                    resume_id=state.agent_session_id,
                    freeze_after=state.freeze_after if self.config.freeze_probe else 0.0,
                    use_freeze_probe=self.config.freeze_probe,
                    use_job=self.config.use_job,
                )
                self.events.append(
                    "turn_start",
                    kick=kick,
                    session=state.session_id,
                    command=state.agent_command,
                    prompt_sha=sha256_bytes(prompt.encode("utf-8")),
                )
                turn = self.adapter.run_turn(prompt, ctx)
                state.cost_usd += max(0.0, turn.cost_usd)
                if turn.session_id and turn.session_id != state.agent_session_id:
                    state.agent_session_id = turn.session_id
                    self.events.append(
                        "session_discovered", kick=kick, session_id=turn.session_id
                    )
                self.events.append(
                    "turn_end",
                    kick=kick,
                    exit_code=turn.exit_code,
                    duration=round(turn.duration, 2),
                    timed_out=turn.timed_out,
                    frozen=turn.frozen,
                    cost_usd=round(turn.cost_usd, 6),
                    tokens=turn.tokens,
                    events=turn.events,
                )

                obs = self._observe(turn)
                diag = detector.diagnose(obs)
                if diag is Diagnosis.TAMPER:
                    restored = evidence.restore_globs(
                        self.repo, state.test_globs, state.baseline_commit
                    )
                    self.events.append("tamper_revert", kick=kick, files=restored)
                diag = self._budget_guard(diag, state)
                self._record(kick, obs, diag, turn, prompt_path)

                self.events.append(
                    "diagnose",
                    kick=kick,
                    label=diag.value,
                    task_done=sum(
                        1
                        for rec in read_json(self.paths.ledger).get("tasks", {}).values()
                        if rec.get("status") == "done"
                    ),
                    total=len(self.config.tasks),
                    test_exit=obs.test_exit,
                    fingerprint=obs.fingerprint,
                    streak=obs.same_fingerprint_streak,
                )

                if diag in TERMINAL:
                    return self._finish(state, diag, started)

                commit = checkpoint(self.repo, f"waker: kick-{kick}")
                self.events.append("checkpoint", kick=kick, commit=commit)

                state.prev_fingerprint = obs.prev_fingerprint
                state.last_fingerprint = obs.fingerprint
                state.fingerprint_streak = obs.same_fingerprint_streak
                state.last_diff_hash = obs.diff_hash
                state.kicks = kick + 1
                state.save(self.paths.state)

                ledger = read_json(self.paths.ledger)
                self._next_prompt = injector.build_wake_prompt(
                    diag,
                    self.config.tasks,
                    self.config.constraints,
                    ledger,
                    self._failures,
                    self.config.test_command,
                    state.kicks,
                    state.max_kicks,
                    notes=self._notes(diag, obs),
                )
                self.events.append(
                    "kick_requested",
                    n=state.kicks,
                    reason=diag.value,
                    prompt_sha=sha256_bytes(self._next_prompt.encode("utf-8")),
                )

        except KeyboardInterrupt:
            commit = checkpoint(self.repo, "waker: aborted")
            self.events.append("aborted", commit=commit)
            return self._finish(state, Diagnosis.BREAKER, started, aborted=True)

    # ------------------------------------------------------------------ observe

    def _observe(self, turn: TurnResult) -> Observation:
        state = self.state
        assert state is not None
        cfg = self.config

        files = evidence.changed_files(self.repo, state.baseline_commit)
        work = [t for t in cfg.tasks if t.kind == "work"]
        constraints = [t for t in cfg.constraints if t.kind != "work"]

        hits = evidence.scope_hits(work, files)
        verifications: dict[str, evidence.RequirementResult] = {}
        candidate_done = True

        for task in work:
            scoped = scheduler.scope_files(task, files)
            if not scoped:
                verifications[task.id] = evidence.RequirementResult(task.id, None)
                candidate_done = False
                continue
            digest = scheduler.scope_digest(self.repo, scoped)
            cached = scheduler.cached_result(self._verify_cache, task.id, digest)
            if cached is not None:
                verifications[task.id] = evidence.RequirementResult(
                    task.id, cached, output="(cached)"
                )
            else:
                outcome = (
                    evidence.run_command(task.command or "", self.repo, timeout=cfg.verify_timeout)
                    if task.command
                    else evidence.CommandResult(None)
                )
                verifications[task.id] = evidence.RequirementResult(
                    task.id, outcome.exit_code, output=outcome.output
                )
                scheduler.remember(
                    self._verify_cache, task.id, digest, outcome.exit_code, state.kicks
                )
            if verifications[task.id].exit_code != 0:
                candidate_done = False

        constraint_results: dict[str, evidence.RequirementResult] = {}
        constraint_digest = scheduler.scope_digest(self.repo, files)
        for constraint in constraints:
            cached = scheduler.cached_result(
                self._verify_cache, constraint.id, constraint_digest
            )
            if cached is not None:
                constraint_results[constraint.id] = evidence.RequirementResult(
                    constraint.id, cached, output="(cached)"
                )
            else:
                outcome = (
                    evidence.run_command(
                        constraint.command or "", self.repo, timeout=cfg.verify_timeout
                    )
                    if constraint.command
                    else evidence.CommandResult(None)
                )
                constraint_results[constraint.id] = evidence.RequirementResult(
                    constraint.id, outcome.exit_code, output=outcome.output
                )
                scheduler.remember(
                    self._verify_cache,
                    constraint.id,
                    constraint_digest,
                    outcome.exit_code,
                    state.kicks,
                )

        claimed = evidence.claimed_done(turn.output)
        run_suite = bool(cfg.test_command) and scheduler.should_run_suite(
            candidate_done, claimed, state.kicks, cfg.full_suite_every
        )
        if run_suite:
            test = evidence.run_command(
                cfg.test_command or "", self.repo, timeout=cfg.verify_timeout
            )
        else:
            test = evidence.CommandResult(None)
        self._test_skipped = bool(cfg.test_command) and not run_suite

        self._verify_results = verifications
        self._constraint_results = constraint_results
        assert self.paths is not None
        write_json_atomic(self.paths.root / "verify_cache.json", self._verify_cache)

        tamper = evidence.hash_globs(self.repo, state.test_globs) != state.baseline_test_hash
        integrity_ok = True
        if cfg.contract_path and Path(cfg.contract_path).exists():
            integrity_ok = file_sha256(cfg.contract_path) == state.contract_hash

        gate_ok = evidence.all_tasks_done(
            work, hits, verifications, constraints, constraint_results
        )
        test_ok = (not cfg.test_command) or (run_suite and test.exit_code == 0)
        all_done = gate_ok and test_ok

        failed_outputs = [
            result.output
            for result in verifications.values()
            if result.exit_code not in (0, None)
        ]
        combined = "\n".join([test.output, *failed_outputs])
        failures = evidence.parse_failures(combined)
        suspect = evidence.suspect_test(failures, combined)

        diff_hash = evidence.diff_digest(self.repo, files)
        signature = evidence.test_signature(combined)
        fingerprint = sha256_bytes(
            (diff_hash + signature + ",".join(sorted(files))).encode("utf-8")
        )
        prev = state.last_fingerprint
        streak = (state.fingerprint_streak + 1) if prev == fingerprint else 1

        self._failures = failures
        return Observation(
            turn_state="running" if (turn.timed_out or turn.frozen) else "exited",
            exit_code=turn.exit_code,
            elapsed=turn.duration,
            last_event_age=turn.duration if (turn.timed_out or turn.frozen) else 0.0,
            diff_hash=diff_hash,
            prev_diff_hash=state.last_diff_hash,
            changed_files=files,
            lines_changed=evidence.lines_changed(self.repo, state.baseline_commit),
            in_scope_files=hits,
            test_exit=test.exit_code,
            has_test=bool(cfg.test_command),
            test_signature=signature,
            tamper=tamper,
            claimed_done=claimed,
            blocked_reason=evidence.parse_blocked(turn.output),
            all_tasks_done=all_done,
            integrity_ok=integrity_ok,
            suspect_test=suspect,
            fingerprint=fingerprint,
            prev_fingerprint=prev,
            same_fingerprint_streak=streak,
            kicks=state.kicks,
            max_kicks=state.max_kicks,
            elapsed_total=state.elapsed,
            max_wall_clock=state.max_wall_clock,
            cost_usd=state.cost_usd,
            max_cost_usd=state.max_cost_usd,
            alive_threshold=state.alive_threshold,
            freeze_after=state.freeze_after,
            unscoped_changes=evidence.unscoped_files(work + constraints, files),
        )

    # -------------------------------------------------------------------- record

    def _record(
        self,
        kick: int,
        obs: Observation,
        diag: Diagnosis,
        turn: TurnResult,
        prompt_path: Path,
    ) -> None:
        assert self.paths is not None and self.events is not None and self.state is not None
        ledger = read_json(self.paths.ledger)
        work = [t for t in self.config.tasks if t.kind == "work"]
        constraints = [t for t in self.config.constraints if t.kind != "work"]

        for task in work:
            files = obs.in_scope_files.get(task.id, [])
            result = self._verify_results.get(task.id)
            gate_exit = result.exit_code if result else None
            status = "pending"
            if files and gate_exit == 0:
                status = "done"
            elif files:
                status = "failed"
            evidence_payload = {
                "files": files[:10],
                "gate": "pass" if gate_exit == 0 else "fail",
                "message": self._message_for(task.id),
            }
            set_task(ledger, task.id, status, evidence_payload, kick)

        for constraint in constraints:
            result = self._constraint_results.get(constraint.id)
            exit_code = result.exit_code if result else None
            status = "done" if exit_code == 0 else ("failed" if exit_code is not None else "pending")
            set_task(
                ledger,
                constraint.id,
                status,
                {"gate": "pass" if exit_code == 0 else "fail", "files": []},
                kick,
            )

        ledger["kicks"] = kick
        ledger["test"] = {
            "exit_code": obs.test_exit,
            "failed": [failure.label() for failure in self._failures[:5]],
            "signature": obs.test_signature,
            "skipped": getattr(self, "_test_skipped", False),
        }
        write_json_atomic(self.paths.ledger, ledger)

        (self.paths.kick_dir(kick, self.state.generation) / "stdout.log").write_text(
            turn.output, encoding="utf-8", errors="replace"
        )
        write_json_atomic(
            self.paths.kick_result(kick, self.state.generation),
            {
                "kick": kick,
                "diagnosis": diag.value,
                "exit_code": turn.exit_code,
                "duration": round(turn.duration, 2),
                "timed_out": turn.timed_out,
                "prompt_sha": sha256_bytes(prompt_path.read_text(encoding="utf-8").encode("utf-8")),
                "changed_files": obs.changed_files,
                "in_scope": obs.in_scope_files,
                "unscoped": obs.unscoped_changes,
                "test_exit": obs.test_exit,
                "test_skipped": getattr(self, "_test_skipped", False),
                "tamper": obs.tamper,
                "fingerprint": obs.fingerprint,
                "streak": obs.same_fingerprint_streak,
                "claimed_done": obs.claimed_done,
                "blocked": obs.blocked_reason,
                "frozen": turn.frozen,
                "cost_usd": round(turn.cost_usd, 6),
                "tokens": turn.tokens,
                "events": turn.events,
                "total_cost_usd": round(self.state.cost_usd, 6),
            },
        )
        self.events.append(
            "verify",
            kick=kick,
            changed=len(obs.changed_files),
            in_scope={k: len(v) for k, v in obs.in_scope_files.items()},
            test_exit=obs.test_exit,
            tamper=obs.tamper,
            all_done=obs.all_tasks_done,
        )

    def _message_for(self, task_id: str) -> str:
        result = self._verify_results.get(task_id)
        texts = result.output if result else ""
        for line in texts.splitlines():
            stripped = line.strip()
            if stripped and ("Error" in stripped or "assert" in stripped.lower()):
                return stripped[:140]
        return ""

    # -------------------------------------------------------------------- finish

    def _finish(
        self,
        state: RunState,
        diag: Diagnosis,
        started: float,
        aborted: bool = False,
    ) -> RunResult:
        assert self.paths is not None and self.events is not None
        closer = getattr(self.adapter, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - closing must never break the report
                pass
        state.status = "aborted" if aborted else diag.value
        state.diagnosis = diag.value
        state.ended_ts = time.time()
        state.save(self.paths.state)

        ledger = read_json(self.paths.ledger)
        report = render_markdown(state, ledger)
        report += "\n\n## Lịch sử kick\n"
        for line in self.events.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("t") == "diagnose":
                report += f"- kick {record.get('kick')}: **{record.get('label')}**\n"
        report += f"\n_Ghi lúc {utcnow()}_\n"
        self.paths.report.write_text(report, encoding="utf-8", errors="replace")
        release_run_lock(self.paths)

        self.events.append("terminal", diagnosis=diag.value, status=state.status)
        code = 130 if aborted else EXIT_CODES.get(diag, 1)
        return RunResult(
            run_id=state.run_id,
            diagnosis=diag,
            exit_code=code,
            report_path=str(self.paths.report),
            kicks=state.kicks,
            duration=time.time() - started,
            message="aborted by user" if aborted else diag.value,
        )

    @staticmethod
    def _budget_guard(diag: Diagnosis, state: RunState) -> Diagnosis:
        if diag in TERMINAL:
            return diag
        if state.kicks >= state.max_kicks:
            return Diagnosis.BREAKER
        if state.max_wall_clock and state.elapsed >= state.max_wall_clock:
            return Diagnosis.BREAKER
        return diag

    @staticmethod
    def _notes(diag: Diagnosis, obs: Observation) -> list[str]:
        notes: list[str] = []
        if diag is Diagnosis.TAMPER:
            notes.append("Bạn vừa sửa file test. Waker đã khôi phục bản gốc. Không được sửa test.")
        if diag is Diagnosis.THRASH:
            notes.append("Hai lần đánh thức liên tiếp không có tiến bộ nào. Đổi cách làm.")
        if diag is Diagnosis.FALSE_DONE:
            notes.append("Bạn báo xong nhưng gate vẫn đỏ. Chỉ báo xong khi test xanh thật.")
        if diag is Diagnosis.BREAKER and obs.max_cost_usd > 0 and obs.cost_usd >= obs.max_cost_usd:
            notes.append(
                f"Đã chạm hạn mức chi phí (${obs.cost_usd:.4f} / ${obs.max_cost_usd:.4f}). Dừng."
            )
        if obs.unscoped_changes:
            notes.append(
                "Thay đổi ngoài hợp đồng: " + ", ".join(obs.unscoped_changes[:5])
            )
        return notes
