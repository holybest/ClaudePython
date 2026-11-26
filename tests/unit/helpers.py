"""!
@brief 단위·통합 시험 공용 도구: 원시 스냅샷 생성과 컨트롤러 하니스.
"""

from child_lock.core.controller import ChildLockController
from child_lock.core.model import Decision


def raw_snapshot(ts: float | None, **changes: object) -> dict[str, object]:
    """모든 입력이 정상(정지, 시동 ON)인 원시 스냅샷을 만든다. ts=None이면 시각 키를 뺀다."""
    raw: dict[str, object] = {
        "vehicle_speed_kph": 0.0,
        "gear": "P",
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
    if ts is not None:
        raw["source_timestamp_s"] = ts
    raw.update(changes)
    return {k: v for k, v in raw.items() if v is not DROP}


## 원시 스냅샷에서 키를 빼라는 표시
DROP = object()


def cmd(side: str, action: str, source: str = "physical_button") -> dict[str, str]:
    """운전자 명령 객체를 만든다."""
    return {"side": side, "action": action, "source": source}


def summary(d: Decision) -> tuple[object, ...]:
    """판정 결과를 비교하기 쉬운 튜플로 바꾼다."""
    return (
        d.lock_left.value,
        d.lock_right.value,
        d.state.value,
        d.priority_reason.value,
        d.reason_code.value,
        tuple(n.value for n in d.notices),
    )


class Harness:
    """시각을 지정해 스냅샷·tick을 넣는 컨트롤러 하니스."""

    def __init__(self) -> None:
        self.ctl = ChildLockController()

    def send(self, now: float, ts: float | None | object = "same", **changes: object) -> Decision:
        """now 시각에 스냅샷을 넣는다. ts 기본값은 now와 같다."""
        stamp = now if ts == "same" else ts
        return self.ctl.evaluate_snapshot(raw_snapshot(stamp, **changes), now)

    def tick(self, now: float) -> Decision:
        """now 시각에 tick 평가를 한다."""
        return self.ctl.evaluate_tick(now)
