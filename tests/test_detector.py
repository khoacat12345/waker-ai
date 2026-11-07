from __future__ import annotations

from waker.detector import diagnose
from waker.models import Diagnosis, Observation


def obs(**kwargs) -> Observation:
    base = dict(
        turn_state="exited",
        exit_code=0,
        elapsed=10,
        last_event_age=0,
        diff_hash="d1",
        prev_diff_hash="d0",
        test_exit=1,
        has_test=True,
        all_tasks_done=False,
        integrity_ok=True,
        kicks=0,
        max_kicks=5,
        alive_threshold=120,
        freeze_after=300,
        stall_after=240,
    )
    base.update(kwargs)
    return Observation(**base)


def test_alive_wins_when_agent_is_working():
    assert diagnose(obs(turn_state="running", last_event_age=5)) is Diagnosis.ALIVE


def test_tamper_outranks_done():
    assert diagnose(obs(tamper=True, all_tasks_done=True, test_exit=0)) is Diagnosis.TAMPER


def test_blocked_is_terminal_even_with_work_left():
    assert diagnose(obs(blocked_reason="need token")) is Diagnosis.BLOCKED


def test_frozen_when_running_but_unchanged():
    assert (
        diagnose(
            obs(turn_state="running", last_event_age=400, diff_hash="d1", prev_diff_hash="d1")
        )
        is Diagnosis.FROZEN
    )


def test_not_frozen_if_diff_moved():
    assert (
        diagnose(
            obs(turn_state="running", last_event_age=400, diff_hash="d2", prev_diff_hash="d1")
        )
        is Diagnosis.PARTIAL
    )


def test_done_requires_green_test_and_all_tasks():
    assert diagnose(obs(all_tasks_done=True, test_exit=0)) is Diagnosis.DONE
    assert diagnose(obs(all_tasks_done=True, test_exit=1)) is not Diagnosis.DONE


def test_done_allows_no_test_command():
    assert diagnose(obs(all_tasks_done=True, test_exit=None, has_test=False)) is Diagnosis.DONE


def test_suspect_test_branches_before_false_done():
    assert (
        diagnose(obs(suspect_test=True, claimed_done=True, test_exit=1))
        is Diagnosis.SUSPECT_TEST
    )


def test_false_done_when_claim_meets_red_gate():
    assert diagnose(obs(claimed_done=True, test_exit=1)) is Diagnosis.FALSE_DONE


def test_thrash_after_two_identical_fingerprints():
    assert diagnose(obs(same_fingerprint_streak=2)) is Diagnosis.THRASH


def test_stall_after_one_identical_fingerprint():
    assert diagnose(obs(same_fingerprint_streak=1, elapsed=300)) is Diagnosis.STALL


def test_breaker_when_kicks_exhausted():
    assert diagnose(obs(kicks=5, max_kicks=5)) is Diagnosis.BREAKER


def test_partial_is_the_fallback():
    assert diagnose(obs(same_fingerprint_streak=0)) is Diagnosis.PARTIAL
