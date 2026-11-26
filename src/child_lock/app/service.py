"""!
@brief SWU-08 응용 조립 (QM).

컨트롤러·안전 런타임·결정 이력을 만들고 연결해 Web 계층에 파사드를 제공한다.
Web은 런타임을 직접 호출하지 않고 이 서비스만 쓴다(SWAD DEP-05). (SWDD 9장)
"""

from collections.abc import Callable, Mapping

from child_lock.app.event_log import Event, EventLog
from child_lock.core.controller import ChildLockController
from child_lock.core.model import Decision
from child_lock.runtime.runtime import MonotonicClock, SafetyRuntime


class ChildLockService:
    """!
    @brief Web 계층용 서비스 파사드.
    """

    def __init__(self, runtime: SafetyRuntime, log: EventLog) -> None:
        """!
        @brief 서비스를 만든다.
        @param runtime 안전 런타임
        @param log 결정 이력
        """
        self._runtime = runtime
        self._log = log

    def submit_snapshot(self, raw: Mapping[str, object]) -> Decision:
        """!
        @brief 스냅샷을 평가한다.
        @param raw 원시 스냅샷
        @return 판정 결과
        """
        return self._runtime.evaluate_snapshot(raw)

    def status(self) -> Decision:
        """!
        @brief tick 평가 1회 후 상태를 구한다 (SWR-014, 022).
        @return 판정 결과
        """
        return self._runtime.tick()

    def events(self) -> tuple[Event, ...]:
        """!
        @brief 결정 이력을 구한다 (SWR-012).
        @return 이벤트 튜플
        """
        return self._log.events()

    def now(self) -> float:
        """!
        @brief 런타임 시계 값을 구한다.
        @return 현재 시각(초)
        """
        return self._runtime.now()

    def start(self) -> None:
        """!
        @brief tick 스레드를 시작한다.
        """
        self._runtime.start()

    def stop(self) -> None:
        """!
        @brief tick 스레드를 멈춘다.
        """
        self._runtime.stop()


def create_service(clock: Callable[[], float] | None = None) -> ChildLockService:
    """!
    @brief 서비스와 구성 요소를 만들어 연결한다.
    @param clock 시각 공급 함수(없으면 단조 시계)
    @return 서비스
    """
    log = EventLog()
    runtime = SafetyRuntime(ChildLockController(), clock or MonotonicClock(), log.record)
    return ChildLockService(runtime, log)
