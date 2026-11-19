"""Timeout profiles and phase-budget helpers.

Time values are kept in seconds internally. User-facing strings such as
``"45m"``, ``"2h"`` and ``"30s"`` are normalized by :func:`parse_duration`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

DEFAULT_PROFILE = "medium"


@dataclass(frozen=True, slots=True)
class Profile:
    """One run-level timeout profile."""

    name: str
    turn_timeout: float
    max_wall_clock: float
    verify_timeout: float
    freeze_after: float
    max_kicks: int


#: Keep ``medium`` in lockstep with the historical EngineConfig defaults.
PROFILES: dict[str, Profile] = {
    "small": Profile(
        name="small",
        turn_timeout=300.0,
        max_wall_clock=1200.0,
        verify_timeout=120.0,
        freeze_after=180.0,
        max_kicks=3,
    ),
    "medium": Profile(
        name="medium",
        turn_timeout=900.0,
        max_wall_clock=5400.0,
        verify_timeout=300.0,
        freeze_after=300.0,
        max_kicks=5,
    ),
    "large": Profile(
        name="large",
        turn_timeout=1800.0,
        max_wall_clock=18000.0,
        verify_timeout=900.0,
        freeze_after=600.0,
        max_kicks=8,
    ),
    "overnight": Profile(
        name="overnight",
        turn_timeout=2700.0,
        max_wall_clock=28800.0,
        verify_timeout=1800.0,
        freeze_after=900.0,
        max_kicks=12,
    ),
}

PROFILE_NAMES = tuple(PROFILES)

#: Fields that may be overridden by ``resolve_profile``.
PROFILE_FIELDS = frozenset(
    {
        "turn_timeout",
        "max_wall_clock",
        "verify_timeout",
        "freeze_after",
        "max_kicks",
    }
)

_UNIT_SECONDS = {
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}
_DURATION_PART = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[smhd])",
    re.IGNORECASE,
)


def parse_duration(value: str | int | float) -> float:
    """Convert a duration to seconds.

    Accepted forms are numbers (already seconds), ``"30s"``, ``"45m"``,
    ``"2h"``, ``"1h30m"`` and ``"1.5h"``. Negative, empty, or malformed
    durations raise :class:`ValueError`.
    """
    if isinstance(value, bool):
        raise ValueError(f"invalid duration: {value!r}")

    if isinstance(value, (int, float)):
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"invalid duration: {value!r}")
        return seconds

    if not isinstance(value, str):
        raise ValueError(f"invalid duration: {value!r}")

    text = value.strip().lower()
    if not text:
        raise ValueError("invalid duration: empty string")

    # A plain number is treated as seconds. This keeps CLI/config overrides
    # convenient while still supporting human-friendly unit suffixes.
    if text.replace(".", "", 1).isdigit():
        seconds = float(text)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"invalid duration: {value!r}")
        return seconds

    total = 0.0
    position = 0
    matched = False
    for match in _DURATION_PART.finditer(text):
        if text[position : match.start()].strip():
            raise ValueError(f"invalid duration: {value!r}")
        total += float(match.group("value")) * _UNIT_SECONDS[match.group("unit").lower()]
        position = match.end()
        matched = True

    if not matched or text[position:].strip():
        raise ValueError(f"invalid duration: {value!r}")
    return total


def resolve_profile(
    name: str = DEFAULT_PROFILE,
    overrides: Mapping[str, object] | None = None,
) -> Profile:
    """Return a profile with optional per-field overrides.

    ``overrides`` accepts ``turn_timeout``, ``max_wall_clock``,
    ``verify_timeout``, ``freeze_after`` and ``max_kicks``. Timeouts may be
    seconds or duration strings. ``None`` means "keep the profile default".
    """
    if not isinstance(name, str):
        raise ValueError(f"unknown profile: {name!r}")
    key = name.strip().lower()
    try:
        base = PROFILES[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown profile {name!r}; choose one of {', '.join(PROFILE_NAMES)}"
        ) from exc

    values: dict[str, object] = {
        "turn_timeout": base.turn_timeout,
        "max_wall_clock": base.max_wall_clock,
        "verify_timeout": base.verify_timeout,
        "freeze_after": base.freeze_after,
        "max_kicks": base.max_kicks,
    }
    for field, raw in (overrides or {}).items():
        if field not in PROFILE_FIELDS:
            raise ValueError(
                f"unknown profile field {field!r}; choose one of "
                f"{', '.join(sorted(PROFILE_FIELDS))}"
            )
        if raw is None:
            continue
        if field == "max_kicks":
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ValueError("max_kicks must be an integer")
            if raw < 1:
                raise ValueError("max_kicks must be >= 1")
            values[field] = raw
        else:
            seconds = parse_duration(raw)  # type: ignore[arg-type]
            if seconds <= 0:
                raise ValueError(f"{field} must be > 0")
            values[field] = seconds

    return Profile(name=key, **values)  # type: ignore[arg-type]


def validate_phase_budget(
    budgets: Iterable[float | int | str],
    profile: Profile | str = DEFAULT_PROFILE,
    reserve: float = 0.15,
) -> float:
    """Validate phase budgets against a profile's wall-clock cap.

    Returns the total phase budget in seconds. Raises :class:`ValueError` when
    a budget is invalid, no phases are supplied, or total budget plus the
    reserve exceeds ``max_wall_clock``.

    ``reserve`` is a fraction of the cap (default 15%) kept for verification,
    reporting and overruns.
    """
    resolved = resolve_profile(profile) if isinstance(profile, str) else profile
    if not isinstance(resolved, Profile):
        raise TypeError("profile must be a Profile or profile name")
    if isinstance(reserve, bool) or not isinstance(reserve, (int, float)):
        raise ValueError("reserve must be a fraction between 0 and 1")
    if not math.isfinite(float(reserve)) or not 0 <= reserve < 1:
        raise ValueError("reserve must be a fraction between 0 and 1")

    total = 0.0
    count = 0
    for raw in budgets:
        seconds = parse_duration(raw)
        if seconds <= 0:
            raise ValueError("phase budget must be > 0")
        total += seconds
        count += 1

    if count == 0:
        raise ValueError("at least one phase budget is required")

    reserved = resolved.max_wall_clock * float(reserve)
    if total + reserved > resolved.max_wall_clock:
        raise ValueError(
            f"phase budgets ({total:.0f}s) + reserve ({reserved:.0f}s) "
            f"exceed max_wall_clock ({resolved.max_wall_clock:.0f}s)"
        )
    return total
