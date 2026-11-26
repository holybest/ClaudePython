"""!
@brief SW 시스템 시험(SWE.6) STC-F-002 ~ STC-F-045 자동화.

케이스 1건 = 시험 함수 1개. 단계별 기대값은 docs/06_system_test/system_test_cases.json의
"예상 출력값"을 그대로 옮긴다.

공통 해석:
- notices는 케이스 합격 기준에 따라 집합으로 비교한다(정렬 후 비교, 지역 도우미 judge/exp).
- 절차 "응답과 직후 GET /api/status 확인": 상태 조회는 tick 평가 1회(SWR-022)라서
  priority_reason·reason_code·notices가 스냅샷 평가 응답과 달라질 수 있다(명령 1회성).
  따라서 예상 출력 전체는 POST 응답으로 판정하고, 직후 상태 조회는 출력(lock_left,
  lock_right)과 state가 응답과 같은지만 확인한다(check_status_follows).
- input_validity.* 기대값은 응답의 input_validity 맵에서 해당 키를 정확히 비교한다.
"""

import time

from tests.system.harness import DROP, Simulator, b0, cmd, expect, floor_ms, summary

## 응답 시각 - 기준 시각 허용 상한(케이스 044·045의 유효 시도 조건, 초)
VALID_AGE_S = 0.190

## 타이밍 조건 미충족 시 재시험 최대 횟수(케이스 044·045 "아니면 재시험")
MAX_ATTEMPTS = 3


# ---- 지역 도우미


def judge(d: dict[str, object]) -> dict[str, object]:
    """판정 JSON의 비교 필드를 뽑고 notices를 정렬한다(집합 비교)."""
    s = summary(d)
    notices = s["notices"]
    assert isinstance(notices, list)
    s["notices"] = sorted(notices)
    return s


def exp(
    lock_left: str,
    lock_right: str,
    state: str,
    priority_reason: str,
    reason_code: str,
    notices: list[str] | None = None,
) -> dict[str, object]:
    """기대 판정을 만든다(notices 정렬, judge와 같은 형식)."""
    e = expect(lock_left, lock_right, state, priority_reason, reason_code, notices)
    e["notices"] = sorted(e["notices"])
    return e


def check_status_follows(sim: Simulator, d: dict[str, object]) -> None:
    """직후 GET /api/status의 출력과 state가 응답과 같은지 확인한다."""
    st = sim.status()
    keys = ("lock_left", "lock_right", "state")
    assert {k: st[k] for k in keys} == {k: d[k] for k in keys}


def validity(d: dict[str, object], key: str) -> object:
    """응답의 input_validity에서 key 값을 꺼낸다."""
    iv = d["input_validity"]
    assert isinstance(iv, dict)
    return iv[key]


## 명령 거절 기대값(S-MIX 유지, COMMAND_REJECTED)
REJECTED_MIX = exp("LOCK", "RELEASE", "NORMAL", "NONE", "NO_CHANGE", ["COMMAND_REJECTED"])


def run_single(
    sim: Simulator, pre: str, raw: dict[str, object], want: dict[str, object]
) -> dict[str, object]:
    """사전조건 수행 → 입력 1건 전송 → 응답 판정 → 직후 상태 조회 확인."""
    getattr(sim, pre)()
    d = sim.send(raw)
    assert judge(d) == want
    check_status_follows(sim, d)
    return d


def run_rejected_mix(sim: Simulator, command: object) -> None:
    """SWR-002 명령 거절 공통 절차(S-MIX, IF-004 INVALID, IF-001 VALID)."""
    d = run_single(sim, "s_mix", b0(command=command), REJECTED_MIX)
    assert validity(d, "IF-004") == "INVALID"
    assert validity(d, "IF-001") == "VALID"


# ---- SWR-001 명령 조합 (PICT)


