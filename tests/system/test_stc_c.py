"""!
@brief SW 시스템 시험(SWE.6) STC-F-091 ~ STC-F-130 자동화.

케이스 정의: docs/06_system_test/system_test_cases.json.
케이스 1건 = 시험 함수 1개. 단계별 기대값은 케이스의 "예상 출력값"을 그대로 옮긴다.
notices는 케이스 공통 합격 기준에 따라 집합(순서 무관)으로 비교한다.
"""

import http.client
import json
import math
import os
import random
import time

from tests.system.harness import DROP, Simulator, b0, cmd, expect, summary

## input_validity 키 8종 (SWR-014)
VALIDITY_KEYS = {"IF-001", "IF-002", "IF-003", "IF-004", "IF-007", "IF-008", "IF-009", "FRESHNESS"}
## 상태 응답 키 8종 (SWR-014)
STATUS_KEYS = {
    "lock_left",
    "lock_right",
    "state",
    "input_validity",
    "priority_reason",
    "reason_code",
    "notices",
    "timestamp_s",
}
## 이벤트 원소 키 8종 (SWR-012)
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


def judge(d: dict[str, object]) -> dict[str, object]:
    """판정 JSON의 비교 필드를 뽑고 notices를 집합 비교용으로 정렬한다."""
    r = summary(d)
    r["notices"] = sorted(r["notices"])
    return r


def want(
    lock_left: str,
    lock_right: str,
    state: str,
    priority_reason: str,
    reason_code: str,
    notices: list[str] | None = None,
) -> dict[str, object]:
    """기대 판정(notices 정렬, judge와 같은 형식)."""
    e = expect(lock_left, lock_right, state, priority_reason, reason_code, notices)
    e["notices"] = sorted(e["notices"])
    return e


def codes(d: dict[str, object]) -> tuple[object, object]:
    """(priority_reason, reason_code)만 뽑는다."""
    return d["priority_reason"], d["reason_code"]


def round_half_up_ms(seconds: float) -> int:
    """초 단위 시간을 ms 정수로 반올림한다(SWRS DEF-04, 0.5 올림, 부동소수 오차 정리)."""
    return math.floor(round(seconds * 1000, 6) + 0.5)


