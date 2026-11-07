"""Claude Code stream-json parsing.

Claude Code emits newline-delimited JSON with ``type`` in
``system | assistant | user | result``. The ``result`` event carries
``total_cost_usd``, ``usage`` and ``session_id``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ClaudeTurnInfo:
    session_id: str | None = None
    cost_usd: float = 0.0
    tokens: int = 0
    text: str = ""
    is_error: bool = False
    permission_denied: bool = False


def parse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "type" in event:
            events.append(event)
    return events


def _sum_usage(usage: dict) -> int:
    total = 0
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        try:
            total += int(usage.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def extract_info(events: list[dict]) -> ClaudeTurnInfo:
    info = ClaudeTurnInfo()
    for event in events:
        session_id = event.get("session_id")
        if session_id and not info.session_id:
            info.session_id = str(session_id)

        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message") or {}
            for part in message.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "text":
                    info.text += str(part.get("text") or "")
        elif kind == "result":
            try:
                info.cost_usd = float(event.get("total_cost_usd") or 0.0)
            except (TypeError, ValueError):
                info.cost_usd = 0.0
            info.tokens = _sum_usage(event.get("usage") or {})
            info.is_error = bool(event.get("is_error")) or event.get("subtype") == "error"
            if not info.text:
                info.text = str(event.get("result") or "")

        blob = json.dumps(event, ensure_ascii=False).lower()
        if "permission" in blob and (
            "denied" in blob or "not allowed" in blob or "requires approval" in blob
        ):
            info.permission_denied = True
    return info
