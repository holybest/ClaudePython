"""!
@brief SWU-06 안전 런타임 (ASIL B).

단조 시계, 평가 직렬화 잠금, 50 ms tick 스레드를 제공한다. 판정 결과는 콜백으로 전달하며
이력 모듈을 import하지 않는다. (SWDD 7장, SWAD 4.2)
"""

import threading
import time
from collections.abc import Callable, Mapping

from child_lock.core.controller import ChildLockController
from child_lock.core.model import Decision

## 판정 결과 콜백 형식: (판정 결과, tick 평가 여부). 반환값은 쓰지 않는다
DecisionCallback = Callable[[Decision, bool], object]


class MonotonicClock:
    """!
    @brief 생성 시점 기준 단조 증가 시계(초).
    """

    def __init__(self) -> None:
        """!
        @brief 기준 시점을 기록한다.
        """
        self._origin = time.monotonic()

    def __call__(self) -> float:
        """!
        @brief 현재 시각을 구한다.
        @return 기준 시점 이후 경과 초
        """
        return time.monotonic() - self._origin


class SafetyRuntime:
    """!
    @brief 컨트롤러 평가를 직렬화하고 주기 tick을 실행한다 (SWC-10).
    """

    def __init__(
        self,
        controller: ChildLockController,
        clock: Callable[[], float],
        on_decision: DecisionCallback | None = None,
        tick_period_s: float = 0.05,
    ) -> None:
        """!
        @brief 런타임을 만든다.
        @param controller 컨트롤러
        @param clock 시각 공급 함수(초)
        @param on_decision 판정 결과 콜백
        @param tick_period_s tick 주기(초)
        """
        self._controller = controller
        self._clock = clock
        self._on_decision = on_decision
        self._period = tick_period_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.tick_errors = 0
        self.callback_errors = 0

    def evaluate_snapshot(self, raw: Mapping[str, object]) -> Decision:
        """!
        @brief 잠금 아래에서 스냅샷을 평가한다.
        @param raw 원시 스냅샷
        @return 판정 결과
        """
        with self._lock:
            decision = self._controller.evaluate_snapshot(raw, self._clock())
            self._notify(decision, False)
        return decision

    def tick(self) -> Decision:
        """!
        @brief 잠금 아래에서 tick 평가를 한다 (SWR-022).
        @return 판정 결과
        """
        with self._lock:
            decision = self._controller.evaluate_tick(self._clock())
            self._notify(decision, True)
        return decision

    def now(self) -> float:
        """!
        @brief 런타임 시계 값을 구한다.
        @return 현재 시각(초)
        """
        return self._clock()

    def last_decision(self) -> Decision:
        """!
        @brief 마지막 판정 결과를 구한다.
        @return 판정 결과
        """
        with self._lock:
            return self._controller.last_decision

    def _notify(self, decision: Decision, is_tick: bool) -> None:
        """!
        @brief 콜백을 호출한다. 콜백 예외는 평가 결과에 영향을 주지 않는다.
        @param decision 판정 결과
        @param is_tick tick 평가 여부
        """
        if self._on_decision is None:
            return
        try:
            self._on_decision(decision, is_tick)
        except Exception:
            self.callback_errors += 1

    def start(self) -> None:
        """!
        @brief tick 스레드를 시작한다. 이미 실행 중이면 아무것도 하지 않는다.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._tick_loop, name="tick", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """!
        @brief tick 스레드를 멈춘다.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _tick_loop(self) -> None:
        """!
        @brief 정지 요청 전까지 주기마다 tick을 실행한다. 예외가 나도 계속한다.
        """
        while not self._stop.wait(self._period):
            try:
                self.tick()
            except Exception:
                self.tick_errors += 1
