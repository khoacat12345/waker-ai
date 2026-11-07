"""Real OpenCode end-to-end test. Disabled unless explicitly enabled.

    $env:WAKER_LIVE_TEST=1
    $env:WAKER_LIVE_MODEL="opencode-go/deepseek-v4.1-flash"   # optional
    pytest tests/test_live_opencode.py -q -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import exists_cmd

from waker.adapters.opencode import OpenCodeAdapter
from waker.engine import Engine, EngineConfig
from waker.models import Diagnosis, Task

pytestmark = pytest.mark.skipif(
    os.environ.get("WAKER_LIVE_TEST") != "1",
    reason="set WAKER_LIVE_TEST=1 to run the real OpenCode test",
)


def test_real_opencode_session_resume_and_cost(repo: Path):
    model = os.environ.get("WAKER_LIVE_MODEL", "opencode-go/deepseek-v4.1-flash")
    task = Task(
        id="T1",
        desc="create src/live.txt",
        scope=["src/live.txt"],
        verify=exists_cmd("src/live.txt"),
    )
    config = EngineConfig(
        repo=str(repo),
        tasks=[task],
        agent_command=f"opencode:{model}",
        test_command=None,
        max_kicks=1,
        turn_timeout=240,
        verify_timeout=60,
        freeze_after=180,
        max_cost_usd=0.5,
    )
    result = Engine(config, OpenCodeAdapter(model=model)).run()

    assert result.diagnosis is Diagnosis.DONE
    assert (repo / "src" / "live.txt").exists()
    assert result.exit_code == 0
