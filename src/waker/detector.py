"""Pure diagnosis: Observation -> Diagnosis.

No I/O, no subprocess, no clock. Every branch is testable in isolation.

Priority order (deviates from the design table in one place on purpose:
``BREAKER`` must be evaluated before ``PARTIAL``, otherwise a run that reached
``max_kicks`` would return ``PARTIAL`` forever and never stop).
"""

from __future__ import annotations

from .models import Diagnosis, Observation


def diagnose(obs: Observation) -> Diagnosis:
    # 1. Agent is actively working - leave it alone.
    if obs.turn_state == "running" and obs.last_event_age < obs.alive_threshold:
        return Diagnosis.ALIVE

    # 2. The exam was edited. This outranks DONE: a tampered test that passes
    #    looks exactly like success.
    if obs.vault_tamper:
        return Diagnosis.VAULT_TAMPER
    if obs.tamper:
        return Diagnosis.TAMPER

    # 3. The agent admitted it is blocked. Stop; do not burn kicks.
    if obs.blocked_reason:
        return Diagnosis.BLOCKED

    # 4. Process alive but nothing changed for too long.
    if obs.turn_state == "running" and obs.last_event_age >= obs.freeze_after:
        unchanged = obs.prev_diff_hash is None or obs.diff_hash == obs.prev_diff_hash
        if unchanged:
            return Diagnosis.FROZEN

    # 5. Real success: every task has evidence and the gate is green.
    test_ok = (not obs.has_test) or obs.test_exit == 0
    if obs.all_tasks_done and test_ok and obs.integrity_ok and obs.hidden_ok:
        return Diagnosis.DONE

    # 5b. Cost guard: never let a retry loop burn the budget.
    if obs.max_cost_usd > 0 and obs.cost_usd >= obs.max_cost_usd:
        return Diagnosis.BREAKER

    # 5c. Hidden tests failed, or the hidden suite itself is broken.
    if obs.hidden_suspect:
        return Diagnosis.SUSPECT_TEST
    if obs.hidden_failed > 0:
        return Diagnosis.HIDDEN_FAIL

    # 6. Every failure looks like a broken test, not broken code.
    if obs.suspect_test:
        return Diagnosis.SUSPECT_TEST

    # 7. Agent claimed success while the gate is red.
    if obs.claimed_done and obs.has_test and obs.test_exit != 0:
        return Diagnosis.FALSE_DONE

    # 8. Same fingerprint twice in a row: the agent is going in circles.
    if obs.same_fingerprint_streak >= 2:
        return Diagnosis.THRASH

    # 9. One stalled kick is not enough to thrash, but worth a nudge.
    if obs.same_fingerprint_streak >= 1 and obs.elapsed >= obs.stall_after:
        return Diagnosis.STALL

    # 10. Budget exhausted.
    if obs.kicks >= obs.max_kicks:
        return Diagnosis.BREAKER
    if obs.max_wall_clock and obs.elapsed_total >= obs.max_wall_clock:
        return Diagnosis.BREAKER

    # 11. Fallback: work remains, keep going.
    return Diagnosis.PARTIAL


def is_terminal(diag: Diagnosis) -> bool:
    from .models import TERMINAL

    return diag in TERMINAL
