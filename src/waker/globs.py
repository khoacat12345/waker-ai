"""Deterministic glob matching with ``**`` support.

``fnmatch`` alone lets ``*`` cross ``/`` boundaries, which would make
``src/*.py`` match ``src/a/b.py``. For scope gating that is wrong: scope must be
precise, otherwise evidence can drift into a different task.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

WILDCARDS = ("*", "?", "[")


def normalize(path: str) -> str:
    """Normalise a filesystem path to a POSIX-style relative path."""
    value = str(path).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.strip("/")


def _split(value: str) -> list[str]:
    return [part for part in normalize(value).split("/") if part]


def _match_parts(pattern: list[str], parts: list[str]) -> bool:
    if not pattern:
        return not parts
    head = pattern[0]
    if head == "**":
        # ``**`` matches zero or more path segments.
        if _match_parts(pattern[1:], parts):
            return True
        return bool(parts) and _match_parts(pattern, parts[1:])
    if not parts:
        return False
    if fnmatchcase(parts[0], head):
        return _match_parts(pattern[1:], parts[1:])
    return False


def matches(path: str, pattern: str) -> bool:
    """Return True if *path* is covered by *pattern*.

    Rules:
    - ``**`` matches any number of segments (including zero).
    - ``*`` matches inside one segment only.
    - A trailing ``/`` is treated as ``/**``.
    - A pattern with no wildcard also matches its subtree (dir semantics).
    """
    if not pattern:
        return False
    pat = normalize(pattern)
    if pat.endswith("/"):
        pat += "**"

    path_parts = _split(path)
    pat_parts = _split(pat)

    if _match_parts(pat_parts, path_parts):
        return True

    # Directory semantics: "docs/api" also covers "docs/api/x.md".
    if not any(ch in pat for ch in WILDCARDS):
        return len(path_parts) > len(pat_parts) and path_parts[: len(pat_parts)] == pat_parts
    return False


def matches_any(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(matches(path, pattern) for pattern in patterns)


def filter_paths(paths: list[str], patterns: list[str]) -> list[str]:
    return [p for p in paths if matches_any(p, patterns)]


def overlaps(left: str, right: str) -> bool:
    """Conservative overlap check used by the contract linter.

    Two patterns overlap if their literal prefixes are in a prefix
    relationship, or if they are identical. This catches the common mistakes
    (``src/**`` vs ``src/pay/**``) without pretending to be a full glob algebra.
    """
    a = normalize(left)
    b = normalize(right)
    if a == b:
        return True

    def literal_prefix(pattern: str) -> str:
        for index, char in enumerate(pattern):
            if char in WILDCARDS:
                return pattern[:index]
        return pattern

    pa = literal_prefix(a)
    pb = literal_prefix(b)
    if not pa or not pb:
        return True
    return pa.startswith(pb) or pb.startswith(pa)
