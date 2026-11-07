from __future__ import annotations

from waker import opencode_events
from waker.adapters.base import TurnContext
from waker.adapters.opencode import OpenCodeAdapter

SAMPLE = "\n".join(
    [
        '{"type":"step_start","timestamp":1,"sessionID":"ses_abc","part":{"type":"step-start"}}',
        '{"type":"text","timestamp":2,"sessionID":"ses_abc","part":{"type":"text","text":"OK"}}',
        "not json at all",
        '{"type":"tool","timestamp":3,"sessionID":"ses_abc","part":{"type":"tool","tool":"write"}}',
    ]
)


def test_parse_events_skips_noise():
    events = opencode_events.parse_events(SAMPLE)
    assert [event["type"] for event in events] == ["step_start", "text", "tool"]
    assert opencode_events.event_session(events) == "ses_abc"
    assert opencode_events.event_text(events) == "OK"


def test_usage_from_export():
    payload = {
        "info": {
            "cost": 0.001234,
            "tokens": {
                "input": 100,
                "output": 20,
                "reasoning": 5,
                "cache": {"read": 7, "write": 3},
            },
        }
    }
    usage = opencode_events.usage_from_export(payload)
    assert usage.ok
    assert usage.cost_usd == 0.001234
    assert usage.tokens == 135


def test_usage_export_handles_missing_fields():
    usage = opencode_events.usage_from_export({"info": {}})
    assert usage.ok
    assert usage.cost_usd == 0
    assert usage.tokens == 0


def test_read_session_usage_missing_binary_is_safe():
    usage = opencode_events.read_session_usage("ses_x", ".", binary="definitely-not-a-binary")
    assert usage.ok is False
    assert usage.cost_usd == 0


def test_command_contains_session_and_model():
    adapter = OpenCodeAdapter(model="opencode-go/deepseek-v4.1-flash")
    ctx = TurnContext(repo=".", run_id="r1", session_id="ses_1", kick=0, timeout=10)
    command = adapter.build_command("làm task A", ctx)
    assert "--session ses_1" in command
    assert "--format json" in command
    assert "--auto" in command
    assert "--model opencode-go/deepseek-v4.1-flash" in command
    assert "làm task A" in command


def test_argv_keeps_prompt_verbatim():
    """The prompt must be a single argv element - no shell parsing."""
    adapter = OpenCodeAdapter(model="m")
    ctx = TurnContext(repo=".", run_id="r1", session_id="ses_1", kick=0, timeout=10)
    prompt = 'làm "task" C:\\path\\file.py -c "x"'
    argv = adapter.build_argv(prompt, ctx)
    assert isinstance(argv, list)
    assert argv[-1] == prompt
    assert argv[1:3] == ["run", "--session"]
    assert "--format" in argv and "json" in argv
