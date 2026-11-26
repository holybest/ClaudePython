"""!
@brief SWU-03~05 컨트롤러·우선순위 판정·규칙 단위 시험 (SWDD 4~6장, SWRS SWR-001~009, 013, 017~022).
"""

import pytest
from tests.unit.helpers import DROP, cmd, summary

from child_lock.core import controller as ctl_mod
from child_lock.core import model as m

R, L = "RELEASE", "LOCK"


# ---------------------------------------------------------------- 초기 상태 (DEF-06)


def test_tick_before_first_snapshot_is_off_release_without_monitoring(h):
    d = h.tick(5.0)
    assert summary(d) == (R, R, "OFF", "NONE", "NO_CHANGE", ())
    assert d.input_validity == m.all_invalid()
    assert d.timestamp_s == 5.0
    assert h.ctl.last_decision == d


def test_last_decision_before_any_evaluation_is_initial_decision(h):
    assert h.ctl.last_decision == m.initial_decision(0.0)


def test_first_normal_snapshot_keeps_initial_release(h):
    d = h.send(1.0)
    assert summary(d) == (R, R, "NORMAL", "NONE", "NO_CHANGE", ())
    assert d.input_validity == m.all_valid()
    assert d.timestamp_s == 1.0


# ---------------------------------------------------------------- 운전자 명령 (SWR-001, 002, 004)


@pytest.mark.parametrize("source", ["physical_button", "avn", "voice", "mobile_app"])
@pytest.mark.parametrize(
    ("side", "expected"), [("left", (R, L)), ("right", (L, R)), ("all", (R, R))]
)
def test_unlock_command_applies_only_to_selected_sides(locked, source, side, expected):
    h = locked()
    d = h.send(0.1, command=cmd(side, "unlock", source))
    assert summary(d) == (*expected, "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK", ())


@pytest.mark.parametrize("source", ["physical_button", "avn", "voice", "mobile_app"])
@pytest.mark.parametrize(
    ("side", "expected"), [("left", (L, R)), ("right", (R, L)), ("all", (L, L))]
)
def test_lock_command_applies_only_to_selected_sides(h, source, side, expected):
    d = h.send(0.1, command=cmd(side, "lock", source))
    assert summary(d) == (*expected, "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK", ())


