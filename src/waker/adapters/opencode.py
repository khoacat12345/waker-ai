"""OpenCode adapter (tier 1: native session resume).

Phase 1 keeps this thin: it builds the documented command and delegates process
handling to :class:`GenericProcessAdapter`. JSON event parsing and live probing
are Phase 2 work.

Command used:

    opencode run --session <id> --auto --format json --model <m> "<prompt>"
"""

from __future__ import annotations

from .generic import GenericProcessAdapter, quote_arg


class OpenCodeAdapter(GenericProcessAdapter):
    name = "opencode"

    def __init__(self, model: str | None = None, extra_args: str = "") -> None:
        self.model = model
        self.extra_args = extra_args
        command = "opencode run --session {session} --auto --format json"
        if model:
            command += f" --model {model}"
        if extra_args:
            command += f" {extra_args}"
        command += " {prompt}"
        super().__init__(command)

    def _build(self, prompt, ctx):  # type: ignore[override]
        # ``{prompt}`` is already quoted by the base implementation; nothing else
        # to do here yet.
        return super()._build(prompt, ctx)


__all__ = ["OpenCodeAdapter", "quote_arg"]
