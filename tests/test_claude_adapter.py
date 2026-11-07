from __future__ import annotations

from waker.adapters.base import TurnContext
from waker.adapters.claude import ClaudeAdapter
from waker.claude_events import extract_info, parse_events

SAMPLE = "\n".join(
    [
        '{"type":"system","subtype":"init","session_id":"cli-1"}',
        '{"type":"assistant","session_id":"cli-1","message":{"content":[{"type":"text","text":"done"}]}}',
        '{"type":"result","subtype":"success","session_id":"cli-1","total_cost_usd":0.0123,'
        '"usage":{"input_tokens":100,"output_tokens":20,"cache_read_input_tokens":5},"result":"done"}',
    ]
)


def test_stream_parsing():
    events = parse_events(SAMPLE)
    info = extract_info(events)
    assert [event["type"] for event in events] == ["system", "assistant", "result"]
    assert info.session_id == "cli-1"
    assert info.text == "done"
    assert abs(info.cost_usd - 0.0123) < 1e-9
    assert info.tokens == 125
    assert info.is_error is False


def test_permission_denied_is_detected():
    events = [
        {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "result": "Permission to use Bash has been denied",
        }
    ]
    info = extract_info(events)
    assert info.permission_denied is True


def test_argv_without_resume_first_turn():
    adapter = ClaudeAdapter(permission_mode="acceptEdits")
    ctx = TurnContext(repo=".", run_id="r", session_id="ses", kick=0, timeout=10)
    argv = adapter.build_argv("làm việc", ctx)
    assert argv[:5] == ["claude", "-p", "--output-format", "stream-json", "--verbose"]
    assert "--permission-mode" in argv and "acceptEdits" in argv
    assert "--resume" not in argv
    assert argv[-1] == "làm việc"


def test_argv_resumes_known_session():
    adapter = ClaudeAdapter()
    ctx = TurnContext(
        repo=".", run_id="r", session_id="ses", kick=1, timeout=10, resume_id="cli-42"
    )
    argv = adapter.build_argv("continue", ctx)
    index = argv.index("--resume")
    assert argv[index + 1] == "cli-42"