def test_invalid_command_is_rejected_but_other_rules_still_apply(h):
    d = h.send(0.1, vehicle_speed_kph=3.0, command={"side": "center", "action": "lock"})
    assert summary(d) == (L, L, "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ("COMMAND_REJECTED",))
    assert d.input_validity.if_004 is m.Validity.INVALID


def test_invalid_command_alone_changes_no_output(locked):
    h = locked()
    d = h.send(0.1, command={"side": "left", "action": "open", "source": "avn"})
    assert summary(d) == (L, L, "NORMAL", "NONE", "NO_CHANGE", ("COMMAND_REJECTED",))


def test_same_command_in_consecutive_snapshots_is_one_input(locked):
    h = locked()
    h.send(0.1, command=cmd("left", "unlock"))
    h.send(0.15, command=cmd("right", "lock"))  # 다른 명령 → 새 입력
    d = h.send(0.2, command=cmd("right", "lock"))  # 같은 명령 반복 → 새 입력 아님
    assert summary(d) == (R, L, "NORMAL", "NONE", "NO_CHANGE", ())


@pytest.mark.parametrize(
    ("speed", "expected"),
    [
        (2.9, (R, L, "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK", ())),
        (3.0, (L, L, "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ("DRIVER_UNLOCK_REJECTED",))),
    ],
)
def test_unlock_speed_boundary(locked, speed, expected):
    h = locked()
    assert summary(h.send(0.1, vehicle_speed_kph=speed, command=cmd("left", "unlock"))) == expected


def test_unlock_rejected_when_speed_group_invalid(locked):
    h = locked()
    d = h.send(0.1, vehicle_speed_kph=-1.0, command=cmd("left", "unlock"))
    assert summary(d) == (L, L, "NORMAL", "NONE", "NO_CHANGE", ("DRIVER_UNLOCK_REJECTED",))


def test_unlock_rejected_when_isofix_group_invalid(locked):
    h = locked()
    d = h.send(0.1, isofix_left=1, command=cmd("left", "unlock"))
    assert summary(d) == (L, L, "NORMAL", "NONE", "NO_CHANGE", ("DRIVER_UNLOCK_REJECTED",))


def test_unlock_rejected_on_isofix_side_only(locked):
    h = locked()
    d = h.send(0.1, isofix_left=True, command=cmd("all", "unlock"))
    assert summary(d) == (L, R, "NORMAL", "ISOFIX", "ISOFIX", ("DRIVER_UNLOCK_REJECTED",))


def test_unlock_rejected_while_degraded(locked):
    h = locked()
    d = h.send(0.1, crash_status="BAD", command=cmd("left", "unlock"))
    assert summary(d) == (
        L,
        L,
        "DEGRADED",
        "DEGRADED",
        "INPUT_INVALID",
        ("DRIVER_UNLOCK_REJECTED",),
    )


def test_lock_command_on_side_decided_by_higher_rule_is_ignored_silently(h):
    d = h.send(0.1, fire_detected=True, command=cmd("left", "lock"))
    assert summary(d) == (R, R, "NORMAL", "FORCED_RELEASE", "FIRE", ())


# ---------------------------------------------------------------- 주행 자동 잠금 (SWR-003)


def test_auto_lock_boundary_and_no_auto_release(h):
    assert summary(h.send(0.1, vehicle_speed_kph=2.9))[:2] == (R, R)
    assert summary(h.send(0.2, vehicle_speed_kph=3.0)) == (
        L,
        L,
        "NORMAL",
        "AUTO_LOCK",
        "AUTO_LOCK_SPEED",
        (),
    )
    assert summary(h.send(0.3, vehicle_speed_kph=0.0)) == (L, L, "NORMAL", "NONE", "NO_CHANGE", ())


# ---- 접근위험·override (SWR-005, 006, 009)


def _suppressed_left(h, t=1.0):
    """좌 위험 TRUE에서 첫 해제 요청을 넣어 억제 상태로 만든다 (6.3 #3)."""
    return h.send(t, rear_left_approach_risk=True, command=cmd("left", "unlock"))


def test_risk_locks_only_that_side(h):
    d = h.send(0.1, rear_left_approach_risk=True)
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


def test_first_unlock_request_on_risk_side_is_suppressed(h):
    d = _suppressed_left(h)
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ("UNLOCK_SUPPRESSED",))


def test_reinput_within_window_after_release_of_button_is_override(h):
    _suppressed_left(h, 1.0)
    h.send(1.05, rear_left_approach_risk=True)  # 명령 없는 스냅샷
    d = h.send(6.0, rear_left_approach_risk=True, command=cmd("left", "unlock"))
    assert summary(d) == (R, R, "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE", ())


def test_same_command_held_across_snapshots_and_ticks_is_not_override(h):
    _suppressed_left(h, 1.0)
    h.tick(1.05)
    d = h.send(6.0, rear_left_approach_risk=True, command=cmd("left", "unlock"))
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


@pytest.mark.parametrize(
    ("elapsed", "override"), [(10.0, True), (10.001, False), (-0.001, False), (0.0, True)]
)
def test_override_window_boundaries(h, elapsed, override):
    _suppressed_left(h, 20.0)  # t0 = 20.0
    h.send(20.0, rear_left_approach_risk=True)  # 명령 없는 스냅샷
    t = 20.0 + elapsed  # 재요청 시각
    d = h.send(max(t, 20.0), ts=t, rear_left_approach_risk=True, command=cmd("left", "unlock"))
    if override:
        assert summary(d)[:2] == (R, R) and d.reason_code is m.ReasonCode.APPROACH_OVERRIDE
    else:
        assert summary(d) == (
            L,
            R,
            "NORMAL",
            "APPROACH_RISK",
            "APPROACH_RISK",
            ("UNLOCK_SUPPRESSED",),
        )


def test_override_persists_while_risk_then_ends_when_risk_clears(h):
    _suppressed_left(h, 1.0)
    h.send(1.05, rear_left_approach_risk=True)
    h.send(2.0, rear_left_approach_risk=True, command=cmd("left", "unlock"))
    d = h.send(2.05, rear_left_approach_risk=True)
    assert summary(d) == (R, R, "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE", ())
    d = h.send(2.1)  # 위험 해소 → override 종료, 출력 유지
    assert summary(d) == (R, R, "NORMAL", "NONE", "NO_CHANGE", ())
    d = h.send(2.15, rear_left_approach_risk=True)  # 위험 재발생 → 다시 잠금
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


def _override_left(h):
    _suppressed_left(h, 1.0)
    h.send(1.05, rear_left_approach_risk=True)
    return h.send(2.0, rear_left_approach_risk=True, command=cmd("left", "unlock"))


def test_lock_command_ends_override_and_locks_that_side(h):
    _override_left(h)
    d = h.send(2.1, rear_left_approach_risk=True, command=cmd("left", "lock"))
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


def test_sensor_fault_ends_override(h):
    _override_left(h)
    h.send(2.1, rear_left_approach_risk=True, sensor_fault=True)
    d = h.send(2.15, rear_left_approach_risk=True)
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


def test_override_not_allowed_while_degraded(h):
    _suppressed_left(h, 1.0)
    h.send(1.05, rear_left_approach_risk=True)
    d = h.send(2.0, rear_left_approach_risk=True, ignition_on=DROP, command=cmd("left", "unlock"))
    assert summary(d) == (
        L,
        R,
        "DEGRADED",
        "APPROACH_RISK",
        "APPROACH_RISK",
        ("UNLOCK_SUPPRESSED",),
    )


def test_stale_unlock_request_does_not_record_suppression_time(h):
    h.send(1.0, rear_left_approach_risk=True)
    d = h.send(1.5, ts=1.0, rear_left_approach_risk=True, command=cmd("left", "unlock"))
    assert summary(d) == (
        L,
        R,
        "DEGRADED",
        "APPROACH_RISK",
        "APPROACH_RISK",
        ("UNLOCK_SUPPRESSED",),
    )
    h.send(1.6, rear_left_approach_risk=True)
    d = h.send(2.0, rear_left_approach_risk=True, command=cmd("left", "unlock"))
    assert summary(d)[5] == ("UNLOCK_SUPPRESSED",)  # 첫 요청으로 처리


def test_all_unlock_with_risk_on_left_releases_right_only(locked):
    h = locked()
    d = h.send(0.1, rear_left_approach_risk=True, command=cmd("all", "unlock"))
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ("UNLOCK_SUPPRESSED",))


def test_override_reason_wins_when_other_side_is_locked_by_risk(h):
    both = {"rear_left_approach_risk": True, "rear_right_approach_risk": True}
    h.send(1.0, command=cmd("right", "unlock"), **both)
    h.send(1.05, **both)
    d = h.send(2.0, command=cmd("right", "unlock"), **both)
    assert summary(d) == (L, R, "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE", ())


# ---------------------------------------------------------------- 충돌 (SWR-007, 008, 020)


def test_crash_confirmed_releases_and_latches_against_everything(locked):
    h = locked()
    d = h.send(0.1, crash_status="CONFIRMED", vehicle_speed_kph=50.0)
    assert summary(d) == (R, R, "EMERGENCY", "CRASH", "CRASH_CONFIRMED", ())
    d = h.send(
        0.2,
        crash_status="NONE",
        vehicle_speed_kph=50.0,
        rear_left_approach_risk=True,
        isofix_right=True,
        command=cmd("all", "lock"),
    )
    assert summary(d) == (R, R, "EMERGENCY", "CRASH", "CRASH_CONFIRMED", ())
    assert summary(h.tick(5.0)) == (R, R, "EMERGENCY", "CRASH", "CRASH_CONFIRMED", ())


@pytest.mark.parametrize(
    "changes",
    [
        {"ts": 0.0},  # 지연 스냅샷
        {"vehicle_speed_kph": -5.0},  # IF-001 무효
        {"sensor_fault": True, "rear_left_approach_risk": True},  # 6.3 #7
        {"ignition_on": "x"},  # IF-009 무효
    ],
)
def test_crash_confirmed_applies_regardless_of_staleness_or_other_invalid_groups(locked, changes):
    h = locked()
    d = h.send(1.0, crash_status="CONFIRMED", **changes)
    assert summary(d)[:5] == (R, R, "EMERGENCY", "CRASH", "CRASH_CONFIRMED")


def test_crash_pending_changes_nothing_and_adds_notice(locked):
    h = locked()
    d = h.send(0.1, crash_status="PENDING")
    assert summary(d) == (L, L, "NORMAL", "NONE", "NO_CHANGE", ("CRASH_PENDING",))


def test_ignition_off_clears_crash_latch(h):
    h.send(0.1, crash_status="CONFIRMED")
    d = h.send(0.2, ignition_on=False)
    assert summary(d) == (R, R, "OFF", "IGNITION_OFF", "IGNITION_OFF", ())
    d = h.send(0.3, vehicle_speed_kph=10.0)
    assert summary(d) == (L, L, "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ())


def test_ignition_off_with_confirmed_relatches(h):
    h.send(0.1, crash_status="CONFIRMED")
    d = h.send(0.2, ignition_on=False, crash_status="CONFIRMED")
    assert summary(d) == (R, R, "EMERGENCY", "CRASH", "CRASH_CONFIRMED", ())


def test_stale_ignition_off_does_not_clear_crash_latch(h):
    h.send(1.0, crash_status="CONFIRMED")
    d = h.send(2.0, ts=1.0, ignition_on=False)  # 6.3 #13
    assert summary(d) == (R, R, "EMERGENCY", "CRASH", "CRASH_CONFIRMED", ())


def test_ignition_off_during_sensor_fault_does_not_clear_latch(h):
    h.send(0.1, crash_status="CONFIRMED")
    h.send(0.2, ignition_on=False, sensor_fault=True)
    d = h.send(0.3)
    assert d.state is m.State.EMERGENCY


def test_crash_clears_override(h):
    _override_left(h)
    h.send(2.1, rear_left_approach_risk=True, crash_status="CONFIRMED")
    h.send(2.2, ignition_on=False)
    d = h.send(2.3, rear_left_approach_risk=True)
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


# ---------------------------------------------------------------- 센서 고장 (SWR-021)


def test_sensor_fault_holds_outputs_against_commands_and_risk(locked):
    h = locked()
    d = h.send(
        0.1,
        sensor_fault=True,
        rear_left_approach_risk=True,
        vehicle_speed_kph=0.0,
        command=cmd("all", "unlock"),
    )
    assert summary(d) == (
        L,
        L,
        "FAULT",
        "SENSOR_FAULT",
        "W_SENSOR_FAULT",
        ("DRIVER_UNLOCK_REJECTED",),
    )


def test_sensor_fault_with_risk_keeps_previous_release(h):
    d = h.send(0.1, sensor_fault=True, rear_left_approach_risk=True)  # 6.3 #8
    assert summary(d) == (R, R, "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT", ())


# ---------------------------------------------------------------- 입력 이상·지연 (SWR-013, 022)


@pytest.mark.parametrize(("age", "state"), [(0.2, "NORMAL"), (0.201, "DEGRADED")])
def test_snapshot_age_boundary(h, age, state):
    d = h.send(10.0 + age, ts=10.0)
    assert d.state.value == state


def test_stale_snapshot_holds_outputs(locked):
    h = locked()
    d = h.send(1.0, ts=0.5, command=cmd("all", "unlock"))
    assert summary(d) == (L, L, "DEGRADED", "DEGRADED", "INPUT_STALE", ("DRIVER_UNLOCK_REJECTED",))
    assert d.input_validity.freshness is m.Validity.STALE


def test_future_timestamp_is_stale(h):
    assert h.send(1.0, ts=1.001).input_validity.freshness is m.Validity.STALE


def test_missing_timestamp_is_stale(h):
    assert h.send(1.0, ts=None).reason_code is m.ReasonCode.INPUT_STALE


def test_time_regression_is_stale(h):
    h.send(5.0)
    d = h.send(4.0, ts=4.0)
    assert d.input_validity.freshness is m.Validity.STALE


@pytest.mark.parametrize("key", ["crash_status", "rear_left_approach_risk", "ignition_on"])
def test_invalid_safety_group_is_degraded_input_invalid(locked, key):
    h = locked()
    d = h.send(0.1, **{key: DROP})
    assert summary(d) == (L, L, "DEGRADED", "DEGRADED", "INPUT_INVALID", ())


def test_invalid_and_stale_together_report_input_invalid(h):
    assert h.send(1.0, ts=0.5, crash_status=DROP).reason_code is m.ReasonCode.INPUT_INVALID


def test_risk_still_locks_on_stale_snapshot(h):
    d = h.send(1.0, ts=0.5, rear_left_approach_risk=True)  # 6.3 #9
    assert summary(d) == (L, R, "DEGRADED", "APPROACH_RISK", "APPROACH_RISK", ())


def test_non_safety_group_invalid_is_not_degraded(h):
    d = h.send(0.1, fire_detected=DROP, vehicle_speed_kph=3.0)  # 6.3 #10
    assert summary(d) == (L, L, "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ())


def test_recovery_after_valid_fresh_snapshot(locked):
    h = locked()
    h.send(1.0, ts=0.5)
    d = h.send(1.1, command=cmd("left", "unlock"))
    assert summary(d) == (R, L, "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK", ())


def test_tick_detects_input_interruption(locked):
    h = locked()
    h.send(1.0)
    assert h.tick(1.2).state is m.State.NORMAL
    d = h.tick(1.25)
    assert summary(d) == (L, L, "DEGRADED", "DEGRADED", "INPUT_STALE", ())
    assert d.timestamp_s == 1.25


def test_tick_does_not_reapply_command_or_repeat_command_notices(h):
    h.send(1.0, command={"side": "x"})
    d = h.tick(1.05)
    assert summary(d) == (R, R, "NORMAL", "NONE", "NO_CHANGE", ())


def test_tick_repeats_crash_pending_notice(h):
    h.send(1.0, crash_status="PENDING")
    assert summary(h.tick(1.05))[5] == ("CRASH_PENDING",)


def test_notices_are_ordered(h):
    d = h.send(1.0, crash_status="PENDING", command={"bad": 1})
    assert summary(d)[5] == ("CRASH_PENDING", "COMMAND_REJECTED")


# ---- 시동 OFF, 강제 해제, ISOFIX (SWR-017, 018, 020)


def test_ignition_off_releases_even_with_isofix(locked):
    h = locked()
    d = h.send(0.1, ignition_on=False, isofix_left=True)  # 6.3 #11
    assert summary(d) == (R, R, "OFF", "IGNITION_OFF", "IGNITION_OFF", ())


def test_ignition_off_while_risk_keeps_risk_side_locked(h):
    d = h.send(0.1, ignition_on=False, rear_right_approach_risk=True)
    assert summary(d) == (R, L, "OFF", "APPROACH_RISK", "APPROACH_RISK", ())


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("fire_detected", "FIRE"),
        ("overtemperature_detected", "OVERTEMP"),
        ("adult_present", "ADULT_PRESENT"),
    ],
)
def test_each_forced_release_input_alone_releases_both(locked, key, code):
    h = locked()
    d = h.send(0.1, vehicle_speed_kph=50.0, **{key: True})
    assert summary(d) == (R, R, "NORMAL", "FORCED_RELEASE", code, ())


def test_forced_release_code_order_when_several_true(h):
    d = h.send(0.1, overtemperature_detected=True, adult_present=True)
    assert d.reason_code is m.ReasonCode.OVERTEMP


def test_forced_release_overrides_isofix(h):
    d = h.send(0.1, fire_detected=True, isofix_right=True)  # 6.3 #12
    assert summary(d) == (R, R, "NORMAL", "FORCED_RELEASE", "FIRE", ())


def test_risk_side_stays_locked_during_forced_release(h):
    d = h.send(0.1, fire_detected=True, rear_left_approach_risk=True)
    assert summary(d) == (L, R, "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ())


def test_isofix_locks_one_side_and_does_not_auto_release(h):
    d = h.send(0.1, isofix_left=True)
    assert summary(d) == (L, R, "NORMAL", "ISOFIX", "ISOFIX", ())
    assert summary(h.send(0.2)) == (L, R, "NORMAL", "NONE", "NO_CHANGE", ())


# ---------------------------------------------------------------- 상태 계산·예외 안전 (DEF-10)


def test_state_priority_emergency_over_fault_over_degraded():
    v_bad = m.InputValidity(*([m.Validity.VALID] * 7), m.Validity.STALE)
    snap = ctl_mod.validate({"sensor_fault": True, "ignition_on": True})
    ctx = m.EvalContext(snap, 1.0, False, v_bad, False)
    state = m.initial_state()
    from child_lock.core.arbitration import arbitrate

    latched = m.CoreState(state.outputs, True, state.doors, None, None)
    assert arbitrate(ctx, latched)[0].state is m.State.EMERGENCY


def test_controller_state_unchanged_when_arbitration_raises(h, monkeypatch):
    h.send(0.1, command=cmd("left", "lock"))
    before = h.ctl.last_decision

    def boom(*_args):
        raise RuntimeError("판정 오류")

    monkeypatch.setattr(ctl_mod, "arbitrate", boom)
    with pytest.raises(RuntimeError):
        h.send(0.2, command=cmd("left", "unlock"))
    monkeypatch.undo()
    assert h.ctl.last_decision == before
    d = h.send(0.3, command=cmd("left", "unlock"))
    assert d.lock_left is m.LockOutput.RELEASE


def test_ordered_notices_drops_command_notices_on_tick_as_second_defense():
    from child_lock.core.arbitration import ordered_notices

    notices = frozenset(
        {m.Notice.UNLOCK_SUPPRESSED, m.Notice.COMMAND_REJECTED, m.Notice.CRASH_PENDING}
    )
    assert ordered_notices(notices, is_tick=True) == (m.Notice.CRASH_PENDING,)
    assert ordered_notices(notices, is_tick=False) == (
        m.Notice.CRASH_PENDING,
        m.Notice.COMMAND_REJECTED,
        m.Notice.UNLOCK_SUPPRESSED,
    )
