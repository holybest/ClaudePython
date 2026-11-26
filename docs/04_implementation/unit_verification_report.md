# 구현 및 단위 검증 보고서

| 항목 | 내용 |
|---|---|
| 문서 ID | UVR-ECL-001 |
| 대상 | `src/child_lock` (SW 유닛 SWU-01~11), 개발 도구 `tools/` |
| 기준 문서 | SWDD-ECL-001 개정 0.3, SAP-ECL-001 개정 0.2, CLAUDE.md 소스코드 품질 |
| 목표 베이스라인 | BL-CODE-UT-1.0 (게이트 G3) |
| 작성일 | 2026-11-26 |

## 1. 구현 방법
- 모든 제품 코드는 TDD(실패하는 시험 → 최소 구현 → 정리)로 작성했다. 모듈마다 시험을 먼저 작성해 실패를 확인한 뒤 구현했다.
- 시험이 결함을 실제로 잡는지 확인하려고 안전 로직에 의도적 결함(변이)을 넣어 시험 실패를 확인했다(3장).
- 설정 파일(`pyproject.toml`, `Jenkinsfile`, `requirements-dev.txt`)은 TDD 예외 항목이며, CI 실행으로 동작을 확인했다.

## 2. 유닛별 시험 결과

| 유닛 | 모듈 | ASIL | 시험 파일 | 시험 수 | 분기 커버리지 |
|---|---|---|---|---|---|
| SWU-01 | `core/model.py` | B | `tests/unit/test_model.py` | 26 | 100% |
| SWU-02 | `core/validation.py` | B | `tests/unit/test_validation.py` | 120 | 100% |
| SWU-03~05 | `core/arbitration.py`, `core/rules.py`, `core/controller.py` | B | `tests/unit/test_controller.py` | 95 | 100% |
| SWU-06~08 | `runtime/runtime.py`, `app/event_log.py`, `app/service.py` | B / QM | `tests/unit/test_runtime_app.py` | 17 | 100% |
| SWU-09~10 | `web/server.py`, `web/__main__.py` | QM | `tests/unit/test_web.py` | 34 | 100% |
| SWU-11 | `web/static/index.html` | QM | 단위 시험 대상 아님(SWDD 14장). 5·6단계에서 확인 | – | – |
| 아키텍처 | 전체 | – | `tests/architecture/test_dependencies.py` | 1 | – |
| 도구 | `tools/arch_check.py`, `tools/quality_check.py` | – | `tests/tools/` | 35 | 100% |
| **합계** | | | | **328** | **100%** |

- 시험 성공률: 328/328 (Python 3.12.10, 3.14.10 모두)
- SWDD 6.3 판정 기대값 표 13행은 모두 `test_controller.py`에 시험으로 들어 있다.
- 사용한 기법: 동치 분할, 경계값 분석(차속 −0.1/0.0/2.9/3.0/300.0/300.1, 지연 200/201 ms, override 경과 −1/0/10,000/10,001 ms, 0.5 ms 반올림 경계), 상태 전이(override 가드), 규칙 쌍 조합(SWR-019), 오류 추측(큰 정수, NaN, 무한대, 시각 역행, 본문을 읽지 않은 오류 응답).

## 3. 변이 확인 (시험의 결함 검출력)

안전 코어에 아래 결함을 하나씩 넣고 단위 시험을 실행했다. 12종 모두 시험이 실패해 결함을 검출했다.

| # | 넣은 결함 | 관련 SWR |
|---|---|---|
| 1 | 규칙 3(접근위험)과 규칙 4(입력 이상) 순서 뒤바꿈 | SWR-019 |
| 2 | override 창 하한(0 ms) 제거 | SWR-006 |
| 3 | 지연 경계 `≤ 200`을 `< 200`으로 | SWR-013 |
| 4 | 명령 새 입력 판정 제거 | SWR-006, DEF-09 |
| 5 | 시동 OFF 초기화에서 입력 이상 조건 제거 | SWR-020 |
| 6 | 잠금 명령의 override 종료 제거 | SWR-006 (CR-03) |
| 7 | 충돌 래치 무시 | SWR-007 |
| 8 | 차속 무효 시 운전자 해제 허용 | SWR-004 |
| 9 | FAULT 상태 제거 | SWR-021 |
| 10 | INPUT_INVALID / INPUT_STALE 구분 제거 | SWR-013 |
| 11 | tick 명령 알림 이중 방어 제거 | SWAD 3.2 |
| 12 | DEGRADED 중 override 허용 | SWR-006 |

11번은 처음에 시나리오 시험으로 검출되지 않아(이중 방어라 정상 경로에서는 드러나지 않음) 해당 함수를 직접 검사하는 시험을 추가했다.

## 4. 정적 분석 결과 (SAP-ECL-001)

| ID | 항목 | 결과 |
|---|---|---|
| SA-01 | Ruff (E, W, F, I, N, B, UP, SIM, C90, SLF) | 위반 0건 |
| SA-02 | Ruff 포맷 | 차이 0건 |
| SA-03 | 순환 복잡도 | 최대 6 (기준 10 이하) |
| SA-04 | 주석률 / 함수 길이 | 모듈 최저 33.3% (기준 20% 이상), 함수 최대 순수 코드 19줄 (기준 50줄 이하) |
| SA-05 | 아키텍처 의존 규칙 | 위반 0건 |
| SA-06 | mypy strict (Python 3.12 기준) | 오류 0건 (15개 파일) |
| SA-07 | Python 3.12 / 3.14 시험 | 모두 통과, 커버리지 100% |
| SA-08 | 런타임 의존성 | 0개 |
| SA-09 | Doxygen 주석 형식 | 위반 0건 |
| SA-10 | 규칙 예외 표기(`noqa`, `type: ignore`, `pragma`, `skip`, `xfail`) | 0건 |

## 5. 구현 중 발견한 결함과 조치

| # | 결함 | 발견 경위 | 조치 |
|---|---|---|---|
| 1 | 0.5 ms 경계에서 부동소수 오차로 반올림이 내림이 됨(예: 0.3005 − 0.1) | 경계값 시험 설계 중 | `diff_ms`를 소수 6자리 정리 후 0.5 올림으로 구현 |
| 2 | 판정 모듈과 규칙 모듈의 순환 import | 구현 중 | `Resolution`을 `rules.py`에 정의 (SWDD 5.1 기록) |
| 3 | 오류 응답 전에 요청 본문을 읽지 않으면 Windows에서 연결이 강제로 끊겨 클라이언트가 응답을 못 받음 | Python 3.14 시험 간헐 실패 → 반복 재현(300회 중 12건) | POST 본문 선 읽기(`_take_body`), 재현 시험 추가 (SWDD 10.1 기록) |
| 4 | 품질 도구가 `NoReturn` 함수에도 `@return`을 요구(오탐) | Web 구현 중 | 도구 수정(시험 선행) |
| 5 | 명령 직후 tick이 이력에 기록되지 않는다고 가정한 시험 기대값 오류 | 시험 실패 분석 | CR-01 규칙(이유 코드 변화 시 기록)대로 기대값 수정 |

## 6. CI
- Jenkins `ClaudePython-CI` » `feature/core-implementation`에서 위 검사를 모두 자동 실행한다(Jenkinsfile). 결과는 PR 본문에 기록한다.
