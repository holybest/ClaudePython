"""!
@brief SWU-01 도메인 모델 (ASIL B).

열거형, 상수, 불변 데이터 타입과 초기값을 정의한다. (SWDD 2장)
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class LockOutput(StrEnum):
    """!
    @brief 쪽별 차일드락 논리 출력 (OEM-IF-005).
    """

    LOCK = "LOCK"
    RELEASE = "RELEASE"


class Side(StrEnum):
    """!
    @brief 후석 쪽.
    """

    LEFT = "left"
    RIGHT = "right"


class CommandSide(StrEnum):
    """!
    @brief 운전자 명령의 대상 쪽 (OEM-IF-004).
    """

    LEFT = "left"
    RIGHT = "right"
    ALL = "all"


class Action(StrEnum):
    """!
    @brief 운전자 명령 동작.
    """

    LOCK = "lock"
    UNLOCK = "unlock"


class CommandSource(StrEnum):
    """!
    @brief 운전자 명령 경로.
    """

    PHYSICAL_BUTTON = "physical_button"
    AVN = "avn"
    VOICE = "voice"
    MOBILE_APP = "mobile_app"


class Gear(StrEnum):
    """!
    @brief 기어 (OEM-IF-001).
    """

    P = "P"
    N = "N"
    D = "D"
    R = "R"


class CrashStatus(StrEnum):
    """!
    @brief 충돌 상태 (OEM-IF-002).
    """

    NONE = "NONE"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


class State(StrEnum):
    """!
    @brief 시스템 상태 (SWRS DEF-10).
    """

    OFF = "OFF"
    NORMAL = "NORMAL"
    OVERRIDE = "OVERRIDE"
    EMERGENCY = "EMERGENCY"
    DEGRADED = "DEGRADED"
    FAULT = "FAULT"


class Validity(StrEnum):
    """!
    @brief 입력 키별 유효성.
    """

    VALID = "VALID"
    INVALID = "INVALID"
    STALE = "STALE"


class PriorityReason(StrEnum):
    """!
    @brief 출력을 결정한 최상위 규칙 (SWRS 4장).
    """

    CRASH = "CRASH"
    SENSOR_FAULT = "SENSOR_FAULT"
    APPROACH_RISK = "APPROACH_RISK"
    DEGRADED = "DEGRADED"
    IGNITION_OFF = "IGNITION_OFF"
    FORCED_RELEASE = "FORCED_RELEASE"
    ISOFIX = "ISOFIX"
    AUTO_LOCK = "AUTO_LOCK"
    DRIVER_COMMAND = "DRIVER_COMMAND"
    NONE = "NONE"


class ReasonCode(StrEnum):
    """!
    @brief 규칙의 세부 이유 코드 (SWRS 4장).
    """

    CRASH_CONFIRMED = "CRASH_CONFIRMED"
    W_SENSOR_FAULT = "W_SENSOR_FAULT"
    APPROACH_RISK = "APPROACH_RISK"
    APPROACH_OVERRIDE = "APPROACH_OVERRIDE"
    INPUT_INVALID = "INPUT_INVALID"
    INPUT_STALE = "INPUT_STALE"
    IGNITION_OFF = "IGNITION_OFF"
    FIRE = "FIRE"
    OVERTEMP = "OVERTEMP"
    ADULT_PRESENT = "ADULT_PRESENT"
    ISOFIX = "ISOFIX"
    AUTO_LOCK_SPEED = "AUTO_LOCK_SPEED"
    DRIVER_LOCK = "DRIVER_LOCK"
    DRIVER_UNLOCK = "DRIVER_UNLOCK"
    NO_CHANGE = "NO_CHANGE"


class Notice(StrEnum):
    """!
    @brief 출력을 결정하지 않는 부가 알림. 정의 순서가 출력 순서이다.
    """

    CRASH_PENDING = "CRASH_PENDING"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    DRIVER_UNLOCK_REJECTED = "DRIVER_UNLOCK_REJECTED"
    UNLOCK_SUPPRESSED = "UNLOCK_SUPPRESSED"


## reason_code → priority_reason N:1 매핑 (SWR-014)
REASON_PRIORITY: Mapping[ReasonCode, PriorityReason] = {
    ReasonCode.CRASH_CONFIRMED: PriorityReason.CRASH,
    ReasonCode.W_SENSOR_FAULT: PriorityReason.SENSOR_FAULT,
    ReasonCode.APPROACH_RISK: PriorityReason.APPROACH_RISK,
    ReasonCode.APPROACH_OVERRIDE: PriorityReason.APPROACH_RISK,
    ReasonCode.INPUT_INVALID: PriorityReason.DEGRADED,
    ReasonCode.INPUT_STALE: PriorityReason.DEGRADED,
    ReasonCode.IGNITION_OFF: PriorityReason.IGNITION_OFF,
    ReasonCode.FIRE: PriorityReason.FORCED_RELEASE,
    ReasonCode.OVERTEMP: PriorityReason.FORCED_RELEASE,
    ReasonCode.ADULT_PRESENT: PriorityReason.FORCED_RELEASE,
    ReasonCode.ISOFIX: PriorityReason.ISOFIX,
    ReasonCode.AUTO_LOCK_SPEED: PriorityReason.AUTO_LOCK,
    ReasonCode.DRIVER_LOCK: PriorityReason.DRIVER_COMMAND,
    ReasonCode.DRIVER_UNLOCK: PriorityReason.DRIVER_COMMAND,
    ReasonCode.NO_CHANGE: PriorityReason.NONE,
}

## 차속 유효 범위 하한·상한 (OEM-IF-001)
SPEED_MIN_KPH = 0.0
SPEED_MAX_KPH = 300.0
## 주행 자동 잠금 차속 (SWR-003, 004)
AUTO_LOCK_SPEED_KPH = 3.0
## 스냅샷 지연 한계 (SWR-013, 022)
STALE_LIMIT_MS = 200
## override 재입력 허용 시간 (SWR-006)
OVERRIDE_WINDOW_MS = 10000
## tick 평가에서 내지 않는 명령 관련 알림 (SWAD 3.2)
COMMAND_NOTICES = frozenset(
    {Notice.COMMAND_REJECTED, Notice.DRIVER_UNLOCK_REJECTED, Notice.UNLOCK_SUPPRESSED}
)


@dataclass(frozen=True, slots=True)
class SidePair[T]:
    """!
    @brief 좌·우 한 쌍의 값.
    """

    left: T
    right: T

    def get(self, side: Side) -> T:
        """!
        @brief 지정한 쪽의 값을 구한다.
        @param side 쪽
        @return 해당 쪽 값
        """
        return self.left if side is Side.LEFT else self.right

    def replace(self, side: Side, value: T) -> "SidePair[T]":
        """!
        @brief 지정한 쪽 값만 바꾼 새 쌍을 만든다.
        @param side 쪽
        @param value 새 값
        @return 새 SidePair
        """
        if side is Side.LEFT:
            return SidePair(value, self.right)
        return SidePair(self.left, value)


@dataclass(frozen=True, slots=True)
class DriverCommand:
    """!
    @brief 검증된 운전자 명령 (OEM-IF-004).
    """

    side: CommandSide
    action: Action
    source: CommandSource

    def covers(self, side: Side) -> bool:
        """!
        @brief 명령이 지정한 쪽을 대상으로 하는지 판단한다.
        @param side 쪽
        @return 대상이면 True
        """
        return self.side is CommandSide.ALL or self.side.value == side.value


@dataclass(frozen=True, slots=True)
class ForcedRelease:
    """!
    @brief 강제 해제 입력 (OEM-IF-007).
    """

    fire: bool
    overtemp: bool
    adult: bool


@dataclass(frozen=True, slots=True)
class InputValidity:
    """!
    @brief 입력 키별 유효성 (SWAD 2.3).
    """

    if_001: Validity
    if_002: Validity
    if_003: Validity
    if_004: Validity
    if_007: Validity
    if_008: Validity
    if_009: Validity
    freshness: Validity

    def safety_abnormal(self) -> bool:
        """!
        @brief 안전 입력 이상 여부를 판단한다 (SWRS DEF-08).
        @return 지연이거나 IF-002/003/009 중 유효하지 않은 것이 있으면 True
        """
        safety = (self.if_002, self.if_003, self.if_009)
        return self.freshness is not Validity.VALID or any(v is not Validity.VALID for v in safety)

    def as_dict(self) -> dict[str, str]:
        """!
        @brief JSON 표기용 사전으로 바꾼다.
        @return 인터페이스 키 → 유효성 문자열
        """
        return {
            "IF-001": self.if_001.value,
            "IF-002": self.if_002.value,
            "IF-003": self.if_003.value,
            "IF-004": self.if_004.value,
            "IF-007": self.if_007.value,
            "IF-008": self.if_008.value,
            "IF-009": self.if_009.value,
            "FRESHNESS": self.freshness.value,
        }


@dataclass(frozen=True, slots=True)
class VehicleSnapshot:
    """!
    @brief 검증된 차량 입력 스냅샷. 무효 키의 필드는 None이다.
    """

    speed_kph: float | None
    gear: Gear | None
    source_timestamp_s: float | None
    crash_status: CrashStatus | None
    approach_risk: SidePair[bool] | None
    command: DriverCommand | None
    forced_release: ForcedRelease | None
    isofix: SidePair[bool] | None
    ignition_on: bool | None
    sensor_fault: bool | None
    validity: InputValidity


@dataclass(frozen=True, slots=True)
class EvalContext:
    """!
    @brief 우선순위 판정 입력 (SWDD 2.3).
    """

    snapshot: VehicleSnapshot
    now_s: float
    is_tick: bool
    validity: InputValidity
    command_is_new: bool


@dataclass(frozen=True, slots=True)
class DoorGuard:
    """!
    @brief 쪽별 접근위험 가드 상태 (SWAD 3.4).
    """

    suppressed_at_s: float | None
    override_active: bool


## 가드 초기 상태 (IDLE)
IDLE_GUARD = DoorGuard(None, False)


@dataclass(frozen=True, slots=True)
class CoreState:
    """!
    @brief 컨트롤러가 보관하는 코어 상태.
    """

    outputs: SidePair[LockOutput]
    crash_latched: bool
    doors: SidePair[DoorGuard]
    last_snapshot: VehicleSnapshot | None
    last_now_s: float | None


@dataclass(frozen=True, slots=True)
class Decision:
    """!
    @brief 평가 1회의 판정 결과 (SWR-014).
    """

    lock_left: LockOutput
    lock_right: LockOutput
    state: State
    input_validity: InputValidity
    priority_reason: PriorityReason
    reason_code: ReasonCode
    notices: tuple[Notice, ...]
    timestamp_s: float


def diff_ms(a_s: float, b_s: float) -> int:
    """!
    @brief 두 시각의 차이(a − b)를 ms 정수로 0.5 올림한다 (SWRS DEF-04).

    부동소수 오차(예: 0.3005 − 0.1 = 0.20049999…)를 없애려고 소수 6자리로 정리한 뒤 올림한다.
    @param a_s 시각 a(초)
    @param b_s 시각 b(초)
    @return 차이(ms)
    """
    return math.floor(round((a_s - b_s) * 1000, 6) + 0.5)


def all_valid() -> InputValidity:
    """!
    @brief 모든 키가 VALID인 유효성을 만든다.
    @return InputValidity
    """
    return _uniform(Validity.VALID)


def all_invalid() -> InputValidity:
    """!
    @brief 모든 키가 INVALID인 유효성을 만든다 (첫 스냅샷 전).
    @return InputValidity
    """
    return _uniform(Validity.INVALID)


def _uniform(value: Validity) -> InputValidity:
    """!
    @brief 모든 키가 같은 값인 유효성을 만든다.
    @param value 유효성 값
    @return InputValidity
    """
    return InputValidity(value, value, value, value, value, value, value, value)


def initial_state() -> CoreState:
    """!
    @brief 기동 시 코어 상태를 만든다 (SWRS DEF-06).
    @return 출력 좌·우 RELEASE, 래치·가드·이력 없음
    """
    release = SidePair(LockOutput.RELEASE, LockOutput.RELEASE)
    return CoreState(release, False, SidePair(IDLE_GUARD, IDLE_GUARD), None, None)


def initial_decision(now_s: float) -> Decision:
    """!
    @brief 첫 스냅샷 전 판정 결과를 만든다 (SWRS DEF-06).
    @param now_s 평가 시각(초)
    @return RELEASE / OFF / NONE / NO_CHANGE 판정
    """
    return Decision(
        LockOutput.RELEASE,
        LockOutput.RELEASE,
        State.OFF,
        all_invalid(),
        PriorityReason.NONE,
        ReasonCode.NO_CHANGE,
        (),
        now_s,
    )