def test_stc_f_002_all_unlock_via_voice(sim):
    """STC-F-002 (SWR-001) voice 경로 all unlock은 좌·우 모두 해제."""
    want = exp("RELEASE", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    run_single(sim, "s_lock", b0(command=cmd("all", "unlock", "voice")), want)


def test_stc_f_003_all_lock_via_mobile_app(sim):
    """STC-F-003 (SWR-001) mobile_app 경로 all lock은 좌·우 모두 잠금."""
    want = exp("LOCK", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")
    run_single(sim, "s0", b0(command=cmd("all", "lock", "mobile_app")), want)


def test_stc_f_004_left_unlock_via_avn(sim):
    """STC-F-004 (SWR-001) avn 경로 left unlock은 왼쪽만 해제."""
    want = exp("RELEASE", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    run_single(sim, "s_lock", b0(command=cmd("left", "unlock", "avn")), want)


def test_stc_f_005_all_unlock_via_physical_button(sim):
    """STC-F-005 (SWR-001) physical_button 경로 all unlock은 좌·우 모두 해제."""
    want = exp("RELEASE", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    run_single(sim, "s_lock", b0(command=cmd("all", "unlock", "physical_button")), want)


def test_stc_f_006_right_unlock_via_mobile_app(sim):
    """STC-F-006 (SWR-001) mobile_app 경로 right unlock은 오른쪽만 해제."""
    want = exp("LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    run_single(sim, "s_lock", b0(command=cmd("right", "unlock", "mobile_app")), want)


def test_stc_f_007_all_lock_via_avn(sim):
    """STC-F-007 (SWR-001) avn 경로 all lock은 좌·우 모두 잠금."""
    want = exp("LOCK", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")
    run_single(sim, "s0", b0(command=cmd("all", "lock", "avn")), want)


def test_stc_f_008_left_lock_via_mobile_app(sim):
    """STC-F-008 (SWR-001) mobile_app 경로 left lock은 왼쪽만 잠금."""
    want = exp("LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")
    run_single(sim, "s0", b0(command=cmd("left", "lock", "mobile_app")), want)


def test_stc_f_009_left_lock_via_voice(sim):
    """STC-F-009 (SWR-001) voice 경로 left lock은 왼쪽만 잠금."""
    want = exp("LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")
    run_single(sim, "s0", b0(command=cmd("left", "lock", "voice")), want)


def test_stc_f_010_right_unlock_via_voice(sim):
    """STC-F-010 (SWR-001) voice 경로 right unlock은 오른쪽만 해제."""
    want = exp("LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    run_single(sim, "s_lock", b0(command=cmd("right", "unlock", "voice")), want)


def test_stc_f_011_right_lock_via_physical_button(sim):
    """STC-F-011 (SWR-001) physical_button 경로 right lock은 오른쪽만 잠금."""
    want = exp("RELEASE", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")
    run_single(sim, "s0", b0(command=cmd("right", "lock", "physical_button")), want)


def test_stc_f_012_left_unlock_via_physical_button(sim):
    """STC-F-012 (SWR-001) physical_button 경로 left unlock은 왼쪽만 해제."""
    want = exp("RELEASE", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")
    run_single(sim, "s_lock", b0(command=cmd("left", "unlock", "physical_button")), want)


def test_stc_f_013_command_is_one_shot(sim):
    """STC-F-013 (SWR-001) 연속해 남은 같은 명령은 재적용 없음, 명령 없는 스냅샷 뒤 재입력은 적용"""
    c = cmd("left", "lock")
    sim.s0()
    # 1) 명령 적용
    assert judge(sim.send(b0(command=c))) == exp(
        "LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK"
    )
    # 2) 화재 강제 해제(C 연속)
    assert judge(sim.send(b0(command=c, fire_detected=True))) == exp(
        "RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", "FIRE"
    )
    # 3) 화재 해제, C가 계속 남아 있음 → 새 입력이 아니므로 재적용 없음
    assert judge(sim.send(b0(command=c))) == exp(
        "RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE"
    )
    # 4) 명령 없음
    assert judge(sim.send(b0())) == exp("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    # 5) 명령 재입력 → 새 입력으로 재적용
    assert judge(sim.send(b0(command=c))) == exp(
        "LOCK", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK"
    )


# ---- SWR-002 명령 형식 검증


def test_stc_f_014_reject_missing_side(sim):
    """STC-F-014 (SWR-002) side 누락 명령은 거절되고 출력 불변."""
    run_rejected_mix(sim, {"action": "unlock", "source": "physical_button"})


def test_stc_f_015_reject_non_string_side(sim):
    """STC-F-015 (SWR-002) side가 정수 1이면 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": 1, "action": "unlock", "source": "physical_button"})


def test_stc_f_016_reject_unknown_side(sim):
    """STC-F-016 (SWR-002) side가 미등록 값 center이면 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "center", "action": "unlock", "source": "physical_button"})


def test_stc_f_017_reject_missing_action(sim):
    """STC-F-017 (SWR-002) action 누락 명령은 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "all", "source": "physical_button"})


def test_stc_f_018_reject_non_string_action(sim):
    """STC-F-018 (SWR-002) action이 true이면 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "all", "action": True, "source": "physical_button"})


def test_stc_f_019_reject_unknown_action_case(sim):
    """STC-F-019 (SWR-002) action이 대문자 시작 Lock이면 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "all", "action": "Lock", "source": "physical_button"})


def test_stc_f_020_reject_missing_source(sim):
    """STC-F-020 (SWR-002) source 누락 명령은 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "all", "action": "lock"})


def test_stc_f_021_reject_non_string_source(sim):
    """STC-F-021 (SWR-002) source가 정수 5이면 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "all", "action": "lock", "source": 5})


def test_stc_f_022_reject_unknown_source(sim):
    """STC-F-022 (SWR-002) source가 미등록 값 tablet이면 거절되고 출력 불변."""
    run_rejected_mix(sim, {"side": "all", "action": "lock", "source": "tablet"})


def test_stc_f_023_rejected_command_keeps_other_rules(sim):
    """STC-F-023 (SWR-002) 명령이 거절돼도 같은 스냅샷의 차속 자동 잠금은 평가."""
    sim.s0()
    raw = b0(vehicle_speed_kph=3.0, command={"side": "center", "action": "lock", "source": "avn"})
    d = sim.send(raw)
    assert judge(d) == exp(
        "LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ["COMMAND_REJECTED"]
    )
    assert validity(d, "IF-004") == "INVALID"
    assert validity(d, "IF-001") == "VALID"


def test_stc_f_024_reject_empty_command_object(sim):
    """STC-F-024 (SWR-002) 빈 명령 객체 {}는 거절되고 출력 불변(제안 케이스)."""
    sim.s_mix()
    d = sim.send(b0(command={}))
    assert judge(d) == REJECTED_MIX
    assert validity(d, "IF-004") == "INVALID"


def test_stc_f_025_reject_non_object_command(sim):
    """STC-F-025 (SWR-002) 명령이 객체가 아닌 문자열 lock이면 거절(제안 케이스)."""
    sim.s_mix()
    d = sim.send(b0(command="lock"))
    assert judge(d) == REJECTED_MIX
    assert validity(d, "IF-004") == "INVALID"


def test_stc_f_026_absent_or_null_command_is_valid(sim):
    """STC-F-026 (SWR-002) 명령 생략·null은 거절 대상이 아니며 COMMAND_REJECTED 없음."""
    want = exp("LOCK", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    sim.s_mix()
    # (a) command 생략
    d = sim.send(b0())
    assert judge(d) == want
    assert validity(d, "IF-004") == "VALID"
    # (b) command = null
    d = sim.send(b0(command=None))
    assert judge(d) == want
    assert validity(d, "IF-004") == "VALID"


# ---- SWR-003 주행 자동 잠금


def test_stc_f_027_no_auto_lock_below_3kph(sim):
    """STC-F-027 (SWR-003) 차속 2.9, 2.99 km/h에서는 자동 잠금 없음."""
    want = exp("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    sim.s0()
    assert judge(sim.send(b0(vehicle_speed_kph=2.9))) == want
    assert judge(sim.send(b0(vehicle_speed_kph=2.99))) == want


def test_stc_f_028_auto_lock_at_3kph(sim):
    """STC-F-028 (SWR-003) 차속 3.0 km/h가 들어온 같은 평가에서 좌·우 LOCK."""
    sim.s0()
    # POST 응답으로 판정(다음 평가를 기다리지 않음)
    d = sim.send(b0(vehicle_speed_kph=3.0))
    assert judge(d) == exp("LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED")


def test_stc_f_029_no_auto_release_when_slowing(sim):
    """STC-F-029 (SWR-003) 차속이 3.0 미만으로 내려가도 자동 해제 없음."""
    sim.s0()
    assert judge(sim.send(b0(vehicle_speed_kph=3.0))) == exp(
        "LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED"
    )
    hold = exp("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    assert judge(sim.send(b0(vehicle_speed_kph=2.9))) == hold
    assert judge(sim.send(b0(vehicle_speed_kph=0.0))) == hold


def test_stc_f_030_integer_speed_is_valid(sim):
    """STC-F-030 (SWR-003) 차속 JSON 정수 3도 유효 숫자로 자동 잠금."""
    sim.s0()
    d = sim.send(b0(vehicle_speed_kph=3))
    assert judge(d) == exp("LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED")
    assert validity(d, "IF-001") == "VALID"


# ---- SWR-004 해제 조건


def test_stc_f_031_unlock_allowed_at_2_9kph(sim):
    """STC-F-031 (SWR-004, SWR-003) 차속 2.9 km/h에서는 해제 허용."""
    sim.s_lock()
    d = sim.send(b0(vehicle_speed_kph=2.9, command=cmd("all", "unlock")))
    assert judge(d) == exp("RELEASE", "RELEASE", "NORMAL", "DRIVER_COMMAND", "DRIVER_UNLOCK")


def test_stc_f_032_unlock_rejected_at_3kph(sim):
    """STC-F-032 (SWR-004, SWR-003) 차속 3.0 km/h에서는 해제 거절, AUTO_LOCK이 결정."""
    sim.s_lock()
    d = sim.send(b0(vehicle_speed_kph=3.0, command=cmd("all", "unlock")))
    assert judge(d) == exp(
        "LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED", ["DRIVER_UNLOCK_REJECTED"]
    )


def test_stc_f_033_unlock_rejected_when_speed_missing(sim):
    """STC-F-033 (SWR-004) 차속 누락(IF-001 무효)이면 해제 거절."""
    sim.s_lock()
    d = sim.send(b0(vehicle_speed_kph=DROP, command=cmd("all", "unlock")))
    assert judge(d) == exp(
        "LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE", ["DRIVER_UNLOCK_REJECTED"]
    )
    assert validity(d, "IF-001") == "INVALID"


def test_stc_f_034_unlock_rejected_when_isofix_missing(sim):
    """STC-F-034 (SWR-004) isofix_left 누락(IF-008 무효)이면 해제 거절, DEGRADED 아님."""
    sim.s_lock()
    d = sim.send(b0(isofix_left=DROP, command=cmd("all", "unlock")))
    assert judge(d) == exp(
        "LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE", ["DRIVER_UNLOCK_REJECTED"]
    )
    assert validity(d, "IF-008") == "INVALID"


def test_stc_f_035_isofix_left_blocks_left_only(sim):
    """STC-F-035 (SWR-004, SWR-018) isofix_left TRUE면 왼쪽만 해제 거절, 오른쪽은 해제."""
    sim.s_lock()
    d = sim.send(b0(isofix_left=True, command=cmd("all", "unlock")))
    assert judge(d) == exp(
        "LOCK", "RELEASE", "NORMAL", "ISOFIX", "ISOFIX", ["DRIVER_UNLOCK_REJECTED"]
    )


def test_stc_f_036_condition_checked_on_selected_side(sim):
    """STC-F-036 (SWR-004, SWR-009) 오른쪽 ISOFIX TRUE에서 왼쪽 해제 명령은 허용(제안 케이스)."""
    sim.s_lock()
    d = sim.send(b0(isofix_right=True, command=cmd("left", "unlock")))
    assert judge(d) == exp("RELEASE", "LOCK", "NORMAL", "ISOFIX", "ISOFIX")


def test_stc_f_037_unlock_rejected_when_degraded(sim):
    """STC-F-037 (SWR-004) crash_status 누락(IF-002 무효, DEGRADED)이면 해제 거절, 출력 유지."""
    sim.s_lock()
    d = sim.send(b0(crash_status=DROP, command=cmd("all", "unlock")))
    assert judge(d) == exp(
        "LOCK", "LOCK", "DEGRADED", "DEGRADED", "INPUT_INVALID", ["DRIVER_UNLOCK_REJECTED"]
    )


# ---- SWR-005 후측방 접근위험


def test_stc_f_038_left_risk_locks_left_each_cycle(sim):
    """STC-F-038 (SWR-005) 왼쪽 접근위험 TRUE면 같은 평가에서 왼쪽 LOCK, TRUE 동안 유지."""
    want = exp("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    n = b0(rear_left_approach_risk=True)
    sim.s0()
    assert judge(sim.send(n)) == want
    for _ in range(3):
        time.sleep(0.05)
        assert judge(sim.send(n)) == want


def test_stc_f_039_right_risk_locks_right(sim):
    """STC-F-039 (SWR-005) 오른쪽 접근위험 TRUE면 오른쪽만 LOCK."""
    want = exp("RELEASE", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    run_single(sim, "s0", b0(rear_right_approach_risk=True), want)


def test_stc_f_040_no_auto_release_after_risk(sim):
    """STC-F-040 (SWR-005) 접근위험이 FALSE로 돌아와도 LOCK 유지."""
    sim.s0()
    assert judge(sim.send(b0(rear_left_approach_risk=True))) == exp(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK"
    )
    assert judge(sim.send(b0())) == exp("LOCK", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")


def test_stc_f_041_stale_risk_still_locks(sim):
    """STC-F-041 (SWR-005) 지연(STALE) 스냅샷이어도 접근위험 TRUE는 LOCK 방향으로 적용."""
    sim.s0()
    t = sim.now()
    d = sim.send(b0(rear_left_approach_risk=True, source_timestamp_s=t - 0.300))
    assert judge(d) == exp("LOCK", "RELEASE", "DEGRADED", "APPROACH_RISK", "APPROACH_RISK")
    assert validity(d, "FRESHNESS") == "STALE"


def test_stc_f_042_string_risk_is_invalid(sim):
    """STC-F-042 (SWR-005) 위험 필드가 문자열 true면 무효, DEGRADED로 직전 출력 유지."""
    sim.s0()
    d = sim.send(b0(rear_left_approach_risk="true"))
    assert judge(d) == exp("RELEASE", "RELEASE", "DEGRADED", "DEGRADED", "INPUT_INVALID")
    assert validity(d, "IF-003") == "INVALID"


# ---- SWR-006 접근위험 해제 억제와 override

## override 창 안의 접근위험 유지 기대값
RISK_HOLD = exp("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
## 첫 해제 요청 억제 기대값
RISK_SUPPRESSED = exp(
    "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"]
)
## override 성립 기대값
RISK_OVERRIDE = exp("RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE")


def risk_precondition(sim: Simulator) -> dict[str, object]:
    """사전조건: S0 후 N 전송(L=LOCK, R=RELEASE, APPROACH_RISK). N을 돌려준다."""
    n = b0(rear_left_approach_risk=True)
    sim.s0()
    assert judge(sim.send(n)) == RISK_HOLD
    return n


def test_stc_f_043_repeated_request_is_not_override(sim):
    """STC-F-043 (SWR-006) 첫 해제 요청은 억제되고, 연속 스냅샷에 남은 같은 명령은 override 아님."""
    n = risk_precondition(sim)
    req = {**n, "command": cmd("left", "unlock")}
    # 2) 첫 요청 억제
    assert judge(sim.send(req)) == RISK_SUPPRESSED
    # 3) 같은 명령 연속 2회(50 ms 간격): override 아님, UNLOCK_SUPPRESSED 재발생 없음
    for _ in range(2):
        time.sleep(0.05)
        assert judge(sim.send(req)) == RISK_HOLD
    # 4) 명령 없음
    assert judge(sim.send(n)) == RISK_HOLD


def _attempt_044(sim: Simulator) -> tuple[bool, list[tuple[str, dict, dict]]]:
    """STC-F-044 1회 시도. (유효 시도 여부, [(단계, 실제, 기대)])를 돌려준다."""
    n = risk_precondition(sim)
    ts1 = floor_ms(sim.now())
    req1 = {**n, "command": cmd("left", "unlock"), "source_timestamp_s": ts1}
    d2 = sim.send(req1)
    d3 = sim.send(n)
    d4 = sim.send(dict(req1))  # REQ2 = REQ1과 동일(ts=ts1)
    valid = float(d4["timestamp_s"]) - ts1 <= VALID_AGE_S
    steps = [
        ("2", judge(d2), RISK_SUPPRESSED),
        ("3", judge(d3), RISK_HOLD),
        ("4", judge(d4), RISK_OVERRIDE),
    ]
    return valid, steps


def test_stc_f_044_override_window_lower_bound(sim):
    """STC-F-044 (SWR-006) 재요청 시각 - t0 = 0 ms이면 override 성립."""
    # 응답 timestamp_s - ts1 <= 190 ms 인 시도만 유효. 무효 시도는 새 서버로 재시험한다.
    valid, steps = _attempt_044(sim)
    for _ in range(MAX_ATTEMPTS - 1):
        if valid:
            break
        extra = Simulator()
        try:
            valid, steps = _attempt_044(extra)
        finally:
            extra.stop()
    assert valid, "타이밍 조건(응답 시각 - ts1 <= 190 ms)을 만족하는 시도가 없음"
    for step, actual, want in steps:
        assert (step, actual) == (step, want)


def _attempt_045(sim: Simulator) -> tuple[bool, list[tuple[str, dict, dict]]]:
    """STC-F-045 1회 시도. (유효 시도 여부, [(단계, 실제, 기대)])를 돌려준다."""
    n = risk_precondition(sim)
    ts1 = floor_ms(sim.now())
    req1 = {**n, "command": cmd("left", "unlock"), "source_timestamp_s": ts1}
    steps: list[tuple[str, dict, dict]] = [("2", judge(sim.send(req1)), RISK_SUPPRESSED)]
    # 3) KA: N을 100 ms 이하 주기로 보내며 서버 시각이 ts1 + 10.000 이상이 될 때까지 대기.
    #    KA 응답도 모두 판정 대상이다.
    target = ts1 + 10.000
    while True:
        time.sleep(0.08)
        d = sim.send(n)
        steps.append(("3", judge(d), RISK_HOLD))
        if float(d["timestamp_s"]) >= target:
            break
    # 4) 서버 시각이 target 이상이 된 즉시 REQ2 전송
    d4 = sim.send({**req1, "source_timestamp_s": target})
    valid = float(d4["timestamp_s"]) - target <= VALID_AGE_S
    steps.append(("4", judge(d4), RISK_OVERRIDE))
    # 5) N 전송: 위험 TRUE 유지 중 override 유지
    steps.append(("5", judge(sim.send(n)), RISK_OVERRIDE))
    return valid, steps


def test_stc_f_045_override_window_upper_bound(sim):
    """STC-F-045 (SWR-006) 재요청 시각 - t0 = 10,000 ms이면 override 성립, 위험 TRUE 중 유지."""
    valid, steps = _attempt_045(sim)
    for _ in range(MAX_ATTEMPTS - 1):
        if valid:
            break
        extra = Simulator()
        try:
            valid, steps = _attempt_045(extra)
        finally:
            extra.stop()
    assert valid, "타이밍 조건(응답 시각 - (ts1 + 10 s) <= 190 ms)을 만족하는 시도가 없음"
    for step, actual, want in steps:
        assert (step, actual) == (step, want)
