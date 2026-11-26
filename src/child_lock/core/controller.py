"""!
@brief SWU-05 컨트롤러 (ASIL B).

코어 상태를 보관하고 평가 순서(검증 → freshness → 명령 새 입력 판정 → 시동 OFF 초기화 → 판정 →
상태 교체)를 실행한다. 시각은 인자로만 받는다. (SWDD 4장)
"""

from collections.abc import Mapping
from dataclasses import replace

from child_lock.core.arbitration import arbitrate
from child_lock.core.model import (
    IDLE_GUARD,
    STALE_LIMIT_MS,
    CoreState,
    Decision,
    EvalContext,
    SidePair,
    Validity,
    VehicleSnapshot,
    diff_ms,
    initial_decision,
    initial_state,
)
from child_lock.core.validation import validate


def is_fresh(ts_s: float | None, now_s: float, last_now_s: float | None) -> bool:
    """!
    @brief 스냅샷 시각이 신선한지 판단한다 (SWR-013, 022, DEF-04).
    @param ts_s 스냅샷 시각(무효면 None)
    @param now_s 평가 시각
    @param last_now_s 직전 평가 시각
    @return 0 ≤ 경과 ≤ 200 ms이고 시각 역행이 없으면 True
    """
    if ts_s is None or (last_now_s is not None and now_s < last_now_s):
        return False
    return 0 <= diff_ms(now_s, ts_s) <= STALE_LIMIT_MS


def is_new_command(
    snapshot: VehicleSnapshot, is_tick: bool, previous: VehicleSnapshot | None
) -> bool:
    """!
    @brief 운전자 명령이 새 입력인지 판단한다 (SWRS DEF-09).
    @param snapshot 현재 스냅샷
    @param is_tick tick 평가 여부
    @param previous 직전 스냅샷
    @return 직전 스냅샷의 명령과 다른 명령이면 True
    """
    if is_tick or snapshot.command is None:
        return False
    return previous is None or previous.command != snapshot.command


def build_context(
    snapshot: VehicleSnapshot, now_s: float, is_tick: bool, state: CoreState
) -> EvalContext:
    """!
    @brief 판정 입력을 만든다 (SWAD 3.3).
    @param snapshot 검증된 스냅샷
    @param now_s 평가 시각
    @param is_tick tick 평가 여부
    @param state 직전 코어 상태
    @return 판정 입력
    """
    fresh = is_fresh(snapshot.source_timestamp_s, now_s, state.last_now_s)
    validity = replace(snapshot.validity, freshness=Validity.VALID if fresh else Validity.STALE)
    command_is_new = is_new_command(snapshot, is_tick, state.last_snapshot)
    return EvalContext(snapshot, now_s, is_tick, validity, command_is_new)


def ignition_off_effective(ctx: EvalContext) -> bool:
    """!
    @brief 시동 OFF 규칙(순위 5)이 효력이 있는지 판단한다 (SWR-020, SWDD 4.4).
    @param ctx 판정 입력
    @return 유효·신선한 시동 OFF이고 센서 고장이 없으면 True
    """
    snap = ctx.snapshot
    return (
        ctx.validity.if_009 is Validity.VALID
        and snap.ignition_on is False
        and snap.sensor_fault is False
        and not ctx.validity.safety_abnormal()
    )


def reset_on_ignition_off(state: CoreState, ctx: EvalContext) -> CoreState:
    """!
    @brief 시동 OFF면 충돌 래치와 override를 초기화한다 (SWR-020).
    @param state 직전 코어 상태
    @param ctx 판정 입력
    @return 초기화가 반영된 코어 상태
    """
    if not ignition_off_effective(ctx):
        return state
    return replace(state, crash_latched=False, doors=SidePair(IDLE_GUARD, IDLE_GUARD))


def latest_time(last: float | None, now: float) -> float:
    """!
    @brief 기준 시각을 갱신한다(역행 후에도 가장 늦은 시각 유지).
    @param last 직전 기준 시각
    @param now 현재 평가 시각
    @return 새 기준 시각
    """
    return now if last is None else max(last, now)


class ChildLockController:
    """!
    @brief 전자식 차일드락 컨트롤러 (SWC-04).
    """

    def __init__(self) -> None:
        """!
        @brief 기동 상태로 초기화한다 (SWRS DEF-06).
        """
        self._state: CoreState = initial_state()
        self._last: Decision = initial_decision(0.0)

    @property
    def last_decision(self) -> Decision:
        """!
        @brief 마지막 판정 결과.
        @return 판정 결과
        """
        return self._last

    def evaluate_snapshot(self, raw: Mapping[str, object], now_s: float) -> Decision:
        """!
        @brief 스냅샷 1건을 평가한다.
        @param raw 원시 스냅샷
        @param now_s 평가 시각(초)
        @return 판정 결과
        """
        return self._evaluate(validate(raw), now_s, is_tick=False)

    def evaluate_tick(self, now_s: float) -> Decision:
        """!
        @brief 새 입력 없이 tick 평가를 한다 (SWR-022).
        @param now_s 평가 시각(초)
        @return 판정 결과
        """
        snapshot = self._state.last_snapshot
        if snapshot is None:
            return self._initial_tick(now_s)
        return self._evaluate(snapshot, now_s, is_tick=True)

    def _evaluate(self, snapshot: VehicleSnapshot, now_s: float, is_tick: bool) -> Decision:
        """!
        @brief 평가 순서를 실행하고 코어 상태를 한 번에 교체한다.
        @param snapshot 평가할 스냅샷
        @param now_s 평가 시각
        @param is_tick tick 평가 여부
        @return 판정 결과
        """
        ctx = build_context(snapshot, now_s, is_tick, self._state)
        decision, next_state = arbitrate(ctx, reset_on_ignition_off(self._state, ctx))
        self._state = replace(
            next_state,
            last_snapshot=snapshot,
            last_now_s=latest_time(self._state.last_now_s, now_s),
        )
        self._last = decision
        return decision

    def _initial_tick(self, now_s: float) -> Decision:
        """!
        @brief 첫 스냅샷 전 tick 결과를 만든다 (SWRS DEF-06).
        @param now_s 평가 시각
        @return 초기 판정 결과
        """
        decision = initial_decision(now_s)
        self._state = replace(self._state, last_now_s=latest_time(self._state.last_now_s, now_s))
        self._last = decision
        return decision
