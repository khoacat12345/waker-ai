"""A tiny text-mode TUI used to test the PTY adapter without an AI."""

from __future__ import annotations

import sys

print("fake-tui ready", flush=True)
print("PROMPT> ", end="", flush=True)
for line in sys.stdin:
    text = line.strip()
    if text == "quit":
        break
    print(f"ECHO:{text}", flush=True)
    print("PROMPT> ", end="", flush=True)
print("BYE", flush=True)
