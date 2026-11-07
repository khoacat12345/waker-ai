"""LLM planner bridge: one agent turn turns a vague prompt into a contract.

This is the only place waker spends tokens on planning. The output is still
validated by the deterministic linter, so a bad plan fails closed instead of
becoming a bad run.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path
from typing import Callable

from . import planner
from .opencode_events import event_text, parse_events, read_session_usage, resolve_opencode_binary
from .process import run_live

FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

META_PROMPT = """You are waker's planning compiler.

Convert the user's request into a YAML contract. Output ONLY the YAML document:
no markdown fences, no commentary, no questions.

Schema:

tasks:
  - id: T1
    desc: "short description"
    scope: ["src/auth/**", "tests/auth/**"]
    verify: "pytest tests/auth -q"
    depends_on: []
  - id: C1
    desc: "never use tailwind"
    kind: constraint
    check: "python -c \\"import sys,pathlib; ...\\""

Rules:
1. A task is the smallest unit that one verify command can prove.
2. scope must be globs; two tasks must NOT share a scope.
3. verify must exit 0 only when the task is genuinely done. Never use "true",
   "echo", or an empty command.
4. Prefer commands that already exist in the repo. Use the file list below to
   choose real paths.
5. If the request implies credentials/deploy, write a task with a clear scope
   and a verify that can run locally; do not invent secrets.
6. At most 12 tasks. No duplicate ids.
7. If the request is a single feature, one task is fine; do not pad.

Repository: {repo}
Files (first {count}):
{files}

User request (verbatim):
{prompt}

YAML:"""


def extract_yaml(text: str) -> str:
    """Pull the YAML document out of an agent reply."""
    match = FENCE_RE.search(text)
    if match:
        candidate = match.group(1)
    else:
        start = text.find("tasks:")
        if start < 0:
            start = text.find("constraints:")
        if start < 0:
            raise ValueError("planner reply contains no `tasks:` YAML")
        candidate = text[start:]
    candidate = candidate.strip()
    if not candidate:
        raise ValueError("planner reply contains an empty YAML document")
    return candidate


def build_meta_prompt(prompt: str, repo: str | Path, limit: int = 200) -> str:
    files = planner._repo_files(repo)[:limit]
    listing = "\n".join(f"- {name}" for name in files) or "- (empty repo)"
    return META_PROMPT.format(
        repo=str(Path(repo).resolve()),
        count=len(files),
        files=listing,
        prompt=prompt.strip(),
    )


def run_opencode_plan(
    meta_prompt: str,
    repo: str | Path,
    model: str | None = None,
    binary: str | None = None,
    timeout: float = 300.0,
) -> str:
    executable = resolve_opencode_binary(binary or "opencode")
    session = f"ses_waker_plan_{secrets.token_hex(4)}"
    argv = [
        executable,
        "run",
        "--session",
        session,
        "--auto",
        "--format",
        "json",
    ]
    if model:
        argv.extend(["--model", model])
    argv.append(meta_prompt)

    result = run_live(argv, cwd=str(repo), timeout=timeout)
    if result.exit_code != 0:
        tail = result.output[-800:]
        raise RuntimeError(f"opencode planning turn failed ({result.exit_code}): {tail}")
    text = event_text(parse_events(result.output))
    if not text.strip():
        raise RuntimeError("opencode planning turn returned no text")

    usage = read_session_usage(session, str(repo), binary=binary or "opencode")
    if usage.ok:
        print(
            f"[waker] plan: ${usage.cost_usd:.4f}, {usage.tokens} tokens",
            file=sys.stderr,
        )
    return text


def generate_contract(
    prompt: str,
    repo: str | Path,
    model: str | None = None,
    binary: str | None = None,
    timeout: float = 300.0,
    runner: Callable[[str], str] | None = None,
) -> planner.PlanBundle:
    """One planning turn -> validated PlanBundle (lint is the caller's job)."""
    meta = build_meta_prompt(prompt, repo)
    if runner is None:
        raw = run_opencode_plan(
            meta, repo=repo, model=model, binary=binary, timeout=timeout
        )
    else:
        raw = runner(meta)
    bundle = planner.parse_contract_text(extract_yaml(raw))
    if not bundle.all_tasks():
        raise ValueError("planner produced zero tasks")
    return bundle
