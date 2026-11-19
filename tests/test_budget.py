from __future__ import annotations

import pytest

from waker.budget import (
    DEFAULT_PROFILE,
    PROFILE_NAMES,
    PROFILES,
    parse_duration,
    resolve_profile,
    validate_phase_budget,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("small", (300.0, 1200.0, 120.0, 180.0, 3)),
        ("medium", (900.0, 5400.0, 300.0, 300.0, 5)),
        ("large", (1800.0, 18000.0, 900.0, 600.0, 8)),
        ("overnight", (2700.0, 28800.0, 1800.0, 900.0, 12)),
    ],
)
def test_profiles_match_contract(name: str, expected: tuple[float, ...]):
    profile = PROFILES[name]
    assert (
        profile.turn_timeout,
        profile.max_wall_clock,
        profile.verify_timeout,
        profile.freeze_after,
        profile.max_kicks,
    ) == expected


def test_profile_names_and_default_are_stable():
    assert PROFILE_NAMES == ("small", "medium", "large", "overnight")
    assert DEFAULT_PROFILE == "medium"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("30s", 30.0),
        ("45m", 2700.0),
        ("2h", 7200.0),
        ("1h30m", 5400.0),
        ("1h 30m", 5400.0),
        ("1.5h", 5400.0),
        ("1d", 86400.0),
        (" 45M ", 2700.0),
        (90, 90.0),
        ("90", 90.0),
    ],
)
def test_parse_duration(value: str | int, expected: float):
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "abc", "-5m", "1x", "1h30", "1hm", "nan", True, -1, float("inf")],
)
def test_parse_duration_rejects_invalid_values(value: object):
    with pytest.raises(ValueError):
        parse_duration(value)  # type: ignore[arg-type]


def test_resolve_profile_default():
    assert resolve_profile() == PROFILES["medium"]
    assert resolve_profile("MEDIUM") == PROFILES["medium"]


def test_resolve_profile_overrides_and_ignores_none():
    profile = resolve_profile(
        "large",
        {
            "turn_timeout": "45m",
            "max_wall_clock": "2h",
            "verify_timeout": "10m",
            "freeze_after": None,
            "max_kicks": 7,
        },
    )
    assert profile.name == "large"
    assert profile.turn_timeout == 2700
    assert profile.max_wall_clock == 7200
    assert profile.verify_timeout == 600
    assert profile.freeze_after == 600
    assert profile.max_kicks == 7


def test_resolve_profile_rejects_bad_name_or_override():
    with pytest.raises(ValueError, match="unknown profile"):
        resolve_profile("huge")
    with pytest.raises(ValueError, match="unknown profile field"):
        resolve_profile("medium", {"unknown": 1})
    with pytest.raises(ValueError, match="must be > 0"):
        resolve_profile("medium", {"turn_timeout": "0s"})
    with pytest.raises(ValueError, match="max_kicks"):
        resolve_profile("medium", {"max_kicks": 0})
    with pytest.raises(ValueError, match="max_kicks"):
        resolve_profile("medium", {"max_kicks": 2.5})


def test_validate_phase_budget_accepts_valid_total():
    total = validate_phase_budget(["5m", "10m"], "small")
    assert total == 900


def test_validate_phase_budget_allows_exact_reserved_cap():
    # medium: 5400s cap - 810s reserve = 4590s available
    total = validate_phase_budget(["76.5m"], PROFILES["medium"])
    assert total == 4590


def test_validate_phase_budget_rejects_over_cap():
    with pytest.raises(ValueError, match="exceed max_wall_clock"):
        validate_phase_budget(["15m", "15m"], "small")


def test_validate_phase_budget_rejects_empty_zero_and_bad_reserve():
    with pytest.raises(ValueError, match="at least one"):
        validate_phase_budget([], "medium")
    with pytest.raises(ValueError, match="must be > 0"):
        validate_phase_budget(["0s"], "medium")
    for reserve in (-0.1, 1.0, True):
        with pytest.raises(ValueError, match="reserve"):
            validate_phase_budget(["5m"], "medium", reserve=reserve)  # type: ignore[arg-type]


def test_validate_phase_budget_rejects_unknown_profile():
    with pytest.raises(ValueError, match="unknown profile"):
        validate_phase_budget(["5m"], "unknown")  # type: ignore[arg-type]
