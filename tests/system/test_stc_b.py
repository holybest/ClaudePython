"""!
@brief 시스템 시험 STC-F-046 ~ STC-F-090 (STC-F-060은 test_stc_examples.py에 있으므로 제외).

케이스 1건 = 시험 함수 1개. 표기(B0, N, cmd, S0, S-LOCK, OV, KA, T, floor_ms)는
docs/06_system_test/system_test_cases.json의 environment 필드를 따른다.
notices는 집합 비교(순서 무관)이므로 비교 전에 정렬한다.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.system.harness import DROP, ROOT, Simulator, b0, cmd, expect, floor_ms, summary

## 시험 공통 입력: 왼쪽 접근위험 TRUE (표기 N)
N = b0(rear_left_approach_risk=True)
## 왼쪽 해제 요청 (표기 REQ1, ts 생략)
REQ_L = b0(rear_left_approach_risk=True, command=cmd("left", "unlock"))
## 결정 이벤트 허용 필드 (SWR-011)
EVENT_KEYS = {
    "event_id",
    "timestamp_s",
    "lock_left",
    "lock_right",
    "state",
    "priority_reason",
    "reason_code",
    "notices",
}

# ---- 지역 도우미


def ssum(d: dict[str, object]) -> dict[str, object]:
    """summary에 notices를 정렬해 집합 비교가 되게 한다."""
    s = summary(d)
    s["notices"] = sorted(s["notices"])
    return s


def ex(*args: object, **kwargs: object) -> dict[str, object]:
    """expect 결과의 notices를 정렬한다."""
    e = expect(*args, **kwargs)
    e["notices"] = sorted(e["notices"])
    return e


def with_ts(raw: dict[str, object], ts: float) -> dict[str, object]:
    """스냅샷에 source_timestamp_s를 붙인다."""
    return {**raw, "source_timestamp_s": ts}


def age_ms(d: dict[str, object], ts: float) -> float:
    """표기 age: 응답 timestamp_s - source_timestamp_s (ms)."""
    return (float(d["timestamp_s"]) - ts) * 1000


def setup_n(sim: Simulator) -> None:
    """사전조건: S0 후 N 전송 (L=LOCK, R=RELEASE, APPROACH_RISK)."""
    sim.s0()
    d = sim.send(N)
    assert ssum(d) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def setup_ov(sim: Simulator) -> float:
    """OV: S0, N, ts1=floor_ms(T), REQ1(ts1), N, REQ1(ts1)을 150 ms 이내 수행(L override)."""
    sim.s0()
    sim.send(N)
    ts1 = floor_ms(sim.now())
    start = time.monotonic()
    sim.send(with_ts(REQ_L, ts1))
    sim.send(N)
    d = sim.send(with_ts(REQ_L, ts1))
    assert time.monotonic() - start <= 0.150, "OV 절차가 150 ms를 넘었습니다"
    assert ssum(d) == ex("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")
    return ts1


def send_req_at(sim: Simulator, req: dict[str, object], ts: float, at: float) -> dict[str, object]:
    """KA(N 반복)로 서버 시각이 at 이상이 되기를 기다렸다가 즉시 req(ts)를 보낸다.

    OS 대기 분해능 때문에 늦게 보내지 않도록 at 50 ms 전부터는 쉬지 않고 서버 시각을 조회하고,
    KA를 멈추기(스레드 join) 전에 req를 보낸다.
    """
    with sim.keepalive(N):
        sim.wait_until_server_time(at - 0.050)
        while sim.now() < at:
            pass
        return sim.send(with_ts(req, ts))


@contextmanager
def fresh_sim() -> Iterator[Simulator]:
    """파트 B 등을 위해 서버를 신규 기동한다(사전조건 '서버 재기동')."""
    s = Simulator()
    try:
        yield s
    finally:
        s.stop()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CwdSimulator(Simulator):
    """작업 디렉터리를 지정해 기동하는 시뮬레이터(파일 생성 여부 관찰용, SWR-012)."""

    def __init__(self, cwd: Path) -> None:
        self.port = _free_port()
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "child_lock.web", "--port", str(self.port)],
            env=env,
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_ready()


def file_list(root: Path) -> set[tuple[str, int]]:
    """작업 디렉터리의 파일 목록(상대 경로, 수정 시각)."""
    return {(str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*")}


def ev_brief(e: dict[str, object]) -> tuple[object, ...]:
    """이벤트 비교용 요약 (좌, 우, 상태, reason_code, 정렬된 notices)."""
    return (e["lock_left"], e["lock_right"], e["state"], e["reason_code"], sorted(e["notices"]))


# ---- SWR-006 override 창·시간 기준


def test_stc_f_046_window_exceeded_resuppresses_and_renews_t0(sim):
    """STC-F-046 (SWR-006) 10,001 ms 재요청은 재억제·t0 갱신, 3,000 ms 뒤 재요청은 override."""
    setup_n(sim)
    ts1 = floor_ms(sim.now())
    # 2) REQ1
    d = sim.send(with_ts(REQ_L, ts1))
    sup = ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"])
    assert ssum(d) == sup
    # 3)~4) KA 후 REQ2(ts1+10.001)
    ts2 = ts1 + 10.001
    d = send_req_at(sim, REQ_L, ts2, ts2)
    assert age_ms(d, ts2) <= 190
    assert ssum(d) == sup
    # 5)~6) KA 후 REQ3(ts1+13.001): t0=ts2 기준 3,000 ms
    ts3 = ts1 + 10.001 + 3.000
    d = send_req_at(sim, REQ_L, ts3, ts3)
    assert age_ms(d, ts3) <= 190
    assert ssum(d) == ex("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")


def _req2_after(s: Simulator, delta: float) -> tuple[dict[str, object], float]:
    """사전조건, REQ1(ts1=floor_ms(T)), KA, 서버 시각 >= ts1+delta 즉시 REQ2 전송."""
    setup_n(s)
    ts1 = floor_ms(s.now())
    d = s.send(with_ts(REQ_L, ts1))
    assert ssum(d) == ex(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"]
    )
    ts2 = ts1 + delta
    d = send_req_at(s, REQ_L, ts2, ts2)
    assert age_ms(d, ts2) <= 190
    return d, ts2


def test_stc_f_047_ms_rounding_boundary(sim):
    """STC-F-047 (SWR-006) 시간차 10,000.4 ms는 override, 10,000.6 ms는 재억제(ms 정수 반올림)."""
    # 파트 A: 10.0004 s -> ms 정수 10,000 -> override
    d, _ = _req2_after(sim, 10.0004)
    assert ssum(d) == ex("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")
    # 파트 B: 서버 재기동, 10.0006 s -> ms 정수 10,001 -> 재억제
    with fresh_sim() as s2:
        d, _ = _req2_after(s2, 10.0006)
        assert ssum(d) == ex(
            "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"]
        )


## STC-F-048 시도 횟수 상한: age가 0~190 ms 밖인 시도는 무효이므로 서버를 재기동해 다시 시도
STC_F_048_MAX_ATTEMPTS = int(os.environ.get("STC_F_048_MAX_ATTEMPTS", "3"))
SUP_L = ("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"])


def _age_ok(d: dict[str, object], ts: float) -> bool:
    """STC-F-048 절차 3: 응답 age가 0~190 ms인 시도만 유효."""
    return 0 <= age_ms(d, ts) <= 190


def _stc_048_attempt(
    s: Simulator, req1_lag: float, gap: float, req2_lag: float
) -> dict[str, object] | None:
    """사전조건, REQ1(ts1=T-req1_lag), KA, 서버 시각 >= ts2+req2_lag 즉시 REQ2(ts2=ts1+gap).

    유효한 시도면 REQ2 응답을, age 범위를 벗어난 무효 시도면 None을 돌려준다.
    """
    setup_n(s)
    ts1 = s.now() - req1_lag
    d = s.send(with_ts(REQ_L, ts1))
    if not _age_ok(d, ts1):
        return None
    assert ssum(d) == ex(*SUP_L)
    ts2 = ts1 + gap
    d = send_req_at(s, REQ_L, ts2, ts2 + req2_lag)
    return d if _age_ok(d, ts2) else None


def _stc_048_part(
    sim: Simulator, req1_lag: float, gap: float, req2_lag: float
) -> dict[str, object]:
    """유효한 시도가 나올 때까지(상한 STC_F_048_MAX_ATTEMPTS) 서버를 새로 기동해 반복한다."""
    d = _stc_048_attempt(sim, req1_lag, gap, req2_lag)
    for _ in range(STC_F_048_MAX_ATTEMPTS - 1):
        if d is not None:
            break
        with fresh_sim() as s:
            d = _stc_048_attempt(s, req1_lag, gap, req2_lag)
    assert d is not None, "유효한 시도(age 0~190 ms)를 얻지 못했습니다"
    return d


def test_stc_f_048_window_uses_source_timestamp(sim):
    """STC-F-048 (SWR-006) override 창 시간차는 수신 시각이 아니라 source_timestamp_s로 계산."""
    # 파트 A: REQ1 ts1=T-0.150 (지연 약 150 ms), REQ2 ts2=ts1+10.100 (지연 약 0 ms)
    d = _stc_048_part(sim, 0.150, 10.100, 0.0)
    assert ssum(d) == ex(*SUP_L)
    # 파트 B: 서버 재기동, REQ1 ts1=T, REQ2 ts2=ts1+9.900을 서버 시각 >= ts2+0.150 에 전송
    with fresh_sim() as s2:
        d = _stc_048_part(s2, 0.0, 9.900, 0.150)
    assert ssum(d) == ex("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")


# ---- SWR-006 쪽 구분, side=all


def test_stc_f_049_opposite_side_request_is_not_override(sim):
    """STC-F-049 (SWR-006) 반대쪽 해제 요청은 override가 아니고 위험 없는 쪽 요청은 정상 처리."""
    setup_n(sim)
    d = sim.send(REQ_L)
    assert ssum(d) == ex(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"]
    )
    sim.send(N)
    d = sim.send(b0(rear_left_approach_risk=True, command=cmd("right", "unlock")))
    assert ssum(d) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_050_all_unlock_split_by_side(sim):
    """STC-F-050 (SWR-006, SWR-001) side=all 해제: 위험 쪽 억제/override, 반대쪽 정상 해제."""
    sim.s_lock()
    d = sim.send(N)
    assert (d["lock_left"], d["lock_right"]) == ("LOCK", "LOCK")
    req_a = b0(rear_left_approach_risk=True, command=cmd("all", "unlock"))
    # 2) notices는 UNLOCK_SUPPRESSED 포함 여부만 판정(DRIVER_UNLOCK_REJECTED 동반 여부는 관찰만)
    d = sim.send(req_a)
    s = ssum(d)
    assert "UNLOCK_SUPPRESSED" in s.pop("notices")
    e = ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    e.pop("notices")
    assert s == e
    # 3) N
    d = sim.send(N)
    assert ssum(d) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    # 4) REQA 재전송(1 s 이내, ts 생략)
    d = sim.send(req_a)
    assert ssum(d) == ex("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")


def test_stc_f_051_guard_independent_per_side(sim):
    """STC-F-051 (SWR-006, SWR-009) 양쪽 위험에서 억제 이력·override는 쪽별로 독립."""
    n2 = b0(rear_left_approach_risk=True, rear_right_approach_risk=True)
    sim.s_lock()
    d = sim.send(n2)
    assert (d["lock_left"], d["lock_right"]) == ("LOCK", "LOCK")
    sup = ex("LOCK", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"])
    req_l = {**n2, "command": cmd("left", "unlock")}
    req_r = {**n2, "command": cmd("right", "unlock")}
    assert ssum(sim.send(req_l)) == sup
    sim.send(n2)
    assert ssum(sim.send(req_r)) == sup
    sim.send(n2)
    # 6) reason_code는 좌 APPROACH_OVERRIDE/우 APPROACH_RISK 동순위라 판정 제외(관찰만)
    s = ssum(sim.send(req_l))
    s.pop("reason_code")
    e = ex("RELEASE", "LOCK", "OVERRIDE", "APPROACH_RISK", "")
    e.pop("reason_code")
    assert s == e


# ---- SWR-006 override 지속·종료


def test_stc_f_052_override_persists_beyond_window(sim):
    """STC-F-052 (SWR-006) override는 10,000 ms 넘어 유지, 위험 FALSE에서 종료, 재발생 시 LOCK."""
    ov = ex("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")
    setup_ov(sim)
    # 2) N을 100 ms 주기로 11 s간 전송, 매 응답 확인
    start = time.monotonic()
    count = 0
    while time.monotonic() - start < 11.0:
        assert ssum(sim.send(N)) == ov, f"{count}번째 응답"
        count += 1
        time.sleep(max(0.0, start + count * 0.1 - time.monotonic()))
    assert ssum(sim.send(b0())) == ex("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    assert ssum(sim.send(N)) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_053_lock_command_ends_override_same_side_only(sim):
    """STC-F-053 (SWR-006) override 중 그 쪽 잠금 명령만 override를 끝냄(반대쪽은 아님)."""
    setup_ov(sim)
    keep = ex("RELEASE", "LOCK", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")
    assert ssum(sim.send({**N, "command": cmd("right", "lock")})) == keep
    # 3) 케이스는 L/R/state만 명시("같은 값")하므로 2)와 같은 판정으로 비교
    assert ssum(sim.send(N)) == keep
    end = ex("LOCK", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    assert ssum(sim.send({**N, "command": cmd("left", "lock")})) == end
    assert ssum(sim.send(N)) == end


def test_stc_f_054_all_lock_ends_override(sim):
    """STC-F-054 (SWR-006) override 중 side=all 잠금 명령도 override를 끝냄."""
    setup_ov(sim)
    end = ex("LOCK", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    assert ssum(sim.send({**N, "command": cmd("all", "lock")})) == end
    assert ssum(sim.send(N)) == end


def test_stc_f_055_ignition_off_resets_override(sim):
    """STC-F-055 (SWR-006, SWR-020) 시동 OFF가 override를 초기화하고 ON 복귀 후 되살아나지 않음."""
    setup_ov(sim)
    d = sim.send(b0(rear_left_approach_risk=True, ignition_on=False))
    assert ssum(d) == ex("LOCK", "RELEASE", "OFF", "APPROACH_RISK", "APPROACH_RISK")
    assert ssum(sim.send(N)) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_056_crash_ends_override(sim):
    """STC-F-056 (SWR-006, SWR-007) 충돌 해제가 override를 끝내고 래치 해제 후 위험 TRUE면 LOCK."""
    setup_ov(sim)
    d = sim.send(b0(rear_left_approach_risk=True, crash_status="CONFIRMED"))
    assert ssum(d) == ex("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")
    d = sim.send(b0(rear_left_approach_risk=True, ignition_on=False))
    assert ssum(d) == ex("LOCK", "RELEASE", "OFF", "APPROACH_RISK", "APPROACH_RISK")
    assert ssum(sim.send(N)) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_057_sensor_fault_ends_override(sim):
    """STC-F-057 (SWR-006, SWR-021) 센서 고장이 override를 끝내고 고장 해제 후 위험 TRUE면 LOCK."""
    setup_ov(sim)
    d = sim.send(b0(rear_left_approach_risk=True, sensor_fault=True))
    assert ssum(d) == ex("RELEASE", "RELEASE", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT")
    assert ssum(sim.send(N)) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_058_stale_snapshot_ends_override(sim):
    """STC-F-058 (SWR-006, SWR-013) 지연 스냅샷이 override를 끝내고 복귀 후에도 LOCK."""
    setup_ov(sim)
    t = sim.now()
    d = sim.send(with_ts(N, t - 0.300))
    assert ssum(d) == ex("LOCK", "RELEASE", "DEGRADED", "APPROACH_RISK", "APPROACH_RISK")
    assert d["input_validity"]["FRESHNESS"] == "STALE"
    assert ssum(sim.send(N)) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_059_no_override_while_degraded(sim):
    """STC-F-059 (SWR-006, SWR-013) DEGRADED 중 해제 재요청은 override로 처리하지 않음."""
    setup_n(sim)
    d = sim.send(REQ_L)
    assert ssum(d) == ex(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"]
    )
    sim.send(N)
    t = sim.now()
    # 5) notices는 판정 제외(관찰만)
    s = ssum(sim.send(with_ts(REQ_L, t - 0.300)))
    s.pop("notices")
    e = ex("LOCK", "RELEASE", "DEGRADED", "APPROACH_RISK", "APPROACH_RISK")
    e.pop("notices")
    assert s == e


def test_stc_f_061_risk_false_resets_suppression(sim):
    """STC-F-061 (SWR-006) 위험 FALSE 후 다시 TRUE가 된 뒤의 첫 해제 요청은 새 첫 요청으로 억제."""
    sup = ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"])
    setup_n(sim)
    start = time.monotonic()
    assert ssum(sim.send(REQ_L)) == sup
    sim.send(b0())
    sim.send(N)
    d = sim.send(REQ_L)
    assert time.monotonic() - start < 1.0
    assert ssum(d) == sup


def test_stc_f_062_input_timeout_ends_override(sim):
    """STC-F-062 (SWR-006, SWR-022) 입력 중단(tick DEGRADED)이 override를 끝냄."""
    setup_ov(sim)
    time.sleep(0.400)
    d = sim.status()
    assert ssum(d) == ex("LOCK", "RELEASE", "DEGRADED", "APPROACH_RISK", "APPROACH_RISK")
    assert d["input_validity"]["FRESHNESS"] == "STALE"
    assert ssum(sim.send(N)) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


# ---- SWR-007 충돌 CONFIRMED·래치

EMERGENCY = ("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")


def test_stc_f_063_confirmed_releases_both_same_evaluation(sim):
    """STC-F-063 (SWR-007) CONFIRMED가 들어온 같은 평가에서 좌·우 RELEASE, EMERGENCY."""
    sim.s_lock()
    assert ssum(sim.send(b0(crash_status="CONFIRMED"))) == ex(*EMERGENCY)


def test_stc_f_064_crash_latch_holds(sim):
    """STC-F-064 (SWR-007) CONFIRMED 후 NONE·잠금·차속·위험·ISOFIX에도 RELEASE 래치 유지."""
    sim.s_lock()
    sim.send(b0(crash_status="CONFIRMED"))
    inputs = [
        b0(),
        b0(command=cmd("all", "lock")),
        b0(vehicle_speed_kph=3.0),
        b0(rear_left_approach_risk=True, rear_right_approach_risk=True),
        b0(isofix_left=True, isofix_right=True),
    ]
    for label, raw in zip("abcde", inputs, strict=True):
        time.sleep(0.050)
        assert ssum(sim.send(raw)) == ex(*EMERGENCY), label


def test_stc_f_065_confirmed_despite_stale(sim):
    """STC-F-065 (SWR-007) CONFIRMED는 지연(STALE) 스냅샷이어도 적용."""
    sim.s_lock()
    t = sim.now()
    assert ssum(sim.send(b0(crash_status="CONFIRMED", source_timestamp_s=t - 0.300))) == ex(
        *EMERGENCY
    )


def test_stc_f_066_confirmed_despite_if001_invalid(sim):
    """STC-F-066 (SWR-007) CONFIRMED는 IF-001 무효(차속 누락)와 관계없이 적용."""
    sim.s_lock()
    assert ssum(sim.send(b0(crash_status="CONFIRMED", vehicle_speed_kph=DROP))) == ex(*EMERGENCY)


def test_stc_f_067_confirmed_despite_if003_invalid(sim):
    """STC-F-067 (SWR-007) CONFIRMED는 IF-003 무효(접근위험 문자열 "true")와 관계없이 적용."""
    sim.s_lock()
    d = sim.send(b0(crash_status="CONFIRMED", rear_left_approach_risk="true"))
    assert ssum(d) == ex(*EMERGENCY)


def test_stc_f_068_confirmed_despite_if009_invalid(sim):
    """STC-F-068 (SWR-007) CONFIRMED는 IF-009 무효(sensor_fault 누락)와 관계없이 적용."""
    sim.s_lock()
    assert ssum(sim.send(b0(crash_status="CONFIRMED", sensor_fault=DROP))) == ex(*EMERGENCY)


def test_stc_f_069_confirmed_over_sensor_fault(sim):
    """STC-F-069 (SWR-007, SWR-021) CONFIRMED는 센서 고장(순위 2)보다 우선."""
    sim.s_lock()
    assert ssum(sim.send(b0(crash_status="CONFIRMED", sensor_fault=True))) == ex(*EMERGENCY)


def test_stc_f_070_latch_cleared_only_by_ignition_off(sim):
    """STC-F-070 (SWR-007, SWR-020) 래치는 시동 OFF에서 해제되고 이후 일반 평가로 복귀."""
    sim.s_lock()
    sim.send(b0(crash_status="CONFIRMED"))
    d = sim.send(b0(ignition_on=False))
    assert ssum(d) == ex("RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF")
    assert ssum(sim.send(b0())) == ex("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    d = sim.send(b0(command=cmd("all", "lock")))
    assert ssum(d) == ex("LOCK", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")


def test_stc_f_071_lowercase_confirmed_is_invalid(sim):
    """STC-F-071 (SWR-007, SWR-013) crash_status 'confirmed'(소문자)는 IF-002 무효, 래치 없음."""
    sim.s_lock()
    d = sim.send(b0(crash_status="confirmed"))
    assert ssum(d) == ex("LOCK", "LOCK", "DEGRADED", "DEGRADED", "INPUT_INVALID")
    assert d["input_validity"]["IF-002"] == "INVALID"
    assert ssum(sim.send(b0())) == ex("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")


# ---- SWR-008 PENDING


def test_stc_f_072_pending_notice_only_no_latch(sim):
    """STC-F-072 (SWR-008) PENDING은 출력·이유 불변, CRASH_PENDING 알림만, 래치 없음."""
    sim.s_lock()
    d = sim.send(b0(crash_status="PENDING"))
    assert ssum(d) == ex("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE", ["CRASH_PENDING"])
    assert ssum(sim.send(b0())) == ex("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    d = sim.send(b0(command=cmd("all", "unlock")))
    assert ssum(d) == ex("RELEASE", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")


def test_stc_f_073_pending_keeps_other_rules(sim):
    """STC-F-073 (SWR-008) PENDING 중에도 자동 잠금·운전자 해제 규칙이 평가됨."""
    sim.s0()
    d = sim.send(b0(crash_status="PENDING", vehicle_speed_kph=3.0))
    assert ssum(d) == ex(
        "LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ["CRASH_PENDING"]
    )
    d = sim.send(b0(crash_status="PENDING", command=cmd("all", "unlock")))
    assert ssum(d) == ex(
        "RELEASE", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK", ["CRASH_PENDING"]
    )


def test_stc_f_074_pending_to_confirmed(sim):
    """STC-F-074 (SWR-008) PENDING -> CONFIRMED 전이에서 SWR-007 동작 후 래치."""
    sim.s_lock()
    d = sim.send(b0(crash_status="PENDING"))
    assert ssum(d) == ex("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE", ["CRASH_PENDING"])
    assert ssum(sim.send(b0(crash_status="CONFIRMED"))) == ex(*EMERGENCY)
    assert ssum(sim.send(b0())) == ex(*EMERGENCY)


def test_stc_f_075_pending_notice_kept_in_tick(sim):
    """STC-F-075 (SWR-008, SWR-022) 입력 중단 후 tick 평가에서도 CRASH_PENDING 알림 유지."""
    sim.s0()
    sim.send(b0(crash_status="PENDING"))
    time.sleep(0.400)
    d = sim.status()
    assert ssum(d) == ex(
        "RELEASE", "RELEASE", "DEGRADED", "DEGRADED", "INPUT_STALE", ["CRASH_PENDING"]
    )


# ---- SWR-009 좌·우 독립


def test_stc_f_076_left_risk_does_not_affect_right_command(sim):
    """STC-F-076 (SWR-009) 왼쪽 접근위험 TRUE가 오른쪽 해제 명령 처리에 영향 없음."""
    # 파트 A(대조)
    sim.s_lock()
    d = sim.send(b0(command=cmd("right", "unlock")))
    assert ssum(d) == ex("LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    # 파트 B(시험): 서버 재기동
    with fresh_sim() as s2:
        s2.s_lock()
        d = s2.send(b0(rear_left_approach_risk=True, command=cmd("right", "unlock")))
        assert ssum(d) == ex("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_077_right_risk_does_not_affect_left_command(sim):
    """STC-F-077 (SWR-009) 오른쪽 접근위험 TRUE가 왼쪽 해제 명령 처리에 영향 없음(대칭)."""
    sim.s_lock()
    d = sim.send(b0(command=cmd("left", "unlock")))
    assert ssum(d) == ex("RELEASE", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    with fresh_sim() as s2:
        s2.s_lock()
        d = s2.send(b0(rear_right_approach_risk=True, command=cmd("left", "unlock")))
        assert ssum(d) == ex("RELEASE", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_078_left_isofix_does_not_affect_right_command(sim):
    """STC-F-078 (SWR-009, SWR-018) 왼쪽 ISOFIX TRUE가 오른쪽 해제 명령 처리에 영향 없음."""
    sim.s_lock()
    d = sim.send(b0(isofix_left=True, command=cmd("right", "unlock")))
    assert ssum(d) == ex("LOCK", "RELEASE", "NORMAL", "ISOFIX", "ISOFIX")


def test_stc_f_079_risk_and_opposite_isofix(sim):
    """STC-F-079 (SWR-009) 한쪽 접근위험과 반대쪽 ISOFIX 동시 TRUE에서 쪽별 규칙만 적용."""
    sim.s0()
    d = sim.send(b0(rear_left_approach_risk=True, isofix_right=True))
    assert ssum(d) == ex("LOCK", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    d = sim.send(b0(isofix_right=True))
    assert ssum(d) == ex("LOCK", "LOCK", "NORMAL", "ISOFIX", "ISOFIX")


# ---- SWR-010~012 결정 이력


def test_stc_f_080_every_snapshot_recorded_consecutive_ids(sim):
    """STC-F-080 (SWR-010) 모든 스냅샷 평가 기록(event_id 1..N 연속), 변화 없는 tick 미기록."""
    assert sim.events() == []
    inputs = [
        b0(),
        b0(vehicle_speed_kph=3.0),
        b0(vehicle_speed_kph=0.0),
        b0(),
        b0(crash_status="PENDING"),
    ]
    for i, raw in enumerate(inputs):
        if i:
            time.sleep(0.050)
        sim.send(raw)
    evs = sim.events()
    assert [e["event_id"] for e in evs] == [1, 2, 3, 4, 5]
    assert [ev_brief(e) for e in evs] == [
        ("RELEASE", "RELEASE", "NORMAL", "NO_CHANGE", []),
        ("LOCK", "LOCK", "NORMAL", "AUTO_LOCK_SPEED", []),
        ("LOCK", "LOCK", "NORMAL", "NO_CHANGE", []),
        ("LOCK", "LOCK", "NORMAL", "NO_CHANGE", []),
        ("LOCK", "LOCK", "NORMAL", "NO_CHANGE", ["CRASH_PENDING"]),
    ]
    time.sleep(0.120)
    assert len(sim.events()) == 5


def test_stc_f_081_changed_tick_recorded_once(sim):
    """STC-F-081 (SWR-010, SWR-022) 변화 있는 tick만 기록, 조회는 미기록, 새 스냅샷은 다음 id."""
    sim.send(b0())
    # (a) 400 ms 입력 중단
    time.sleep(0.400)
    evs = sim.events()
    assert len(evs) == 2
    e = evs[-1]
    assert (e["event_id"], e["lock_left"], e["lock_right"], e["state"]) == (
        2,
        "RELEASE",
        "RELEASE",
        "DEGRADED",
    )
    assert (e["priority_reason"], e["reason_code"]) == ("DEGRADED", "INPUT_STALE")
    # (b) 1 s 추가 대기
    time.sleep(1.0)
    assert len(sim.events()) == 2
    # (c) 상태 조회 10회
    for _ in range(10):
        sim.status()
    assert len(sim.events()) == 2
    # (d) B0 전송
    sim.send(b0())
    evs = sim.events()
    assert len(evs) == 3
    assert (evs[-1]["event_id"], evs[-1]["state"]) == (3, "NORMAL")


def test_stc_f_082_event_fields_exact(sim):
    """STC-F-082 (SWR-011) 결정 이벤트 필드는 허용 8개와 정확히 같고 timestamp_s는 평가 시각."""
    d = sim.send(b0(crash_status="PENDING"))
    time.sleep(0.400)
    evs = sim.events()
    assert len(evs) == 2
    for e in evs:
        assert set(e) == EVENT_KEYS
    assert evs[0]["notices"] == ["CRASH_PENDING"]
    assert evs[0]["timestamp_s"] == d["timestamp_s"]
    assert (evs[1]["state"], evs[1]["reason_code"]) == ("DEGRADED", "INPUT_STALE")


def _send_b0_times(s: Simulator, count: int) -> None:
    for _ in range(count):
        s.send(b0())


def test_stc_f_083_retention_100_oldest_first(tmp_path):
    """STC-F-083 (SWR-012) 100건 보존, 오래된 것부터 삭제, 오래된 순 조회, 파일 생성 없음."""
    # 서버 작업 디렉터리를 빈 임시 디렉터리로 지정해 실행 중 파일 생성을 관찰한다
    s = CwdSimulator(tmp_path)
    try:
        before = file_list(tmp_path)
        _send_b0_times(s, 100)
        assert [e["event_id"] for e in s.events()] == list(range(1, 101))
        _send_b0_times(s, 1)
        assert [e["event_id"] for e in s.events()] == list(range(2, 102))
        _send_b0_times(s, 5)
        assert [e["event_id"] for e in s.events()] == list(range(7, 107))
    finally:
        s.stop()
    assert file_list(tmp_path) == before


def test_stc_f_084_no_history_after_restart(tmp_path):
    """STC-F-084 (SWR-012) 프로세스 재기동 후 이력 없음(영속 저장 없음)."""
    # 사전조건: 직전 케이스(083)처럼 이벤트 106건을 만든 상태를 이 시험 안에서 재현
    s = CwdSimulator(tmp_path)
    try:
        _send_b0_times(s, 106)
        assert len(s.events()) == 100
    finally:
        s.stop()
    # 같은 작업 디렉터리·같은 명령으로 재기동(포트는 시험 환경에서 빈 포트를 사용)
    s = CwdSimulator(tmp_path)
    try:
        assert s.events() == []
        s.send(b0())
        evs = s.events()
        assert [e["event_id"] for e in evs] == [1]
    finally:
        s.stop()


# ---- SWR-013 IF-001 검증


def _if001(d: dict[str, object]) -> object:
    return d["input_validity"]["IF-001"]


NO_CHANGE = ("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")


def test_stc_f_085_speed_lower_bound(sim):
    """STC-F-085 (SWR-013) 차속 0.0은 유효, -0.1은 IF-001 무효(DEGRADED 아님)."""
    sim.s0()
    d = sim.send(b0(vehicle_speed_kph=0.0))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "VALID"
    d = sim.send(b0(vehicle_speed_kph=-0.1))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "INVALID"


def test_stc_f_086_speed_upper_bound(sim):
    """STC-F-086 (SWR-013, SWR-003) 차속 300.1은 무효로 자동 잠금 없음, 300.0은 유효로 자동 잠금."""
    sim.s0()
    d = sim.send(b0(vehicle_speed_kph=300.1))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "INVALID"
    d = sim.send(b0(vehicle_speed_kph=300.0))
    assert ssum(d) == ex("LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED")
    assert _if001(d) == "VALID"


def test_stc_f_087_speed_bool_invalid(sim):
    """STC-F-087 (SWR-013) 차속 bool true는 IF-001 무효로 자동 잠금에 쓰이지 않음."""
    sim.s0()
    d = sim.send(b0(vehicle_speed_kph=True))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "INVALID"


def test_stc_f_088_speed_string_invalid(sim):
    """STC-F-088 (SWR-013) 차속 문자열 "50"은 IF-001 무효로 자동 잠금에 쓰이지 않음."""
    sim.s0()
    d = sim.send(b0(vehicle_speed_kph="50"))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "INVALID"


def test_stc_f_089_speed_missing_invalid(sim):
    """STC-F-089 (SWR-013) 차속 누락은 IF-001 무효로 자동 잠금에 쓰이지 않음."""
    sim.s0()
    d = sim.send(b0(vehicle_speed_kph=DROP))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "INVALID"


def test_stc_f_090_unknown_gear_invalidates_group(sim):
    """STC-F-090 (SWR-013) gear 'd'(미등록)이면 IF-001 그룹 전체 무효로 차속 50도 쓰이지 않음."""
    sim.s0()
    d = sim.send(b0(gear="d", vehicle_speed_kph=50.0))
    assert ssum(d) == ex(*NO_CHANGE)
    assert _if001(d) == "INVALID"
