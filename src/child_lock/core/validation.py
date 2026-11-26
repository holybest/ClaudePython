"""!
@brief SWU-02 입력 검증 (ASIL B).

원시 입력을 입력 그룹별로 검증해 VehicleSnapshot을 만든다. 시각과 무관한 형식·범위·enum만
검사하며, freshness의 시각 기준 판단은 컨트롤러(SWU-05)가 한다. 예외를 던지지 않는다. (SWDD 3장)
"""

import math
from collections.abc import Mapping
from enum import StrEnum

from child_lock.core.model import (
    SPEED_MAX_KPH,
    SPEED_MIN_KPH,
    Action,
    CommandSide,
    CommandSource,
    CrashStatus,
    DriverCommand,
    ForcedRelease,
    Gear,
    InputValidity,
    SidePair,
    Validity,
    VehicleSnapshot,
)

## 운전자 명령 객체의 필수 키 (OEM-IF-004)
_COMMAND_KEYS = ("side", "action", "source")


def _as_float(value: object) -> float | None:
    """!
    @brief 유한한 숫자(bool 제외)를 float로 바꾼다.
    @param value 원시 값
    @return float 값, 숫자가 아니거나 유한하지 않으면 None
    """
    if type(value) is int:
        try:
            value = float(value)
        except OverflowError:
            return None
    if type(value) is float and math.isfinite(value):
        return value
    return None


def _enum_value[E: StrEnum](enum_cls: type[E], value: object) -> E | None:
    """!
    @brief 문자열을 열거형 멤버로 바꾼다.
    @param enum_cls 열거형 클래스
    @param value 원시 값
    @return 멤버, 등록되지 않은 값이면 None
    """
    if isinstance(value, str) and value in enum_cls._value2member_map_:
        return enum_cls(value)
    return None


def _bools(raw: Mapping[str, object], keys: tuple[str, ...]) -> tuple[bool, ...] | None:
    """!
    @brief 여러 키의 bool 값을 한꺼번에 읽는다.
    @param raw 원시 입력
    @param keys 읽을 키 목록
    @return bool 값 튜플, 하나라도 누락·bool 아님이면 None
    """
    values = [raw.get(k) for k in keys]
    if all(type(v) is bool for v in values):
        return tuple(bool(v) for v in values)
    return None


def _validate_motion(raw: Mapping[str, object]) -> tuple[float | None, Gear | None, Validity]:
    """!
    @brief 차속·기어 그룹을 검증한다 (OEM-IF-001).
    @param raw 원시 입력
    @return (차속, 기어, 유효성)
    """
    speed = _as_float(raw.get("vehicle_speed_kph"))
    gear = _enum_value(Gear, raw.get("gear"))
    if speed is None or gear is None or not SPEED_MIN_KPH <= speed <= SPEED_MAX_KPH:
        return None, None, Validity.INVALID
    return speed, gear, Validity.VALID


def _validate_timestamp(raw: Mapping[str, object]) -> float | None:
    """!
    @brief 스냅샷 시각을 검증한다(0 이상 유한 숫자).
    @param raw 원시 입력
    @return 시각(초), 무효면 None
    """
    ts = _as_float(raw.get("source_timestamp_s"))
    return ts if ts is not None and ts >= 0.0 else None


def _validate_crash(raw: Mapping[str, object]) -> tuple[CrashStatus | None, Validity]:
    """!
    @brief 충돌 상태를 검증한다 (OEM-IF-002).
    @param raw 원시 입력
    @return (충돌 상태, 유효성)
    """
    crash = _enum_value(CrashStatus, raw.get("crash_status"))
    return crash, Validity.VALID if crash is not None else Validity.INVALID


def _validate_side_pair(
    raw: Mapping[str, object], left_key: str, right_key: str
) -> tuple[SidePair[bool] | None, Validity]:
    """!
    @brief 좌·우 bool 쌍을 검증한다 (OEM-IF-003, IF-008).
    @param raw 원시 입력
    @param left_key 좌측 키
    @param right_key 우측 키
    @return (좌우 쌍, 유효성)
    """
    values = _bools(raw, (left_key, right_key))
    if values is None:
        return None, Validity.INVALID
    return SidePair(values[0], values[1]), Validity.VALID


def _validate_command(raw: Mapping[str, object]) -> tuple[DriverCommand | None, Validity]:
    """!
    @brief 운전자 명령을 검증한다 (OEM-IF-004, SWR-002). 명령이 없으면 유효이다.
    @param raw 원시 입력
    @return (명령, 유효성)
    """
    value = raw.get("command")
    if value is None:
        return None, Validity.VALID
    if not isinstance(value, Mapping):
        return None, Validity.INVALID
    side = _enum_value(CommandSide, value.get("side"))
    action = _enum_value(Action, value.get("action"))
    source = _enum_value(CommandSource, value.get("source"))
    if side is None or action is None or source is None:
        return None, Validity.INVALID
    return DriverCommand(side, action, source), Validity.VALID


def _validate_forced(raw: Mapping[str, object]) -> tuple[ForcedRelease | None, Validity]:
    """!
    @brief 화재·과온·성인 탑승 그룹을 검증한다 (OEM-IF-007).
    @param raw 원시 입력
    @return (강제 해제 입력, 유효성)
    """
    values = _bools(raw, ("fire_detected", "overtemperature_detected", "adult_present"))
    if values is None:
        return None, Validity.INVALID
    return ForcedRelease(*values), Validity.VALID


def _validate_ignition(raw: Mapping[str, object]) -> tuple[bool | None, bool | None, Validity]:
    """!
    @brief 시동·센서 고장 그룹을 검증한다 (OEM-IF-009).
    @param raw 원시 입력
    @return (시동, 센서 고장, 유효성)
    """
    values = _bools(raw, ("ignition_on", "sensor_fault"))
    if values is None:
        return None, None, Validity.INVALID
    return values[0], values[1], Validity.VALID


def validate(raw: object) -> VehicleSnapshot:
    """!
    @brief 원시 입력을 검증해 스냅샷을 만든다 (SWR-013). 정의되지 않은 키는 무시한다.
    @param raw 원시 입력(Mapping이 아니면 모든 그룹 누락으로 처리)
    @return 검증된 스냅샷
    """
    data: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}
    speed, gear, v_motion = _validate_motion(data)
    ts = _validate_timestamp(data)
    crash, v_crash = _validate_crash(data)
    risk, v_risk = _validate_side_pair(data, "rear_left_approach_risk", "rear_right_approach_risk")
    command, v_command = _validate_command(data)
    forced, v_forced = _validate_forced(data)
    isofix, v_isofix = _validate_side_pair(data, "isofix_left", "isofix_right")
    ignition, fault, v_ign = _validate_ignition(data)
    freshness = Validity.VALID if ts is not None else Validity.STALE
    validity = InputValidity(
        v_motion, v_crash, v_risk, v_command, v_forced, v_isofix, v_ign, freshness
    )
    return VehicleSnapshot(
        speed, gear, ts, crash, risk, command, forced, isofix, ignition, fault, validity
    )
