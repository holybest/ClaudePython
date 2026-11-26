"""!
@brief SWU-02 입력 검증(core/validation.py) 단위 시험 (SWR-002, SWR-013, SWDD 3장).
"""

import math

import pytest

from child_lock.core import model as m
from child_lock.core.validation import validate

V, INV, ST = m.Validity.VALID, m.Validity.INVALID, m.Validity.STALE


def valid_raw(**changes: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "vehicle_speed_kph": 0.0,
        "gear": "P",
        "source_timestamp_s": 1.0,
        "crash_status": "NONE",
        "rear_left_approach_risk": False,
        "rear_right_approach_risk": False,
        "fire_detected": False,
        "overtemperature_detected": False,
        "adult_present": False,
        "isofix_left": False,
        "isofix_right": False,
        "ignition_on": True,
        "sensor_fault": False,
    }
    raw.update(changes)
    return raw


def without(key: str) -> dict[str, object]:
    raw = valid_raw()
    del raw[key]
    return raw


def test_fully_valid_snapshot_has_all_values_and_valid_keys():
    snap = validate(valid_raw())
    assert snap.validity == m.all_valid()
    assert (snap.speed_kph, snap.gear, snap.source_timestamp_s) == (0.0, m.Gear.P, 1.0)
    assert snap.crash_status is m.CrashStatus.NONE
    assert snap.approach_risk == m.SidePair(False, False)
    assert snap.command is None
    assert snap.forced_release == m.ForcedRelease(False, False, False)
    assert snap.isofix == m.SidePair(False, False)
    assert (snap.ignition_on, snap.sensor_fault) == (True, False)


@pytest.mark.parametrize(
    ("speed", "valid"),
    [
        (-0.1, False),
        (0.0, True),
        (0, True),
        (120.5, True),
        (300.0, True),
        (300, True),
        (300.1, False),
        (True, False),
        ("10", False),
        (None, False),
        (math.nan, False),
        (math.inf, False),
        (10**400, False),  # 큰 정수: 예외 없이 무효
    ],
)
def test_speed_boundaries_and_types(speed, valid):
    snap = validate(valid_raw(vehicle_speed_kph=speed))
    assert snap.validity.if_001 is (V if valid else INV)
    assert (snap.speed_kph is not None) is valid
    assert snap.validity.safety_abnormal() is False  # IF-001 무효는 안전 입력 이상 아님


def test_speed_value_is_converted_to_float():
    snap = validate(valid_raw(vehicle_speed_kph=3))
    assert isinstance(snap.speed_kph, float)


@pytest.mark.parametrize("gear", ["X", "p", 1, None])
def test_invalid_gear_invalidates_if_001_group(gear):
    snap = validate(valid_raw(gear=gear))
    assert snap.validity.if_001 is INV
    assert (snap.speed_kph, snap.gear) == (None, None)


@pytest.mark.parametrize(("key", "attr"), [("vehicle_speed_kph", "if_001"), ("gear", "if_001")])
def test_missing_motion_key_invalidates_group(key, attr):
    assert getattr(validate(without(key)).validity, attr) is INV


@pytest.mark.parametrize(
    ("ts", "fresh"),
    [(0.0, True), (5, True), (-0.001, False), (True, False), ("1", False), (math.nan, False)],
)
def test_timestamp_validity_sets_freshness(ts, fresh):
    snap = validate(valid_raw(source_timestamp_s=ts))
    assert snap.validity.freshness is (V if fresh else ST)
    assert (snap.source_timestamp_s is not None) is fresh
    assert snap.validity.if_001 is V  # 시각 무효가 차속·기어 그룹에 번지지 않음


def test_missing_timestamp_is_stale():
    assert validate(without("source_timestamp_s")).validity.freshness is ST


@pytest.mark.parametrize(
    ("value", "valid"),
    [("NONE", True), ("PENDING", True), ("CONFIRMED", True), ("confirmed", False), (2, False)],
)
def test_crash_status_enum(value, valid):
    snap = validate(valid_raw(crash_status=value))
    assert snap.validity.if_002 is (V if valid else INV)
    if valid:
        assert snap.crash_status is m.CrashStatus(value)


