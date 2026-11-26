"""!
@brief SWU-03 우선순위 판정 (ASIL B).

규칙 1~9를 순위대로 적용하고 판정 결과와 다음 코어 상태를 조립하는 순수 함수이다. (SWDD 5장)
"""

from dataclasses import replace

from child_lock.core.model import (
    COMMAND_NOTICES,
    IDLE_GUARD,
    Action,
    CoreState,
    Decision,
    DoorGuard,
    EvalContext,
    LockOutput,
    Notice,
    PriorityReason,
    ReasonCode,
    SidePair,
    State,
    Validity,
)
from child_lock.core.rules import RULES, SIDES, Resolution, command_requested, risk_on


def _sensor_fault(ctx: EvalContext) -> bool:
    """!
    @brief 유효한 센서 고장 입력이 있는지 판단한다.
    @param ctx 판정 입력
    @return 센서 고장이면 True
    """
    return ctx.validity.if_009 is Validity.VALID and ctx.snapshot.sensor_fault is True


def update_guards(ctx: EvalContext, doors: SidePair[DoorGuard]) -> SidePair[DoorGuard]:
    """!
    @brief override 종료 조건을 문 가드에 반영한다 (SWR-006, SWAD 3.4).
    @param ctx 판정 입력
    @param doors 직전 문 가드
    @return 갱신된 문 가드
    """
    ends_override = ctx.validity.safety_abnormal() or _sensor_fault(ctx)
    for side in SIDES:
        guard = doors.get(side)
        if risk_on(ctx, side) is False:
            guard = IDLE_GUARD
        elif ends_override or command_requested(ctx, side, Action.LOCK):
            guard = replace(guard, override_active=False)
        doors = doors.replace(side, guard)
    return doors


def fill_undecided(
    decided: SidePair[LockOutput | None], previous: SidePair[LockOutput]
) -> SidePair[LockOutput]:
    """!
    @brief 미결정 쪽을 직전 확정 출력으로 채운다.
    @param decided 규칙이 결정한 출력
    @param previous 직전 확정 출력
    @return 쪽별 최종 출력
    """
    left, right = decided.left, decided.right
    return SidePair(
        left if left is not None else previous.left,
        right if right is not None else previous.right,
    )


def ordered_notices(notices: frozenset[Notice], is_tick: bool) -> tuple[Notice, ...]:
    """!
    @brief 알림을 정의 순서로 정렬하고, tick이면 명령 관련 알림을 뺀다 (SWAD 3.2).
    @param notices 수집한 알림
    @param is_tick tick 평가 여부
    @return 정렬된 알림
    """
    return tuple(n for n in Notice if n in notices and not (is_tick and n in COMMAND_NOTICES))


def compute_state(ctx: EvalContext, res: Resolution) -> State:
    """!
    @brief 시스템 상태를 결정한다 (SWRS DEF-10).
    @param ctx 판정 입력
    @param res 규칙 적용 결과
    @return 상태
    """
    v = ctx.validity
    if res.crash_latched:
        return State.EMERGENCY
    if _sensor_fault(ctx):
        return State.FAULT
    if v.safety_abnormal():
        return State.DEGRADED
    if any(res.doors.get(s).override_active for s in SIDES):
        return State.OVERRIDE
    if v.if_009 is Validity.VALID and ctx.snapshot.ignition_on is False:
        return State.OFF
    return State.NORMAL


def arbitrate(ctx: EvalContext, state: CoreState) -> tuple[Decision, CoreState]:
    """!
    @brief 규칙 1~9를 순위대로 적용해 판정 결과와 다음 코어 상태를 만든다 (SWR-019).
    @param ctx 판정 입력
    @param state 직전 코어 상태(시동 OFF 초기화 반영본)
    @return (판정 결과, 다음 코어 상태)
    """
    res = Resolution.start(update_guards(ctx, state.doors), state.crash_latched)
    for rule in RULES:
        res = rule(ctx, state, res)
    outputs = fill_undecided(res.outputs, state.outputs)
    reason = res.reason or (PriorityReason.NONE, ReasonCode.NO_CHANGE)
    decision = Decision(
        lock_left=outputs.left,
        lock_right=outputs.right,
        state=compute_state(ctx, res),
        input_validity=ctx.validity,
        priority_reason=reason[0],
        reason_code=reason[1],
        notices=ordered_notices(res.notices, ctx.is_tick),
        timestamp_s=ctx.now_s,
    )
    next_state = CoreState(
        outputs, res.crash_latched, res.doors, state.last_snapshot, state.last_now_s
    )
    return decision, next_state