def request_full(
    sim: Simulator,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str, bytes]:
    """요청을 보내고 (상태 코드, Content-Type, 본문)을 돌려준다(헤더 확인용)."""
    conn = http.client.HTTPConnection("127.0.0.1", sim.port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type") or "", resp.read()
    finally:
        conn.close()


def without_ts(d: dict[str, object]) -> dict[str, object]:
    """timestamp_s를 뺀 상태(조회 결과 비교용)."""
    return {k: v for k, v in d.items() if k != "timestamp_s"}


def env_runs(name: str, default: int) -> int:
    """반복 횟수를 환경 변수로 바꿀 수 있게 한다(기본값 = 케이스 사양)."""
    return int(os.environ.get(name, str(default)))


NORMAL_LOCK = want("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
DEGRADED_INVALID_LOCK = want("LOCK", "LOCK", "DEGRADED", "DEGRADED", "INPUT_INVALID")
DEGRADED_STALE_LOCK = want("LOCK", "LOCK", "DEGRADED", "DEGRADED", "INPUT_STALE")


# ---- SWR-013 입력 검증


def test_stc_f_091_gear_values_do_not_affect_output(sim):
    """STC-F-091 (SWR-013) gear 유효 값 P/N/D/R 모두 유효이고 출력에 영향 없음(차속 0.0)."""
    sim.s0()
    for i, gear in enumerate(("P", "N", "D", "R")):
        if i:
            time.sleep(0.05)  # 각 전송 사이 50 ms
        d = sim.send(b0(gear=gear))
        assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE"), gear
        assert d["input_validity"]["IF-001"] == "VALID", gear


def test_stc_f_092_crash_status_missing_is_degraded(sim):
    """STC-F-092 (SWR-013) IF-002 누락이면 DEGRADED, 직전 출력(LOCK) 유지."""
    sim.s_lock()
    d = sim.send(b0(crash_status=DROP))
    assert judge(d) == DEGRADED_INVALID_LOCK
    assert d["input_validity"]["IF-002"] == "INVALID"


def test_stc_f_093_crash_status_integer_is_degraded(sim):
    """STC-F-093 (SWR-013) IF-002가 정수 2(문자열 아님)이면 DEGRADED, 직전 출력 유지."""
    sim.s_lock()
    d = sim.send(b0(crash_status=2))
    assert judge(d) == DEGRADED_INVALID_LOCK
    assert d["input_validity"]["IF-002"] == "INVALID"


def test_stc_f_094_approach_group_one_field_invalid(sim):
    """STC-F-094 (SWR-013) IF-003 한쪽만 무효('yes')이면 그룹 전체 무효로 오른쪽 TRUE도 미사용."""
    sim.s0()
    d = sim.send(b0(rear_left_approach_risk="yes", rear_right_approach_risk=True))
    assert judge(d) == want("RELEASE", "RELEASE", "DEGRADED", "DEGRADED", "INPUT_INVALID")
    assert d["input_validity"]["IF-003"] == "INVALID"


def test_stc_f_095_approach_group_one_field_missing(sim):
    """STC-F-095 (SWR-013) IF-003 오른쪽 누락이면 그룹 전체 무효로 왼쪽 TRUE도 미사용."""
    sim.s0()
    d = sim.send(b0(rear_left_approach_risk=True, rear_right_approach_risk=DROP))
    assert judge(d) == want("RELEASE", "RELEASE", "DEGRADED", "DEGRADED", "INPUT_INVALID")
    assert d["input_validity"]["IF-003"] == "INVALID"


def test_stc_f_096_sensor_fault_missing_ignores_ignition_off(sim):
    """STC-F-096 (SWR-013) IF-009 무효(sensor_fault 누락)이면 시동 OFF 해제 없이 DEGRADED."""
    sim.s_lock()
    d = sim.send(b0(ignition_on=False, sensor_fault=DROP))
    assert judge(d) == DEGRADED_INVALID_LOCK
    assert d["input_validity"]["IF-009"] == "INVALID"


def test_stc_f_097_ignition_string_ignores_sensor_fault(sim):
    """STC-F-097 (SWR-013) IF-009 무효(ignition_on='on')이면 sensor_fault=true 미사용, DEGRADED."""
    sim.s0()
    d = sim.send(b0(ignition_on="on", sensor_fault=True))
    assert judge(d) == want("RELEASE", "RELEASE", "DEGRADED", "DEGRADED", "INPUT_INVALID")
    assert d["input_validity"]["IF-009"] == "INVALID"


def test_stc_f_098_overtemp_missing_disables_fire_group(sim):
    """STC-F-098 (SWR-013) IF-007 무효면 DEGRADED 아님, fire=true도 미사용으로 해제 없음."""
    sim.s_lock()
    d = sim.send(b0(fire_detected=True, overtemperature_detected=DROP))
    assert judge(d) == NORMAL_LOCK
    assert d["input_validity"]["IF-007"] == "INVALID"


def test_stc_f_099_isofix_left_missing_disables_isofix_group(sim):
    """STC-F-099 (SWR-013) IF-008 무효면 DEGRADED 아님, isofix_right=true도 미사용."""
    sim.s0()
    d = sim.send(b0(isofix_left=DROP, isofix_right=True))
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    assert d["input_validity"]["IF-008"] == "INVALID"


def test_stc_f_100_stale_boundary_200_201_ms(sim):
    """STC-F-100 (SWR-013) 지연 200 ms 이하 정상, 201 ms 이상 STALE(응답 시각으로 사후 판정)."""
    max_runs = env_runs("STC_F_100_RUNS", 200)
    sim.s_lock()
    delays = (0.190, 0.195, 0.198, 0.199, 0.200)
    records: list[tuple[int, dict[str, object], str]] = []
    n200 = n201 = 0
    for i in range(max_runs):
        if i:
            sim.send(b0())  # 시도 사이 정상 B0(ts 생략)로 NORMAL 복귀
        t = sim.now()
        src = t - delays[i % len(delays)]
        d = sim.send(b0(source_timestamp_s=src))
        age_ms = round_half_up_ms(float(d["timestamp_s"]) - src)
        records.append((age_ms, judge(d), d["input_validity"]["FRESHNESS"]))
        n200 += age_ms == 200
        n201 += age_ms == 201
        if n200 >= 3 and n201 >= 3:
            break
    # 표본 판정: 모든 표본이 age_ms에 따른 예상과 일치해야 한다
    for age_ms, got, fresh in records:
        if age_ms <= 200:
            assert (got, fresh) == (NORMAL_LOCK, "VALID"), (age_ms, got, fresh)
        else:
            assert (got, fresh) == (DEGRADED_STALE_LOCK, "STALE"), (age_ms, got, fresh)
    # 서버 시계 해상도가 거칠면(예: Windows time.monotonic 15.625 ms) 응답 시각이 T와 같거나
    # 한 눈금 뒤가 되어 age_ms=201 표본이 나오지 않을 수 있다. 이 경우 시험 불성립으로 판정한다.
    assert n200 >= 3 and n201 >= 3, (
        f"시험 불성립: 표본 부족(age_ms=200 {n200}건, 201 {n201}건, 시도 {len(records)}회)"
    )


def test_stc_f_101_stale_rounding_half_ms(sim):
    """STC-F-101 (SWR-013) 반올림(DEF-04): 200.0~200.5 ms는 정상, 200.5~201.0 ms는 STALE."""
    max_runs = env_runs("STC_F_101_RUNS", 500)
    rng = random.Random()
    sim.s_lock()
    low: list[tuple[float, dict[str, object], str]] = []
    high: list[tuple[float, dict[str, object], str]] = []
    tried = 0
    for i in range(max_runs):
        if i:
            sim.send(b0())  # 시도 사이 정상 B0로 복귀
        t = sim.now()
        src = t - rng.uniform(0.1985, 0.2005)
        d = sim.send(b0(source_timestamp_s=src))
        tried += 1
        age_s = round(float(d["timestamp_s"]) - src, 6)
        sample = (age_s, judge(d), d["input_validity"]["FRESHNESS"])
        # 0.2005 정확 경계와 두 구간 밖 표본은 판정 제외
        if 0.2000 < age_s < 0.2005:
            low.append(sample)
        elif 0.2005 < age_s < 0.2010:
            high.append(sample)
        if len(low) >= 3 and len(high) >= 3:
            break
    for age_s, got, fresh in low:
        assert (got["state"], fresh) == ("NORMAL", "VALID"), (age_s, got, fresh)
    for age_s, got, fresh in high:
        assert (got["state"], got["reason_code"], fresh) == ("DEGRADED", "INPUT_STALE", "STALE"), (
            age_s,
            got,
            fresh,
        )
    assert len(low) >= 3 and len(high) >= 3, (
        f"시험 불성립: 표본 부족((0.2000,0.2005) {len(low)}건, (0.2005,0.2010) {len(high)}건, "
        f"시도 {tried}회)"
    )


def test_stc_f_102_future_timestamp_is_stale(sim):
    """STC-F-102 (SWR-013) source_timestamp_s가 미래(T+10 s)이면 STALE(DEGRADED)."""
    sim.s_lock()
    t = sim.now()
    d = sim.send(b0(source_timestamp_s=t + 10.0))
    assert judge(d) == DEGRADED_STALE_LOCK
    assert d["input_validity"]["FRESHNESS"] == "STALE"


def test_stc_f_103_negative_timestamp_is_stale(sim):
    """STC-F-103 (SWR-013) source_timestamp_s가 음수(-1.0)이면 STALE(DEGRADED)."""
    sim.s_lock()
    d = sim.send(b0(source_timestamp_s=-1.0))
    assert judge(d) == DEGRADED_STALE_LOCK
    assert d["input_validity"]["FRESHNESS"] == "STALE"


def test_stc_f_104_string_timestamp_is_stale(sim):
    """STC-F-104 (SWR-013) source_timestamp_s가 문자열('now')이면 STALE(DEGRADED)."""
    sim.s_lock()
    d = sim.send(b0(source_timestamp_s="now"))
    assert judge(d) == DEGRADED_STALE_LOCK
    assert d["input_validity"]["FRESHNESS"] == "STALE"


def test_stc_f_105_omitted_timestamp_is_valid(sim):
    """STC-F-105 (SWR-013) source_timestamp_s 생략 시 서버 시각으로 채워 VALID."""
    sim.s_lock()
    d = sim.send(b0())
    assert judge(d) == NORMAL_LOCK
    assert d["input_validity"]["FRESHNESS"] == "VALID"


def test_stc_f_106_invalid_and_stale_reports_input_invalid(sim):
    """STC-F-106 (SWR-013) 안전 입력 무효와 지연 동시면 INPUT_INVALID 우선, 두 유효성 표시."""
    sim.s_lock()
    t = sim.now()
    d = sim.send(b0(crash_status=DROP, source_timestamp_s=t - 0.300))
    assert judge(d) == DEGRADED_INVALID_LOCK
    assert d["input_validity"]["IF-002"] == "INVALID"
    assert d["input_validity"]["FRESHNESS"] == "STALE"


def test_stc_f_107_recovery_from_invalid_and_stale(sim):
    """STC-F-107 (SWR-013) 안전 입력 이상(무효, 지연) 해소 시 정상 복귀, 직전 출력 유지."""
    sim.s_lock()
    assert judge(sim.send(b0(crash_status=DROP))) == DEGRADED_INVALID_LOCK  # (a)
    assert judge(sim.send(b0())) == NORMAL_LOCK  # (b)
    t = sim.now()
    assert judge(sim.send(b0(source_timestamp_s=t - 0.300))) == DEGRADED_STALE_LOCK  # (c)
    assert judge(sim.send(b0())) == NORMAL_LOCK  # (d)


def test_stc_f_108_approach_risk_applies_during_degraded(sim):
    """STC-F-108 (SWR-013) DEGRADED 중에도 접근위험 TRUE는 해당 쪽 LOCK, 반대쪽 유지."""
    sim.s0()
    d = sim.send(b0(crash_status=DROP, rear_left_approach_risk=True))
    assert judge(d) == want("LOCK", "RELEASE", "DEGRADED", "APPROACH_RISK", "APPROACH_RISK")
    assert d["input_validity"]["IF-002"] == "INVALID"


def test_stc_f_109_release_rules_blocked_during_degraded(sim):
    """STC-F-109 (SWR-013) DEGRADED 중 시동 OFF·화재 해제 미적용, 직전 LOCK 유지."""
    sim.s_lock()
    assert judge(sim.send(b0(crash_status=DROP, ignition_on=False))) == DEGRADED_INVALID_LOCK
    assert judge(sim.send(b0(crash_status=DROP, fire_detected=True))) == DEGRADED_INVALID_LOCK


def test_stc_f_110_lock_rules_blocked_during_degraded(sim):
    """STC-F-110 (SWR-013) DEGRADED 중 차속·ISOFIX·잠금 명령 미적용, 직전 RELEASE 유지."""
    sim.s0()
    exp = want("RELEASE", "RELEASE", "DEGRADED", "DEGRADED", "INPUT_INVALID")
    assert judge(sim.send(b0(crash_status=DROP, vehicle_speed_kph=3.0))) == exp  # (a)
    assert judge(sim.send(b0(crash_status=DROP, isofix_left=True))) == exp  # (b)
    assert judge(sim.send(b0(crash_status=DROP, command=cmd("all", "lock")))) == exp  # (c)


# ---- SWR-014 출력 형식


def test_stc_f_111_status_before_any_snapshot(sim):
    """STC-F-111 (SWR-014) 스냅샷 수신 전 상태 조회: 필드 완비, 초기값, timestamp_s 증가."""
    first = sim.status()
    time.sleep(0.1)
    second = sim.status()
    for d in (first, second):
        assert set(d) >= STATUS_KEYS, d
        assert judge(d) == want("RELEASE", "RELEASE", "OFF", "NONE", "NO_CHANGE")
        assert set(d["input_validity"]) == VALIDITY_KEYS, d["input_validity"]
        assert all(v in ("VALID", "INVALID", "STALE") for v in d["input_validity"].values())
    assert second["timestamp_s"] > first["timestamp_s"]


def test_stc_f_112_status_matches_post_after_evaluation(sim):
    """STC-F-112 (SWR-014) 평가 후 상태 조회가 형식에 맞고 POST 응답과 같은 내용."""
    sim.s0()
    posted = sim.send(b0(crash_status="PENDING"))
    got = sim.status()
    assert judge(got) == want(
        "RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE", ["CRASH_PENDING"]
    )
    assert isinstance(got["notices"], list)
    assert got["input_validity"] == {k: "VALID" for k in VALIDITY_KEYS}
    assert judge(got) == judge(posted)


def test_stc_f_113_reason_code_mapping_decision_table(sim):
    """STC-F-113 (SWR-014) 이유 코드와 priority_reason 매핑(12개 상황 순서 주입)."""
    sim.send(b0())  # 사전조건: 신규 기동 후 B0 1건
    # 이 케이스는 두 코드 필드만 판정한다(그 밖의 필드는 각 전용 케이스에서 판정).
    steps = [
        (b0(vehicle_speed_kph=3.0), ("AUTO_LOCK", "AUTO_LOCK_SPEED")),
        (b0(command=cmd("all", "unlock")), ("DRIVER_COMMAND", "DRIVER_UNLOCK")),
        (b0(command=cmd("all", "lock")), ("DRIVER_COMMAND", "DRIVER_LOCK")),
        (b0(isofix_left=True), ("ISOFIX", "ISOFIX")),
        (b0(fire_detected=True), ("FORCED_RELEASE", "FIRE")),
        (b0(overtemperature_detected=True), ("FORCED_RELEASE", "OVERTEMP")),
        (b0(adult_present=True), ("FORCED_RELEASE", "ADULT_PRESENT")),
        (b0(rear_left_approach_risk=True), ("APPROACH_RISK", "APPROACH_RISK")),
        (b0(ignition_on=False), ("IGNITION_OFF", "IGNITION_OFF")),
        (b0(crash_status=DROP), ("DEGRADED", "INPUT_INVALID")),
        (b0(sensor_fault=True), ("SENSOR_FAULT", "W_SENSOR_FAULT")),
        (b0(crash_status="CONFIRMED"), ("CRASH", "CRASH_CONFIRMED")),
    ]
    for no, (raw, exp) in enumerate(steps, start=1):
        time.sleep(0.05)  # 단계 사이 50 ms
        assert codes(sim.send(raw)) == exp, f"{no}단계"


# ---- SWR-015 HTTP 인터페이스


def test_stc_f_114_endpoints_respond_with_correct_format(sim):
    """STC-F-114 (SWR-015) 4개 엔드포인트가 200과 올바른 JSON/HTML 형식으로 응답."""
    sim.s0()
    status, ctype, _ = request_full(sim, "GET", "/")
    assert status == 200 and ctype.startswith("text/html"), (status, ctype)

    status, _, body = request_full(sim, "GET", "/api/status")
    data = json.loads(body)
    assert status == 200 and isinstance(data, dict)
    assert set(data) == STATUS_KEYS, sorted(data)

    status, _, body = request_full(sim, "GET", "/api/events")
    data = json.loads(body)
    assert status == 200 and isinstance(data, list)
    for ev in data:
        assert set(ev) == EVENT_KEYS, sorted(ev)

    status, _, body = request_full(
        sim,
        "POST",
        "/api/snapshot",
        json.dumps(b0()).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    data = json.loads(body)
    assert status == 200 and isinstance(data, dict)
    assert set(data) == STATUS_KEYS, sorted(data)


def check_rejected_body_keeps_state(sim: Simulator, body: bytes) -> None:
    """S-LOCK 후 잘못된 본문이 400이고 이력 건수·상태가 변하지 않음을 확인한다(STC-F-115/116)."""
    sim.s_lock()
    n = len(sim.events())
    before = sim.status()
    status, _ = sim.request_raw("POST", "/api/snapshot", body)
    assert status == 400
    assert len(sim.events()) == n
    after = sim.status()
    assert (after["lock_left"], after["lock_right"], after["state"]) == ("LOCK", "LOCK", "NORMAL")
    assert without_ts(after) == without_ts(before)


def test_stc_f_115_non_json_text_body_is_400(sim):
    """STC-F-115 (SWR-015) JSON이 아닌 텍스트 본문(abc)은 400, 상태·이력 불변."""
    check_rejected_body_keeps_state(sim, b"abc")


def test_stc_f_116_empty_body_is_400(sim):
    """STC-F-116 (SWR-015) 빈 본문(0 바이트)은 400, 상태·이력 불변."""
    check_rejected_body_keeps_state(sim, b"")


def check_rejected_after_s0(sim: Simulator, body: bytes) -> None:
    """S0 후 본문이 400으로 거절되고 이벤트 건수가 그대로인지 확인한다(STC-F-117/118)."""
    sim.s0()
    n = len(sim.events())
    status, _ = sim.request_raw("POST", "/api/snapshot", body)
    assert status == 400
    assert len(sim.events()) == n


def test_stc_f_117_nan_literal_body_is_400(sim):
    """STC-F-117 (SWR-015) NaN 리터럴을 포함한 본문은 400으로 거절."""
    check_rejected_after_s0(sim, b'{"vehicle_speed_kph": NaN, "gear": "P"}')


def test_stc_f_118_top_level_array_is_400(sim):
    """STC-F-118 (SWR-015) 최상위가 배열([])인 JSON은 400으로 거절."""
    check_rejected_after_s0(sim, b"[]")


# ---- SWR-017 강제 해제


def test_stc_f_119_fire_releases_both(sim):
    """STC-F-119 (SWR-017) 화재 단독이면 같은 평가에 좌·우 RELEASE, 이유 FIRE."""
    sim.s_lock()
    d = sim.send(b0(fire_detected=True))
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", "FIRE")


def test_stc_f_120_overtemp_releases_both(sim):
    """STC-F-120 (SWR-017) 과열 단독이면 같은 평가에 좌·우 RELEASE, 이유 OVERTEMP."""
    sim.s_lock()
    d = sim.send(b0(overtemperature_detected=True))
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", "OVERTEMP")


def test_stc_f_121_adult_present_releases_both(sim):
    """STC-F-121 (SWR-017) 성인 존재 단독이면 같은 평가에 좌·우 RELEASE, 이유 ADULT_PRESENT."""
    sim.s_lock()
    d = sim.send(b0(adult_present=True))
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", "ADULT_PRESENT")


def test_stc_f_122_forced_release_reason_priority(sim):
    """STC-F-122 (SWR-017) 동시 TRUE 시 이유 코드 FIRE > OVERTEMP > ADULT_PRESENT."""
    sim.s_lock()
    steps = [
        (b0(overtemperature_detected=True, adult_present=True), "OVERTEMP"),  # (a)
        (b0(fire_detected=True, overtemperature_detected=True), "FIRE"),  # (b)
        (b0(fire_detected=True, adult_present=True), "FIRE"),  # (c)
        (
            b0(fire_detected=True, overtemperature_detected=True, adult_present=True),
            "FIRE",
        ),  # (d)
    ]
    for raw, reason in steps:
        d = sim.send(raw)
        assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", reason), reason


def test_stc_f_123_lock_command_ignored_during_forced_release(sim):
    """STC-F-123 (SWR-017) 강제 해제 중 잠금 명령 무시, 해소 후 재잠금 없음, 차속 3.0에서만 잠금."""
    sim.s0()
    d = sim.send(b0(fire_detected=True, command=cmd("all", "lock")))  # (a)
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", "FIRE")
    d = sim.send(b0())  # (b)
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    d = sim.send(b0(vehicle_speed_kph=3.0))  # (c)
    assert judge(d) == want("LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED")


# ---- SWR-018 ISOFIX


def test_stc_f_124_isofix_left_locks_left_only(sim):
    """STC-F-124 (SWR-018) 왼쪽 ISOFIX TRUE면 왼쪽만 LOCK, FALSE가 되어도 자동 해제 없음."""
    sim.s0()
    d = sim.send(b0(isofix_left=True))  # (a)
    assert judge(d) == want("LOCK", "RELEASE", "NORMAL", "ISOFIX", "ISOFIX")
    d = sim.send(b0())  # (b)
    assert judge(d) == want("LOCK", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")


def test_stc_f_125_isofix_right_locks_right_keeps_left(sim):
    """STC-F-125 (SWR-018) 오른쪽 ISOFIX TRUE면 오른쪽만 LOCK, 왼쪽 LOCK 유지(매핑 교차 검출)."""
    sim.s_mix()
    d = sim.send(b0(isofix_right=True))
    assert judge(d) == want("LOCK", "LOCK", "NORMAL", "ISOFIX", "ISOFIX")


def test_stc_f_126_unlock_rejected_while_isofix(sim):
    """STC-F-126 (SWR-018) 양쪽 ISOFIX TRUE 동안 해제 명령 거절, FALSE 이후 해제 허용."""
    sim.s0()
    d = sim.send(b0(isofix_left=True, isofix_right=True))  # (a)
    assert judge(d) == want("LOCK", "LOCK", "NORMAL", "ISOFIX", "ISOFIX")
    d = sim.send(b0(isofix_left=True, isofix_right=True, command=cmd("all", "unlock")))  # (b)
    assert judge(d) == want(
        "LOCK", "LOCK", "NORMAL", "ISOFIX", "ISOFIX", ["DRIVER_UNLOCK_REJECTED"]
    )
    d = sim.send(b0())  # (c)
    assert judge(d) == want("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    d = sim.send(b0(command=cmd("all", "unlock")))  # (d)
    assert judge(d) == want("RELEASE", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")


# ---- SWR-019 우선순위 조합 (PICT 행)


def test_stc_f_127_pict_crash_over_fault_stale_ignition(sim):
    """STC-F-127 (SWR-019) PICT 행: 충돌 확정이 센서 고장·지연·시동 OFF보다 우선."""
    sim.s_lock()
    t = sim.now()
    d = sim.send(
        b0(
            crash_status="CONFIRMED",
            sensor_fault=True,
            source_timestamp_s=t - 0.300,
            ignition_on=False,
        )
    )
    assert judge(d) == want("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")


def test_stc_f_128_pict_approach_over_fire_speed_command(sim):
    """STC-F-128 (SWR-019) PICT 행: 접근위험이 화재·차속·잠금 명령보다 우선."""
    sim.s0()
    d = sim.send(
        b0(
            rear_left_approach_risk=True,
            fire_detected=True,
            vehicle_speed_kph=3.0,
            command=cmd("all", "lock"),
        )
    )
    assert judge(d) == want("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")


def test_stc_f_129_pict_crash_over_ignition_isofix_command(sim):
    """STC-F-129 (SWR-019) PICT 행: 충돌 확정이 시동 OFF·ISOFIX·잠금 명령보다 우선."""
    sim.s0()
    d = sim.send(
        b0(
            crash_status="CONFIRMED",
            ignition_on=False,
            isofix_left=True,
            command=cmd("all", "lock"),
        )
    )
    assert judge(d) == want("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")


def test_stc_f_130_pict_sensor_fault_over_all_lower(sim):
    """STC-F-130 (SWR-019) PICT 행: 센서 고장이 접근위험·지연·시동 OFF·화재 등 하위보다 우선."""
    sim.s_lock()
    t = sim.now()
    d = sim.send(
        b0(
            sensor_fault=True,
            rear_left_approach_risk=True,
            source_timestamp_s=t - 0.300,
            ignition_on=False,
            fire_detected=True,
            isofix_left=True,
            vehicle_speed_kph=3.0,
        )
    )
    assert judge(d) == want("LOCK", "LOCK", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT")