@pytest.mark.parametrize(
    ("key", "attr", "field"),
    [
        ("rear_left_approach_risk", "if_003", "approach_risk"),
        ("rear_right_approach_risk", "if_003", "approach_risk"),
        ("isofix_left", "if_008", "isofix"),
        ("isofix_right", "if_008", "isofix"),
        ("fire_detected", "if_007", "forced_release"),
        ("overtemperature_detected", "if_007", "forced_release"),
        ("adult_present", "if_007", "forced_release"),
        ("ignition_on", "if_009", "ignition_on"),
        ("sensor_fault", "if_009", "sensor_fault"),
    ],
)
@pytest.mark.parametrize("bad", [1, 0, "true", None, "missing"])
def test_boolean_groups_reject_non_bool_and_missing(key, attr, field, bad):
    raw = without(key) if bad == "missing" else valid_raw(**{key: bad})
    snap = validate(raw)
    assert getattr(snap.validity, attr) is INV
    assert getattr(snap, field) is None


def test_boolean_pairs_keep_side_order():
    snap = validate(valid_raw(rear_left_approach_risk=True, isofix_right=True, adult_present=True))
    assert snap.approach_risk == m.SidePair(True, False)
    assert snap.isofix == m.SidePair(False, True)
    assert snap.forced_release == m.ForcedRelease(False, False, True)


def test_ignition_group_values():
    snap = validate(valid_raw(ignition_on=False, sensor_fault=True))
    assert (snap.ignition_on, snap.sensor_fault) == (False, True)


@pytest.mark.parametrize("command", [None, "absent"])
def test_absent_command_is_valid_no_command(command):
    raw = valid_raw() if command == "absent" else valid_raw(command=None)
    snap = validate(raw)
    assert (snap.command, snap.validity.if_004) == (None, V)


@pytest.mark.parametrize("side", ["left", "right", "all"])
@pytest.mark.parametrize("action", ["lock", "unlock"])
@pytest.mark.parametrize("source", ["physical_button", "avn", "voice", "mobile_app"])
def test_valid_command_combinations(side, action, source):
    snap = validate(valid_raw(command={"side": side, "action": action, "source": source}))
    assert snap.validity.if_004 is V
    assert snap.command == m.DriverCommand(
        m.CommandSide(side), m.Action(action), m.CommandSource(source)
    )


@pytest.mark.parametrize(
    "command",
    [
        {"action": "lock", "source": "avn"},
        {"side": "left", "source": "avn"},
        {"side": "left", "action": "lock"},
        {"side": "center", "action": "lock", "source": "avn"},
        {"side": "left", "action": "open", "source": "avn"},
        {"side": "left", "action": "lock", "source": "phone"},
        {"side": 1, "action": "lock", "source": "avn"},
        "left lock",
        ["left", "lock", "avn"],
    ],
)
def test_invalid_command_is_rejected_without_affecting_other_groups(command):
    snap = validate(valid_raw(command=command))
    assert (snap.command, snap.validity.if_004) == (None, INV)
    assert snap.validity.safety_abnormal() is False


def test_unknown_keys_are_ignored_by_core():
    snap = validate(valid_raw(video_frame="xxx"))
    assert snap.validity == m.all_valid()


@pytest.mark.parametrize("raw", [None, "text", 3, ["a"]])
def test_non_mapping_input_invalidates_everything_without_exception(raw):
    v = validate(raw).validity
    assert v.as_dict() == {
        "IF-001": "INVALID",
        "IF-002": "INVALID",
        "IF-003": "INVALID",
        "IF-004": "VALID",  # 명령 없음은 유효
        "IF-007": "INVALID",
        "IF-008": "INVALID",
        "IF-009": "INVALID",
        "FRESHNESS": "STALE",
    }
