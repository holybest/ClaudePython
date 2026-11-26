"""!
@brief SWU-01 도메인 모델(core/model.py) 단위 시험.
"""

import dataclasses

import pytest

from child_lock.core import model as m


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (0.2004, 0.0, 200),  # 0.4 ms → 내림
        (0.2005, 0.0, 201),  # 0.5 ms → 올림 (DEF-04)
        (0.3005, 0.1, 201),  # 부동소수 오차(0.20049999…)에도 0.5 올림
        (0.2008, 0.0004, 200),  # 차이를 한 번만 반올림
        (0.0, 0.001, -1),  # 음수 차이
        (10.0, 0.0, 10000),
    ],
)
def test_diff_ms_rounds_the_difference_half_up(a, b, expected):
    assert m.diff_ms(a, b) == expected


def test_side_pair_get_and_replace_return_side_values():
    pair = m.SidePair(left=1, right=2)
    assert (pair.get(m.Side.LEFT), pair.get(m.Side.RIGHT)) == (1, 2)
    assert pair.replace(m.Side.LEFT, 9) == m.SidePair(9, 2)
    assert pair.replace(m.Side.RIGHT, 9) == m.SidePair(1, 9)
    assert pair == m.SidePair(1, 2)  # 원본 불변


@pytest.mark.parametrize(
    ("cmd_side", "left", "right"),
    [
        (m.CommandSide.LEFT, True, False),
        (m.CommandSide.RIGHT, False, True),
        (m.CommandSide.ALL, True, True),
    ],
)
def test_driver_command_covers_selected_sides(cmd_side, left, right):
    cmd = m.DriverCommand(cmd_side, m.Action.UNLOCK, m.CommandSource.AVN)
    assert (cmd.covers(m.Side.LEFT), cmd.covers(m.Side.RIGHT)) == (left, right)


def _validity(**changes: m.Validity) -> m.InputValidity:
    return dataclasses.replace(m.all_valid(), **changes)


@pytest.mark.parametrize(
    ("changes", "abnormal"),
    [
        ({}, False),
        ({"if_001": m.Validity.INVALID}, False),
        ({"if_004": m.Validity.INVALID}, False),
        ({"if_007": m.Validity.INVALID}, False),
        ({"if_008": m.Validity.INVALID}, False),
        ({"if_002": m.Validity.INVALID}, True),
        ({"if_003": m.Validity.INVALID}, True),
        ({"if_009": m.Validity.INVALID}, True),
        ({"freshness": m.Validity.STALE}, True),
    ],
)
def test_safety_abnormal_only_for_safety_groups_and_freshness(changes, abnormal):
    assert _validity(**changes).safety_abnormal() is abnormal


def test_input_validity_as_dict_uses_interface_keys():
    v = _validity(if_003=m.Validity.INVALID, freshness=m.Validity.STALE)
    assert v.as_dict() == {
        "IF-001": "VALID",
        "IF-002": "VALID",
        "IF-003": "INVALID",
        "IF-004": "VALID",
        "IF-007": "VALID",
        "IF-008": "VALID",
        "IF-009": "VALID",
        "FRESHNESS": "STALE",
    }


def test_all_invalid_marks_every_key_invalid():
    assert set(m.all_invalid().as_dict().values()) == {"INVALID"}


def test_initial_state_releases_both_sides_without_latch_or_history():
    s = m.initial_state()
    assert s.outputs == m.SidePair(m.LockOutput.RELEASE, m.LockOutput.RELEASE)
    assert s.crash_latched is False
    assert s.doors == m.SidePair(m.IDLE_GUARD, m.IDLE_GUARD)
    assert (s.last_snapshot, s.last_now_s) == (None, None)


def test_initial_decision_is_off_release_no_change():
    d = m.initial_decision(1.5)
    assert (d.lock_left, d.lock_right, d.state) == (
        m.LockOutput.RELEASE,
        m.LockOutput.RELEASE,
        m.State.OFF,
    )
    assert (d.priority_reason, d.reason_code, d.notices) == (
        m.PriorityReason.NONE,
        m.ReasonCode.NO_CHANGE,
        (),
    )
    assert d.input_validity == m.all_invalid()
    assert d.timestamp_s == 1.5


def test_reason_priority_maps_every_reason_code_as_in_swrs_table():
    rp, rc = m.PriorityReason, m.ReasonCode
    assert m.REASON_PRIORITY == {
        rc.CRASH_CONFIRMED: rp.CRASH,
        rc.W_SENSOR_FAULT: rp.SENSOR_FAULT,
        rc.APPROACH_RISK: rp.APPROACH_RISK,
        rc.APPROACH_OVERRIDE: rp.APPROACH_RISK,
        rc.INPUT_INVALID: rp.DEGRADED,
        rc.INPUT_STALE: rp.DEGRADED,
        rc.IGNITION_OFF: rp.IGNITION_OFF,
        rc.FIRE: rp.FORCED_RELEASE,
        rc.OVERTEMP: rp.FORCED_RELEASE,
        rc.ADULT_PRESENT: rp.FORCED_RELEASE,
        rc.ISOFIX: rp.ISOFIX,
        rc.AUTO_LOCK_SPEED: rp.AUTO_LOCK,
        rc.DRIVER_LOCK: rp.DRIVER_COMMAND,
        rc.DRIVER_UNLOCK: rp.DRIVER_COMMAND,
        rc.NO_CHANGE: rp.NONE,
    }


def test_enum_values_match_json_notation():
    assert m.LockOutput.LOCK.value == "LOCK"
    assert m.CommandSource.MOBILE_APP.value == "mobile_app"
    assert m.CommandSide.ALL.value == "all"
    assert m.Gear.R.value == "R"
    assert [n.value for n in m.Notice] == [
        "CRASH_PENDING",
        "COMMAND_REJECTED",
        "DRIVER_UNLOCK_REJECTED",
        "UNLOCK_SUPPRESSED",
    ]


def test_data_types_are_immutable():
    state = m.initial_state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.crash_latched = True
