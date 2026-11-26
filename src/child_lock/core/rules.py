"""!
@brief SWU-04 우선순위 규칙 1~9 (ASIL B).

각 규칙은 판정 입력과 직전 상태를 보고 아직 결정되지 않은 쪽만 결정한다. RULES 튜플의 순서가
SWR-019 우선순위이다. 순환 import를 피하려고 중간 결과 Resolution도 이 모듈에 둔다. (SWDD 5.1, 6장)
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from child_lock.core.model import (
    AUTO_LOCK_SPEED_KPH,
    IDLE_GUARD,
    OVERRIDE_WINDOW_MS,
    Action,
    CoreState,
    CrashStatus,
    DoorGuard,
    EvalContext,
    LockOutput,
    Notice,
    PriorityReason,
    ReasonCode,
    Side,
    SidePair,
    Validity,
    diff_ms,
)

## 이유 쌍 (priority_reason, reason_code)
Reason = tuple[PriorityReason, ReasonCode]
## 평가 순서대로의 쪽
SIDES = (Side.LEFT, Side.RIGHT)


@dataclass(frozen=True, slots=True)
class Resolution:
    """!
    @brief 규칙 적용 중의 중간 결과 (SWDD 5.1).
    """

    outputs: SidePair[LockOutput | None]
    deciders: SidePair[PriorityReason | None]
    reason: Reason | None
    notices: frozenset[Notice]
    doors: SidePair[DoorGuard]
    crash_latched: bool

    @classmethod
    def start(cls, doors: SidePair[DoorGuard], crash_latched: bool) -> "Resolution":
        """!
        @brief 아무 쪽도 결정되지 않은 중간 결과를 만든다.
        @param doors 갱신된 문 가드
        @param crash_latched 직전 충돌 래치
        @return 새 Resolution
        """
        return cls(
            SidePair(None, None), SidePair(None, None), None, frozenset(), doors, crash_latched
        )

    def is_open(self, side: Side) -> bool:
        """!
        @brief 아직 결정되지 않은 쪽인지 판단한다.
        @param side 쪽
        @return 미결정이면 True
        """
        return self.outputs.get(side) is None

    def decide(self, side: Side, output: LockOutput, reason: Reason) -> "Resolution":
        """!
        @brief 미결정인 쪽의 출력을 결정한다. 처음 결정하는 규칙의 이유를 기록한다.
        @param side 쪽
        @param output 출력
        @param reason 이유 쌍
        @return 새 Resolution (이미 결정된 쪽이면 그대로)
        """
        if not self.is_open(side):
            return self
        return replace(
            self,
            outputs=self.outputs.replace(side, output),
            deciders=self.deciders.replace(side, reason[0]),
            reason=self.reason or reason,
        )

    def add_notice(self, notice: Notice) -> "Resolution":
        """!
        @brief 알림을 추가한다.
        @param notice 알림
        @return 새 Resolution
        """
        return replace(self, notices=self.notices | {notice})

    def with_door(self, side: Side, guard: DoorGuard) -> "Resolution":
        """!
        @brief 한 쪽 문 가드를 바꾼다.
        @param side 쪽
        @param guard 새 가드
        @return 새 Resolution
        """
        return replace(self, doors=self.doors.replace(side, guard))

    def with_reason(self, reason: Reason) -> "Resolution":
        """!
        @brief 이유를 덮어쓴다 (override 표시용, SWDD 6.1).
        @param reason 이유 쌍
        @return 새 Resolution
        """
        return replace(self, reason=reason)


## 규칙 함수 형식
Rule = Callable[[EvalContext, CoreState, Resolution], Resolution]


def _decide_all(res: Resolution, outputs: SidePair[LockOutput], reason: Reason) -> Resolution:
    """!
    @brief 미결정인 양쪽을 지정한 출력으로 결정한다.
    @param res 중간 결과
    @param outputs 쪽별 출력
    @param reason 이유 쌍
    @return 새 Resolution
    """
    for side in SIDES:
        res = res.decide(side, outputs.get(side), reason)
    return res


def _both(output: LockOutput) -> SidePair[LockOutput]:
    """!
    @brief 양쪽이 같은 출력인 쌍을 만든다.
    @param output 출력
    @return SidePair
    """
    return SidePair(output, output)


def command_requested(ctx: EvalContext, side: Side, action: Action) -> bool:
    """!
    @brief 지정한 쪽에 대한 새 운전자 명령(lock/unlock)이 있는지 판단한다.
    @param ctx 판정 입력
    @param side 쪽
    @param action 명령 동작
    @return 새 입력이고 동작·쪽이 맞으면 True
    """
    command = ctx.snapshot.command
    return (
        ctx.command_is_new
        and command is not None
        and command.action is action
        and command.covers(side)
    )


def risk_on(ctx: EvalContext, side: Side) -> bool | None:
    """!
    @brief 유효한 접근위험 값을 구한다.
    @param ctx 판정 입력
    @param side 쪽
    @return 위험 여부, IF-003이 무효면 None
    """
    risk = ctx.snapshot.approach_risk
    if ctx.validity.if_003 is not Validity.VALID or risk is None:
        return None
    return risk.get(side)


def rule_crash(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 1: 충돌 CONFIRMED 또는 래치 → 좌·우 RELEASE (SWR-007, 008).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    crash = ctx.snapshot.crash_status if ctx.validity.if_002 is Validity.VALID else None
    if crash is CrashStatus.PENDING:
        res = res.add_notice(Notice.CRASH_PENDING)
    if crash is not CrashStatus.CONFIRMED and not res.crash_latched:
        return res
    res = replace(res, crash_latched=True, doors=SidePair(IDLE_GUARD, IDLE_GUARD))
    reason = (PriorityReason.CRASH, ReasonCode.CRASH_CONFIRMED)
    return _decide_all(res, _both(LockOutput.RELEASE), reason)


def rule_sensor_fault(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 2: 센서 고장 → 직전 확정 출력 유지 (SWR-021).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    if ctx.validity.if_009 is not Validity.VALID or ctx.snapshot.sensor_fault is not True:
        return res
    reason = (PriorityReason.SENSOR_FAULT, ReasonCode.W_SENSOR_FAULT)
    return _decide_all(res, state.outputs, reason)


def _window_ok(request_s: float, suppressed_at_s: float) -> bool:
    """!
    @brief override 재입력 창(0 ≤ 경과 ≤ 10,000 ms) 안인지 판단한다 (SWR-006).
    @param request_s 재요청 시각
    @param suppressed_at_s 억제 시각 t0
    @return 창 안이면 True
    """
    return 0 <= diff_ms(request_s, suppressed_at_s) <= OVERRIDE_WINDOW_MS


def _unlock_on_risk(ctx: EvalContext, res: Resolution, side: Side) -> Resolution:
    """!
    @brief 위험 중 해제 요청을 억제하거나 override로 처리한다 (SWDD 6.1).
    @param ctx 판정 입력
    @param res 중간 결과
    @param side 쪽
    @return 새 Resolution
    """
    guard = res.doors.get(side)
    fresh = ctx.validity.freshness is Validity.VALID
    request_s = ctx.snapshot.source_timestamp_s if fresh else None
    if (
        request_s is not None
        and guard.suppressed_at_s is not None
        and _window_ok(request_s, guard.suppressed_at_s)
        and not ctx.validity.safety_abnormal()
    ):
        res = res.with_door(side, DoorGuard(guard.suppressed_at_s, True))
        return res.decide(side, LockOutput.RELEASE, _OVERRIDE)
    res = res.with_door(side, DoorGuard(request_s, False))
    return res.add_notice(Notice.UNLOCK_SUPPRESSED).decide(side, LockOutput.LOCK, _RISK)


## 접근위험 규칙의 이유 쌍
_RISK = (PriorityReason.APPROACH_RISK, ReasonCode.APPROACH_RISK)
_OVERRIDE = (PriorityReason.APPROACH_RISK, ReasonCode.APPROACH_OVERRIDE)


def _risk_side(ctx: EvalContext, res: Resolution, side: Side) -> Resolution:
    """!
    @brief 한 쪽의 접근위험 규칙을 적용한다 (SWR-005, 006).
    @param ctx 판정 입력
    @param res 중간 결과
    @param side 쪽
    @return 새 Resolution
    """
    if not res.is_open(side) or risk_on(ctx, side) is not True:
        return res
    if res.doors.get(side).override_active:
        return res.decide(side, LockOutput.RELEASE, _OVERRIDE)
    if command_requested(ctx, side, Action.UNLOCK):
        return _unlock_on_risk(ctx, res, side)
    return res.decide(side, LockOutput.LOCK, _RISK)


def rule_approach_risk(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 3: 접근위험 쪽 LOCK, override 중이면 RELEASE (SWR-005, 006, 009).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    for side in SIDES:
        res = _risk_side(ctx, res, side)
    overridden = any(
        res.deciders.get(s) is PriorityReason.APPROACH_RISK and res.doors.get(s).override_active
        for s in SIDES
    )
    return res.with_reason(_OVERRIDE) if overridden else res


def rule_degraded(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 4: 안전 입력 이상 → 직전 확정 출력 유지 (SWR-013, 022).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    v = ctx.validity
    if not v.safety_abnormal():
        return res
    invalid = Validity.INVALID in (v.if_002, v.if_003, v.if_009)
    code = ReasonCode.INPUT_INVALID if invalid else ReasonCode.INPUT_STALE
    return _decide_all(res, state.outputs, (PriorityReason.DEGRADED, code))


def rule_ignition_off(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 5: 시동 OFF → 좌·우 RELEASE (SWR-020).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    if ctx.validity.if_009 is not Validity.VALID or ctx.snapshot.ignition_on is not False:
        return res
    reason = (PriorityReason.IGNITION_OFF, ReasonCode.IGNITION_OFF)
    return _decide_all(res, _both(LockOutput.RELEASE), reason)


def rule_forced_release(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 6: 화재·과온·성인 탑승 → 좌·우 RELEASE (SWR-017).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    forced = ctx.snapshot.forced_release
    if ctx.validity.if_007 is not Validity.VALID or forced is None:
        return res
    active = [
        code
        for flag, code in (
            (forced.fire, ReasonCode.FIRE),
            (forced.overtemp, ReasonCode.OVERTEMP),
            (forced.adult, ReasonCode.ADULT_PRESENT),
        )
        if flag
    ]
    if not active:
        return res
    reason = (PriorityReason.FORCED_RELEASE, active[0])
    return _decide_all(res, _both(LockOutput.RELEASE), reason)


def isofix_on(ctx: EvalContext, side: Side) -> bool | None:
    """!
    @brief 유효한 ISOFIX 값을 구한다.
    @param ctx 판정 입력
    @param side 쪽
    @return ISOFIX 연결 여부, IF-008이 무효면 None
    """
    isofix = ctx.snapshot.isofix
    if ctx.validity.if_008 is not Validity.VALID or isofix is None:
        return None
    return isofix.get(side)


def rule_isofix(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 7: ISOFIX 연결 쪽 LOCK (SWR-018, 009).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    reason = (PriorityReason.ISOFIX, ReasonCode.ISOFIX)
    for side in SIDES:
        if isofix_on(ctx, side) is True:
            res = res.decide(side, LockOutput.LOCK, reason)
    return res


def _moving(ctx: EvalContext) -> bool | None:
    """!
    @brief 유효 차속이 자동 잠금 기준 이상인지 판단한다.
    @param ctx 판정 입력
    @return 3.0 km/h 이상이면 True, IF-001이 무효면 None
    """
    speed = ctx.snapshot.speed_kph
    if ctx.validity.if_001 is not Validity.VALID or speed is None:
        return None
    return speed >= AUTO_LOCK_SPEED_KPH


def rule_auto_lock(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 8: 차속 3.0 km/h 이상 → 좌·우 LOCK (SWR-003).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    if _moving(ctx) is not True:
        return res
    reason = (PriorityReason.AUTO_LOCK, ReasonCode.AUTO_LOCK_SPEED)
    return _decide_all(res, _both(LockOutput.LOCK), reason)


def _unlock_allowed(ctx: EvalContext, res: Resolution, side: Side) -> bool:
    """!
    @brief 운전자 해제 조건 (a)~(d)를 판단한다 (SWR-004).
    @param ctx 판정 입력
    @param res 중간 결과
    @param side 쪽
    @return 모두 만족하면 True
    """
    return (
        _moving(ctx) is False
        and risk_on(ctx, side) is False
        and isofix_on(ctx, side) is False
        and res.is_open(side)
    )


def _unlock_side(ctx: EvalContext, res: Resolution, side: Side) -> Resolution:
    """!
    @brief 한 쪽 운전자 해제를 적용하거나 거절한다 (SWDD 6.2).
    @param ctx 판정 입력
    @param res 중간 결과
    @param side 쪽
    @return 새 Resolution
    """
    if _unlock_allowed(ctx, res, side):
        reason = (PriorityReason.DRIVER_COMMAND, ReasonCode.DRIVER_UNLOCK)
        return res.decide(side, LockOutput.RELEASE, reason)
    if res.deciders.get(side) is PriorityReason.APPROACH_RISK:
        return res  # 규칙 3이 억제·override로 이미 처리
    return res.add_notice(Notice.DRIVER_UNLOCK_REJECTED)


def rule_driver_command(ctx: EvalContext, state: CoreState, res: Resolution) -> Resolution:
    """!
    @brief 순위 9: 운전자 명령 적용 (SWR-001, 002, 004).
    @param ctx 판정 입력
    @param state 직전 코어 상태
    @param res 중간 결과
    @return 새 Resolution
    """
    if ctx.is_tick:
        return res
    if ctx.validity.if_004 is Validity.INVALID:
        return res.add_notice(Notice.COMMAND_REJECTED)
    reason = (PriorityReason.DRIVER_COMMAND, ReasonCode.DRIVER_LOCK)
    for side in SIDES:
        if command_requested(ctx, side, Action.LOCK):
            res = res.decide(side, LockOutput.LOCK, reason)
        elif command_requested(ctx, side, Action.UNLOCK):
            res = _unlock_side(ctx, res, side)
    return res


## 우선순위 순서의 규칙 (SWR-019)
RULES: tuple[Rule, ...] = (
    rule_crash,
    rule_sensor_fault,
    rule_approach_risk,
    rule_degraded,
    rule_ignition_off,
    rule_forced_release,
    rule_isofix,
    rule_auto_lock,
    rule_driver_command,
)
