"""!
@brief SWU-06 안전 런타임, SWU-07 결정 이력, SWU-08 응용 조립 단위 시험 (SWDD 7~9장).
"""

import threading
import time

import pytest

from child_lock.app.event_log import Event, EventLog
from child_lock.app.service import ChildLockService, create_service
from child_lock.core import model as m
from child_lock.core.controller import ChildLockController
from child_lock.runtime.runtime import MonotonicClock, SafetyRuntime
from tests.unit.helpers import cmd, raw_snapshot


class FakeClock:
    """시험용 수동 시계."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Recorder:
    """콜백 호출 기록."""

    def __init__(self) -> None:
        self.calls: list[tuple[m.Decision, bool]] = []

    def __call__(self, decision: m.Decision, is_tick: bool) -> None:
        self.calls.append((decision, is_tick))


def _wait_until(cond, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------- SWU-06 안전 런타임


def test_monotonic_clock_starts_near_zero_and_never_decreases():
    clock = MonotonicClock()
    a = clock()
    b = clock()
    assert 0.0 <= a <= b < 1.0


def test_snapshot_evaluation_uses_clock_and_notifies_non_tick():
    clock, rec = FakeClock(2.0), Recorder()
    rt = SafetyRuntime(ChildLockController(), clock, rec)
    d = rt.evaluate_snapshot(raw_snapshot(2.0, command=cmd("left", "lock")))
    assert (d.lock_left, d.timestamp_s) == (m.LockOutput.LOCK, 2.0)
    assert rec.calls == [(d, False)]
    assert rt.last_decision() == d
    assert rt.now() == 2.0


def test_tick_evaluation_notifies_tick():
    clock, rec = FakeClock(1.0), Recorder()
    rt = SafetyRuntime(ChildLockController(), clock, rec)
    d = rt.tick()
    assert d.state is m.State.OFF
    assert rec.calls == [(d, True)]


def test_runtime_without_callback_still_evaluates():
    rt = SafetyRuntime(ChildLockController(), FakeClock(0.5))
    assert rt.tick().timestamp_s == 0.5


def test_callback_exception_is_counted_and_decision_returned():
    def broken(_d: m.Decision, _t: bool) -> None:
        raise ValueError("이력 오류")

    rt = SafetyRuntime(ChildLockController(), FakeClock(1.0), broken)
    d = rt.evaluate_snapshot(raw_snapshot(1.0, command=cmd("all", "lock")))
    assert d.lock_left is m.LockOutput.LOCK
    assert rt.callback_errors == 1


class ExplodingController(ChildLockController):
    """평가 때마다 예외를 던지는 컨트롤러."""

    def evaluate_snapshot(self, raw, now_s):
        raise RuntimeError("코어 오류")

    def evaluate_tick(self, now_s):
        raise RuntimeError("코어 오류")


def test_controller_exception_propagates_and_lock_is_released():
    rt = SafetyRuntime(ExplodingController(), FakeClock(1.0))
    with pytest.raises(RuntimeError):
        rt.evaluate_snapshot({})
    with pytest.raises(RuntimeError):
        rt.tick()  # 잠금이 풀려 있어야 다시 호출 가능


def test_tick_thread_runs_periodically_and_can_restart():
    rec = Recorder()
    rt = SafetyRuntime(ChildLockController(), MonotonicClock(), rec, tick_period_s=0.01)
    rt.start()
    rt.start()  # 이미 실행 중이면 무시
    assert _wait_until(lambda: len(rec.calls) >= 3)
    rt.stop()
    count = len(rec.calls)
    time.sleep(0.05)
    assert len(rec.calls) == count  # 정지 후 tick 없음
    rt.start()  # 재시작 가능 (검토 D-10)
    assert _wait_until(lambda: len(rec.calls) > count)
    rt.stop()
    assert all(is_tick for _, is_tick in rec.calls)


def test_tick_thread_keeps_average_period_of_50ms_despite_timer_granularity():
    # Windows 대기 분해능(약 15.6 ms) 때문에 50 ms 대기가 62.5 ms로 늘어나도
    # 평균 주기는 50 ms여야 한다 (SWR-022)
    rec = Recorder()
    rt = SafetyRuntime(ChildLockController(), MonotonicClock(), rec, tick_period_s=0.05)
    rt.start()
    time.sleep(1.02)
    rt.stop()
    assert 19 <= len(rec.calls) <= 22


def test_tick_thread_survives_exceptions():
    rt = SafetyRuntime(ExplodingController(), FakeClock(), tick_period_s=0.01)
    rt.start()
    assert _wait_until(lambda: rt.tick_errors >= 2)
    rt.stop()


def test_stop_without_start_is_harmless():
    SafetyRuntime(ChildLockController(), FakeClock()).stop()


def test_concurrent_evaluations_are_serialized():
    rt = SafetyRuntime(ChildLockController(), MonotonicClock())
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(200):
                rt.tick()
        except BaseException as exc:  # 시험 실패 원인 수집
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ---------------------------------------------------------------- SWU-07 결정 이력 (SWR-010~012)


def _decision(
    left: str = "RELEASE", state: str = "NORMAL", code: str = "NO_CHANGE", t: float = 0.0
):
    return m.Decision(
        m.LockOutput(left),
        m.LockOutput.RELEASE,
        m.State(state),
        m.all_valid(),
        m.REASON_PRIORITY[m.ReasonCode(code)],
        m.ReasonCode(code),
        (m.Notice.CRASH_PENDING,),
        t,
    )


def test_snapshot_decisions_are_always_recorded_with_sequential_ids():
    log = EventLog()
    for i in range(3):
        log.record(_decision(t=float(i)), is_tick=False)
    assert [e.event_id for e in log.events()] == [1, 2, 3]


def test_tick_decisions_are_recorded_only_when_output_state_or_reason_changes():
    log = EventLog()
    log.record(_decision(), is_tick=False)
    assert log.record(_decision(t=0.05), is_tick=True) is None  # 변화 없음
    assert log.record(_decision(state="DEGRADED", code="INPUT_STALE"), is_tick=True) is not None
    assert log.record(_decision(state="DEGRADED", code="INPUT_STALE"), is_tick=True) is None
    assert (
        log.record(_decision(left="LOCK", state="DEGRADED", code="INPUT_STALE"), True) is not None
    )
    assert len(log.events()) == 3


def test_event_contains_only_allowed_fields():
    event = EventLog().record(_decision(left="LOCK", t=1.5), is_tick=False)
    assert event == Event(
        event_id=1,
        timestamp_s=1.5,
        lock_left=m.LockOutput.LOCK,
        lock_right=m.LockOutput.RELEASE,
        state=m.State.NORMAL,
        priority_reason=m.PriorityReason.NONE,
        reason_code=m.ReasonCode.NO_CHANGE,
        notices=(m.Notice.CRASH_PENDING,),
    )
    assert [f for f in Event.__dataclass_fields__] == [
        "event_id",
        "timestamp_s",
        "lock_left",
        "lock_right",
        "state",
        "priority_reason",
        "reason_code",
        "notices",
    ]


def test_log_keeps_latest_100_in_order():
    log = EventLog()
    for i in range(101):
        log.record(_decision(t=float(i)), is_tick=False)
    ids = [e.event_id for e in log.events()]
    assert ids == list(range(2, 102))


# ---------------------------------------------------------------- SWU-08 응용 조립


def test_service_submits_snapshot_records_event_and_reports_status():
    clock = FakeClock(1.0)
    svc = create_service(clock)
    d = svc.submit_snapshot(raw_snapshot(1.0, command=cmd("right", "lock")))
    assert d.lock_right is m.LockOutput.LOCK
    clock.now = 1.05
    status = svc.status()
    assert (status.lock_right, status.timestamp_s) == (m.LockOutput.LOCK, 1.05)
    # 명령 직후 tick은 reason_code가 DRIVER_LOCK → NO_CHANGE로 바뀌므로 기록된다 (SWR-010, CR-01)
    codes = [e.reason_code for e in svc.events()]
    assert codes == [m.ReasonCode.DRIVER_LOCK, m.ReasonCode.NO_CHANGE]
    clock.now = 1.1
    svc.status()  # 변화 없는 tick → 기록 안 됨
    assert len(svc.events()) == 2
    assert svc.now() == 1.1


def test_service_status_detects_interruption_via_tick():
    clock = FakeClock(1.0)
    svc = create_service(clock)
    svc.submit_snapshot(raw_snapshot(1.0))
    clock.now = 1.3
    assert svc.status().state is m.State.DEGRADED
    assert svc.events()[-1].reason_code is m.ReasonCode.INPUT_STALE


def test_service_start_stop_controls_tick_thread():
    svc = create_service()
    assert isinstance(svc, ChildLockService)
    svc.start()
    svc.submit_snapshot(raw_snapshot(svc.now()))
    assert _wait_until(lambda: svc.status().state is m.State.DEGRADED, timeout=3.0)
    svc.stop()
