"""!
@brief SWU-07 결정 이력 (QM).

최근 100건의 결정 이벤트를 메모리에만 보관한다. 스냅샷 평가는 모두, tick 평가는 출력·상태·
reason_code가 바뀔 때만 기록한다. (SWDD 8장, SWR-010~012, CR-01)
"""

import threading
from collections import deque
from dataclasses import dataclass

from child_lock.core.model import Decision, LockOutput, Notice, PriorityReason, ReasonCode, State

## 변화 판단 키 (좌, 우, 상태, reason_code)
_Key = tuple[LockOutput, LockOutput, State, ReasonCode]


@dataclass(frozen=True, slots=True)
class Event:
    """!
    @brief 결정 이벤트 (SWR-011 허용 필드만).
    """

    event_id: int
    timestamp_s: float
    lock_left: LockOutput
    lock_right: LockOutput
    state: State
    priority_reason: PriorityReason
    reason_code: ReasonCode
    notices: tuple[Notice, ...]


def _key(decision: Decision) -> _Key:
    """!
    @brief tick 기록 여부를 판단할 키를 만든다.
    @param decision 판정 결과
    @return (좌, 우, 상태, reason_code)
    """
    return (decision.lock_left, decision.lock_right, decision.state, decision.reason_code)


class EventLog:
    """!
    @brief 메모리 링 버퍼 결정 이력.
    """

    def __init__(self, capacity: int = 100) -> None:
        """!
        @brief 빈 이력을 만든다.
        @param capacity 보관 건수
        """
        self._events: deque[Event] = deque(maxlen=capacity)
        self._next_id = 1
        self._last_key: _Key | None = None
        self._lock = threading.Lock()

    def record(self, decision: Decision, is_tick: bool) -> Event | None:
        """!
        @brief 판정 결과를 기록한다. 변화 없는 tick 결과는 기록하지 않는다.
        @param decision 판정 결과
        @param is_tick tick 평가 여부
        @return 기록한 이벤트, 기록하지 않았으면 None
        """
        with self._lock:
            key = _key(decision)
            changed = key != self._last_key
            self._last_key = key
            if is_tick and not changed:
                return None
            event = Event(
                self._next_id,
                decision.timestamp_s,
                decision.lock_left,
                decision.lock_right,
                decision.state,
                decision.priority_reason,
                decision.reason_code,
                decision.notices,
            )
            self._next_id += 1
            self._events.append(event)
            return event

    def events(self) -> tuple[Event, ...]:
        """!
        @brief 보관 중인 이벤트를 오래된 순으로 구한다.
        @return 이벤트 튜플
        """
        with self._lock:
            return tuple(self._events)
