"""!
@brief 시스템 시험 예시 (작성 규칙 기준): STC-F-001, STC-F-060.

케이스 1건 = 시험 함수 1개. 함수 이름은 test_stc_<f|nf>_<번호>_<요약>.
docstring 첫 줄에 케이스 ID와 베이시스 ID를 쓴다.
단계별 기대값은 케이스의 "예상 출력값"을 그대로 옮긴다.
"""

from tests.system.harness import b0, cmd, expect, summary


def test_stc_f_001_right_lock_via_avn(sim):
    """STC-F-001 (SWR-001) avn 경로 right lock은 선택된 쪽에만 반영."""
    sim.s0()
    d = sim.send(b0(command=cmd("right", "lock", "avn")))
    assert summary(d) == expect("RELEASE", "LOCK", "NORMAL", "DRIVER_COMMAND", "DRIVER_LOCK")


def test_stc_f_060_suppression_then_reinput_is_override(sim):
    """STC-F-060 (SWR-006) 첫 해제 요청 억제 후 명령 없는 스냅샷을 거친 재요청은 override."""
    n = b0(rear_left_approach_risk=True)
    req = b0(rear_left_approach_risk=True, command=cmd("left", "unlock"))
    sim.s0()
    assert summary(sim.send(req)) == expect(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK", ["UNLOCK_SUPPRESSED"]
    )
    assert summary(sim.send(n)) == expect(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK"
    )
    assert summary(sim.send(req)) == expect(
        "RELEASE", "RELEASE", "OVERRIDE", "APPROACH_RISK", "APPROACH_OVERRIDE"
    )
