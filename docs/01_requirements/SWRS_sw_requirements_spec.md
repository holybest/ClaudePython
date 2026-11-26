# SW 요구사항 사양서 (SWRS)

| 항목 | 내용 |
|---|---|
| 문서 ID | SWRS-ECL-001 |
| 개정 | 0.2 (독립 검토 RV-01 결과 반영) |
| 대상 | 전자식 차일드락 제어 SW (PC/SIL 참조 구현) |
| 입력 | OEM-SWR-001 Rev 1.0 (BL-OEM-1.0) |
| 목표 베이스라인 | BL-SWR-1.0 (게이트 G1) |
| 상태 | 초안 — 사용자 검토 및 OEM 질의 답변 대기 |
| 작성일 | 2026-11-26 |

## 1. 개요

### 1.1 목적
OEM-SWR-001의 OEM 요구사항 13건(안전 4, 기능 7, 비기능 2), 외부 인터페이스 9건, 제품 경계(3장)와 프로젝트 제약(2장)을 시험 가능한 SW 요구사항(SWR-001~026)으로 구체화한다.

### 1.2 범위
- 포함: 후석 좌·우 차일드락의 잠금/해제 **논리 판단**, 상태·이유 코드, 입력 검증·감시, 결정 이력, Web 시뮬레이터(화면·API).
- 제외: 도어 래치·구동기 HW, CAN/LIN 드라이버, 양산 ECU·RTOS·HIL·실차, HARA·ASIL 결정, 법규 적합성 판단, 인증.

### 1.3 표기
- **ASIL**: OEM이 할당한 등급을 따른다(B 또는 QM). 둘 이상의 OEM 요구에서 파생된 SWR은 높은 등급을 따른다.
- **[가정 A-xx]**: OEM 원문이 정의하지 않아 공급자가 임시로 정한 내용. OEM 질의(`oem_queries.md`) 답변 후 갱신한다.

## 2. 실행 모델과 공통 정의

| ID | 정의 |
|---|---|
| DEF-01 평가 | SW는 두 가지 평가를 수행한다. (a) **스냅샷 평가**: 차량 입력 스냅샷 1건을 받아 1회 평가. (b) **tick 평가**: 새 입력 없이 현재 시각 `now`만으로 1회 평가(입력 중단 감시용, SWR-022). 둘 다 "평가 주기" 1회로 본다. 공칭 입력 주기와 tick 주기는 50 ms이다. [가정 A-01] |
| DEF-02 반응 시점 | "첫 평가주기", "다음 평가주기", "N ms 이내" 요구는 **해당 입력이 처음 들어온 평가의 결과**에 반영하는 것으로 만족한다. 이는 "다음 평가주기"를 "늦어도 다음 주기"로 해석한 것이다. [가정 A-01, 질의 Q-06] |
| DEF-03 시각 | 평가 시각 `now`는 주입된 시계에서 얻는다(SWR-016). 스냅샷의 `source_timestamp_s`(OEM-IF-001)는 스냅샷 전체의 생성 시각이며, 운전자 명령의 요청 시각이기도 하다(OEM-IF-004). [가정 A-02] |
| DEF-04 시간 비교 | 시간 차이는 ms 단위 정수로 반올림한 뒤 비교한다(부동소수 오차 방지). 예: 0.2004 s → 200 ms. [가정 A-15] |
| DEF-05 출력 | 좌·우 각각 `LOCK` 또는 `RELEASE` (OEM-IF-005). |
| DEF-06 초기 상태 | 기동 시 출력은 좌·우 `RELEASE`, 상태는 `OFF`이다. 첫 스냅샷을 받기 전에는 입력 중단 감시(SWR-022)를 하지 않는다. 이 출력이 최초의 "직전 확정 출력"이다. [가정 A-03] |
| DEF-07 입력 그룹 | 검증은 입력 인터페이스 단위(IF-001, IF-002, IF-003, IF-004, IF-007, IF-008, IF-009)로 한다. 무효 그룹에 의존하는 규칙만 비활성화하고, 다른 유효 그룹에 의존하는 규칙은 계속 평가한다. [가정 A-04] |
| DEF-08 안전 입력 그룹 | ASIL B 규칙이 의존하는 그룹: IF-002(충돌), IF-003(접근위험), IF-009(시동·센서 고장). 그리고 스냅샷 freshness. 이 중 하나라도 무효이거나 지연되면 **안전 입력 이상**이다(SWR-013). IF-001·IF-004·IF-007·IF-008의 무효는 안전 입력 이상으로 보지 않는다. [가정 A-04] |
| DEF-09 운전자 명령 | 운전자 명령은 스냅샷에 선택적으로 포함되는 1회성 이벤트이다. 직전 스냅샷에 없던 명령이 들어오면 "새 입력"이다. 같은 명령이 연속된 스냅샷에 계속 있으면 하나의 입력으로 본다. [가정 A-16] |
| DEF-10 상태 | 상태는 다음 순서로 처음 맞는 것이다: 충돌 해제 활성 → `EMERGENCY`, 센서 고장 → `FAULT`, 안전 입력 이상 → `DEGRADED`, override 활성인 쪽 있음 → `OVERRIDE`, 시동 OFF → `OFF`, 그 외 → `NORMAL`. 좌·우 결정 규칙이 달라도 상태는 하나이다. [가정 A-14] |

## 3. SW 요구사항

### 3.1 운전자 명령

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-001 | QM | SW는 운전자 명령(`side` ∈ left/right/all, `action` ∈ lock/unlock, `source` ∈ physical_button/avn/voice/mobile_app)을 선택된 쪽 출력에만 적용해야 한다. `all`은 좌·우 모두를 뜻한다. 네 source는 동일하게 처리한다. 적용 시 이유는 `DRIVER_LOCK` 또는 `DRIVER_UNLOCK`이다. | 정지(차속 0.0), 모든 입력 유효, 상위 규칙 비활성에서 4 source × 2 action × 3 side 조합 각각이 선택된 출력에만 반영되고 반대쪽 출력은 변하지 않는다. | OEM-FR-001, IF-004 |
| SWR-002 | QM | SW는 운전자 명령의 필드 누락, 형식 오류, 미등록 enum 값을 거절해야 한다. 거절된 명령으로 인한 출력 변화는 없어야 하고, 알림(`notices`)에 `COMMAND_REJECTED`를 넣는다. 다른 규칙의 평가는 계속한다. | `side`·`action`·`source` 각각의 누락, 문자열이 아닌 값, 미등록 값(예: `side="center"`)에서 명령 적용 없음 + `COMMAND_REJECTED`. 같은 스냅샷의 차속 3.0 km/h 자동 잠금은 그대로 동작. | OEM-FR-001, IF-004 |
| SWR-004 | QM | SW는 운전자 해제 명령을 다음 조건을 모두 만족하는 쪽에만 적용해야 한다: (a) IF-001이 유효하고 차속 < 3.0 km/h, (b) 해당 쪽 접근위험이 FALSE(override는 SWR-006), (c) IF-008이 유효하고 해당 쪽 ISOFIX FALSE, (d) 상위 우선순위 규칙(SWR-019)이 해당 쪽 출력을 결정하지 않음. 조건을 만족하지 못한 쪽은 출력을 유지하고 알림에 `DRIVER_UNLOCK_REJECTED`를 넣는다. [가정 A-05] | 조건 (a)~(d)를 하나씩 위반한 상태에서 해제 명령 시 해당 쪽 출력 유지 + `DRIVER_UNLOCK_REJECTED`. 모두 만족 시 해당 쪽 `RELEASE`. 차속 경계 2.9 / 3.0 km/h. | OEM-FR-001, IF-001, IF-008 |

### 3.2 주행 자동 잠금

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-003 | QM | SW는 IF-001이 유효하고 차속이 3.0 km/h 이상이면 해당 평가부터 좌·우 출력을 `LOCK`으로 해야 한다(이유 `AUTO_LOCK_SPEED`). 차속이 3.0 km/h 미만으로 내려가도 자동으로 해제하지 않는다. [가정 A-06] | 차속 2.9 → 자동 잠금 없음, 3.0 → 같은 평가에 좌·우 `LOCK`. 이후 0.0 → `LOCK` 유지. | OEM-FR-002, IF-001 |

### 3.3 후측방 접근위험

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-005 | B | SW는 IF-003이 형식상 유효하고 `rear_<side>_approach_risk`가 TRUE이면 해당 평가에 그 쪽 출력을 `LOCK`으로 해야 한다(이유 `APPROACH_RISK`). 위험이 TRUE인 동안 매 평가 `LOCK`을 유지한다. 단, SWR-006의 override가 활성인 쪽은 예외이다. 스냅샷이 지연(STALE)된 경우에도 TRUE이면 `LOCK` 방향으로만 적용한다. | 위험 TRUE 주입 평가에 해당 쪽 `LOCK` + `APPROACH_RISK`. 위험 유지 중 매 평가 `LOCK`. 지연 스냅샷의 TRUE도 `LOCK`. | OEM-SR-002, IF-003 |
| SWR-006 | B | SW는 접근위험 TRUE인 쪽의 해제 요청(새 입력, DEF-09)을 억제해야 한다: 출력 `LOCK` 유지, 알림 `UNLOCK_SUPPRESSED`, 억제 시각 t0 = 해당 스냅샷의 `source_timestamp_s` 기록. 같은 쪽 해제 요청이 새 입력으로 다시 들어오고 그 요청 시각 − t0 ≤ 10,000 ms이면 명시적 override로 처리한다: 그 쪽 `RELEASE`, 이유 `APPROACH_OVERRIDE`. override는 그 쪽 위험이 FALSE가 될 때까지 유지되며(그동안 `RELEASE`, 상태 `OVERRIDE`), 위험 FALSE, 시동 OFF, 충돌 해제, 센서 고장, 안전 입력 이상 중 하나가 되면 끝난다. 요청 시각 − t0 > 10,000 ms이면 새 첫 요청으로 보고 다시 억제하며 t0를 갱신한다. 안전 입력 이상(DEGRADED) 중에는 override를 허용하지 않는다. [가정 A-07] | 첫 해제 요청 → `LOCK` + `UNLOCK_SUPPRESSED`. 재요청 경과 10,000 ms → override, 10,001 ms → 다시 억제. 같은 명령이 연속 스냅샷에 남아 있으면 override 아님. override 후 위험 TRUE 유지 → `RELEASE` 유지. 위험 FALSE → override 종료. 이후 위험 TRUE 재발생 → `LOCK`. 반대쪽 요청은 override 아님. | OEM-SR-002, OEM-FR-003, IF-004 |
| SWR-009 | B | SW는 접근위험, ISOFIX, 운전자 명령의 영향을 해당 쪽 출력에만 적용하고 반대쪽 출력은 바꾸지 않아야 한다. | 좌측 위험만 TRUE일 때 우측 출력과 우측 명령 처리가 위험 FALSE일 때와 같다. ISOFIX, 명령도 같은 방식으로 확인. | OEM-SR-002, OEM-FR-001, OEM-FR-006 |

### 3.4 충돌 긴급해제

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-007 | B | SW는 IF-002가 형식상 유효하고 `crash_status = CONFIRMED`이면 다른 모든 규칙보다 우선하여 해당 평가에 좌·우 출력을 `RELEASE`로 해야 한다(이유 `CRASH_CONFIRMED`, 상태 `EMERGENCY`). 이 판단은 스냅샷 지연(STALE)이나 다른 그룹의 무효와 관계없이 적용한다. 이후 `crash_status` 값과 관계없이 래치를 유지하며, 시동 OFF(SWR-020)에서만 래치를 해제한다. [가정 A-08] | CONFIRMED 주입 평가에 좌·우 `RELEASE`. 지연 스냅샷 + CONFIRMED, IF-001 무효 + CONFIRMED, 센서 고장 + CONFIRMED에서도 `RELEASE`. 이후 NONE·PENDING·접근위험·ISOFIX·차속·잠금 명령에도 `RELEASE` 유지. 시동 OFF 후 래치 해제. | OEM-SR-001, IF-002 |
| SWR-008 | B | SW는 `crash_status = PENDING`이면 출력을 바꾸지 않고 다른 규칙을 계속 평가하며, 알림에 `CRASH_PENDING`을 넣어야 한다. [가정 A-09] | PENDING 주입 시 출력·이유 코드가 NONE일 때와 같고 알림에 `CRASH_PENDING`. PENDING → CONFIRMED 시 SWR-007 동작. | OEM-SR-001, IF-002 |

### 3.5 이벤트 기록 (결정 이력)

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-010 | QM | SW는 모든 평가(스냅샷·tick) 결과를 결정 이벤트로 기록하고, 1부터 1씩 증가하는 `event_id`를 부여해야 한다. | 연속 N회 평가 후 이벤트의 `event_id`가 1..N으로 연속. | OEM-NFR-002 |
| SWR-011 | QM | 결정 이벤트는 허용 필드(`event_id`, `timestamp_s`, `lock_left`, `lock_right`, `state`, `priority_reason`, `reason_code`, `notices`)만 가져야 하며, 영상·음성·개인 식별자를 저장하지 않아야 한다. `timestamp_s`는 평가 시각 `now`이다. | 저장된 이벤트의 필드 집합이 허용 목록과 정확히 같다. | OEM-NFR-002, OEM 2장 프로젝트 제약 |
| SWR-012 | QM | SW는 최근 100건의 결정 이벤트만 메모리에 보존하고(오래된 것부터 삭제), 조회 시 오래된 순으로 반환해야 한다. 파일·DB 같은 영속 저장을 하지 않아 프로세스 재기동 후 이력이 없어야 한다. | 101건 평가 후 조회 결과가 `event_id` 2..101 순서. 새 프로세스에서 조회 시 0건. 실행 중 파일 생성 없음. | OEM-NFR-002 |

### 3.6 입력 검증과 감시

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-013 | B | SW는 평가 전에 입력 그룹별로 누락·형식·범위를 검증해야 한다(범위: 아래 표). 무효 그룹은 `INVALID`로 표시하고 그 그룹에 의존하는 규칙에 쓰지 않는다. 최근 수신 스냅샷의 `now - source_timestamp_s > 200 ms`이면 `STALE`이다. 안전 입력 이상(DEF-08)이면 해당 평가에 상태를 `DEGRADED`로 하고, 상위 규칙(SWR-019 순위 1~3)이 결정하지 않은 쪽은 직전 확정 출력을 유지한다(이유 `INPUT_INVALID` 또는 `INPUT_STALE`). 안전 입력 그룹이 모두 유효하고 지연이 없으면 정상 평가로 돌아간다. [가정 A-04, A-10] | 그룹별 누락·형식·범위 경계(예: 차속 -0.1 / 0.0 / 300.0 / 300.1)에서 `INVALID` 판정. 지연 200 ms → 정상, 201 ms → `DEGRADED`. IF-007 무효만으로는 `DEGRADED` 아님(화재 규칙만 비활성). DEGRADED 중 접근위험 TRUE → 해당 쪽 `LOCK`. 복귀 확인. | OEM-SR-003, IF-001~IF-004, IF-007~IF-009 |
| SWR-022 | B | SW는 tick 평가(DEF-01)를 제공해야 한다. 마지막으로 받은 스냅샷 기준 `now - source_timestamp_s > 200 ms`이면 tick 평가에서 `DEGRADED`(이유 `INPUT_STALE`)로 전환한다. 시뮬레이터·호스트는 tick을 50 ms 이하 주기로 호출하고, 상태 조회(SWR-015) 때도 tick을 1회 수행한다. [가정 A-01] | 시각 0 ms에 스냅샷 수신, 이후 입력 없이 50 ms마다 tick → 250 ms tick에서 `DEGRADED`(입력 중단 후 300 ms 이내). 새 유효 스냅샷 수신 시 복귀. | OEM-SR-003 |

입력 범위 (OEM 6장 기준):

| 그룹 | 필드 | 유효 값 |
|---|---|---|
| IF-001 | `vehicle_speed_kph` | 실수 또는 정수 0.0 ~ 300.0 (bool 제외) |
| IF-001 | `gear` | `P`, `N`, `D`, `R` |
| IF-001 | `source_timestamp_s` | 실수 ≥ 0.0, `now` 이하 [가정 A-02] |
| IF-002 | `crash_status` | `NONE`, `PENDING`, `CONFIRMED` |
| IF-003 | `rear_left_approach_risk`, `rear_right_approach_risk` | bool |
| IF-004 | `side`, `action`, `source` | SWR-001/002 참고. 명령은 선택 입력(없으면 명령 없음) |
| IF-007 | `fire_detected`, `overtemperature_detected`, `adult_present` | bool |
| IF-008 | `isofix_left`, `isofix_right` | bool |
| IF-009 | `ignition_on`, `sensor_fault` | bool |

`source_timestamp_s`가 무효이면 freshness를 판단할 수 없으므로 `STALE`로 본다.

### 3.7 상태 조회와 표시

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-014 | QM | SW는 상태 조회 결과로 `lock_left`, `lock_right`, `state`, `input_validity`(그룹별 `VALID`/`INVALID`/`STALE`), `priority_reason`, `reason_code`, `notices`를 제공해야 한다. `priority_reason`은 해당 평가에서 출력을 결정한 최상위 규칙(4장 표)이고, `reason_code`는 그 규칙의 세부 코드이다(N:1 매핑). `notices`는 출력을 결정하지 않은 부가 알림 목록이다. | 4장의 각 `reason_code`가 나오는 상황에서 7개 필드가 모두 있고 값이 기대와 같다. `reason_code` → `priority_reason` 매핑이 4장 표와 같다. | OEM-FR-004, IF-006 |
| SWR-015 | QM | SW는 HTTP 인터페이스를 제공해야 한다: `GET /api/status`(SWR-014 JSON), `GET /api/events`(SWR-012 이력), `POST /api/snapshot`(시뮬레이터 입력 → 스냅샷 평가 1회). 응답 직렬화에 실패하면 HTTP 500을 반환한다. 요청 본문이 JSON이 아니면 HTTP 400을 반환한다. [가정 A-11] | 각 엔드포인트 정상 응답 200과 JSON 스키마. 직렬화 실패 주입 시 500. 잘못된 JSON 본문 시 400. | OEM-FR-004, IF-006 |
| SWR-025 | QM | SW는 Web 시뮬레이터 화면(`GET /`)을 제공해야 한다. 화면에서 IF-001~IF-004, IF-007~IF-009의 모든 입력값을 설정해 스냅샷을 보낼 수 있고, SWR-014 상태와 최근 결정 이력을 볼 수 있어야 한다. | 화면에서 각 입력 필드를 설정해 전송 → `/api/status`와 화면 표시가 같다. 이력 표시 확인. | OEM-FR-004, OEM 3장 표시/조작 |
| SWR-026 | QM | SW는 정의된 입력 필드(3.6 표, 운전자 명령)만 받아야 한다. 정의되지 않은 필드가 있는 요청은 HTTP 400으로 거절하고 처리·저장하지 않는다. 성인 존재는 불리언(`adult_present`)으로만 받는다. | 영상·음성·이름 등 정의되지 않은 필드를 넣은 요청 → 400, 상태·이력 변화 없음. | OEM-NFR-002, OEM 2장 프로젝트 제약, 7장 개인정보 처리 |

### 3.8 결정론, 처리 시간, 실행 환경

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-016 | QM | SW의 평가 결과는 초기 상태, 입력 순서(스냅샷·tick), 주입된 시계 값에만 의존해야 한다. 실제 시계, 난수, 집합 순서 같은 외부 요인에 의존하지 않는다. | 고정 시계로 같은 입력 벡터를 1,000회 재생했을 때 공개 결과(SWR-014 필드 + 이벤트)의 SHA-256 해시가 모두 같다. | OEM-NFR-001 |
| SWR-023 | B | SW의 1회 평가(스냅샷·tick) 처리 시간은 10 ms 이하여야 한다. 이는 300 ms(SR-001), 100 ms(SR-003) 시간 요구를 같은 평가 반영(DEF-02)으로 만족하기 위한 근거이다. [가정 A-17] | PC 실행 환경에서 대표 입력 1,000회 평가의 최대 처리 시간 ≤ 10 ms. | OEM-SR-001, OEM-SR-003 (파생) |
| SWR-024 | QM | SW는 Python 3.12에서 동작해야 하며, 런타임에 표준 라이브러리만 사용한다. | Python 3.12 환경에서 전체 시험 통과. 런타임 의존성 목록이 비어 있음. | OEM 3장 실행 환경 |

### 3.9 강제 해제와 강제 잠금

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-017 | QM | SW는 IF-007이 유효하고 `fire_detected`, `overtemperature_detected`, `adult_present` 중 하나라도 TRUE이면 해당 평가에 좌·우 출력을 `RELEASE`로 해야 한다. 이유 코드는 `FIRE`, `OVERTEMP`, `ADULT_PRESENT`이며, 여러 개가 동시에 TRUE이면 이 순서로 앞의 것을 쓴다. 단, 상위 우선순위 규칙(SWR-019)이 결정한 쪽은 제외한다. | 각 입력 단독 TRUE 주입 시 같은 평가에 좌·우 `RELEASE` + 입력별 이유 코드. 동시 TRUE 시 순서 확인. | OEM-FR-005, IF-007 |
| SWR-018 | QM | SW는 IF-008이 유효하고 `isofix_<side>`가 TRUE이면 해당 쪽 출력을 `LOCK`으로 하고(이유 `ISOFIX`), 반대쪽 출력은 유지해야 한다. TRUE인 동안 그 쪽 운전자 해제를 거절한다. FALSE가 되어도 자동 해제하지 않는다. [가정 A-12] | 한쪽만 TRUE 주입 시 그 쪽만 `LOCK`, 반대쪽 유지. TRUE 중 해제 명령 거절. | OEM-FR-006, IF-008 |

### 3.10 우선순위 판정 (파생 요구)

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-019 | B | SW는 매 평가에 아래 우선순위(1이 최상위)로 쪽별 출력을 결정해야 한다. 상위 규칙이 결정한 쪽은 하위 규칙이 바꾸지 않는다. `priority_reason`·`reason_code`는 좌·우 중 더 높은 순위 규칙의 것을 쓴다. 상태는 DEF-10을 따른다. [가정 A-13] | 두 규칙이 동시에 활성인 모든 쌍에서 상위 규칙의 출력과 `priority_reason`이 나온다. | OEM-SR-001(“다른 명령보다 우선”), SR-002, SR-003, SR-004, FR-002, FR-003, FR-005, FR-006, FR-007 — 규칙 간 충돌 해소 |

| 순위 | 규칙 (활성 조건) | 결정하는 쪽과 출력 | `priority_reason` |
|---|---|---|---|
| 1 | 충돌 CONFIRMED 또는 래치 (IF-002 형식 유효) | 좌·우 `RELEASE` | `CRASH` |
| 2 | 센서 고장 (IF-009 유효, `sensor_fault` TRUE) | 좌·우 직전 확정 출력 유지 | `SENSOR_FAULT` |
| 3 | 접근위험 (IF-003 형식 유효, 해당 쪽 TRUE) | 해당 쪽 `LOCK` (override 활성 시 `RELEASE`) | `APPROACH_RISK` |
| 4 | 안전 입력 이상 (DEF-08) | 남은 쪽 직전 확정 출력 유지 | `DEGRADED` |
| 5 | 시동 OFF (IF-009 유효, `ignition_on` FALSE) | 좌·우 `RELEASE` | `IGNITION_OFF` |
| 6 | 화재·과온·성인 탑승 (IF-007 유효) | 남은 쪽 `RELEASE` | `FORCED_RELEASE` |
| 7 | ISOFIX (IF-008 유효, 해당 쪽 TRUE) | 해당 쪽 `LOCK` | `ISOFIX` |
| 8 | 차속 ≥ 3.0 km/h (IF-001 유효) | 남은 쪽 `LOCK` | `AUTO_LOCK` |
| 9 | 운전자 명령 (IF-004 유효, 새 입력) | 선택 쪽 `LOCK`/`RELEASE` | `DRIVER_COMMAND` |
| – | 해당 규칙 없음 | 직전 출력 유지 | `NONE` |

원칙: ASIL B 요구(1~4)를 QM 요구(5~9)보다 앞에 둔다. QM 요구 사이에서는 해제 쪽(5, 6)을 잠금 쪽(7, 8)보다 앞에 둔다. 순서는 OEM 확인이 필요하다(질의 Q-02).

### 3.11 시동 OFF

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-020 | QM | SW는 IF-009가 유효하고 `ignition_on = FALSE`이면 해당 평가에서 먼저 충돌 래치(SWR-007)와 override(SWR-006)를 초기화한 뒤 우선순위 판정을 수행해야 한다. 상위 규칙이 없으면 좌·우 출력은 `RELEASE`, 상태 `OFF`, 이유 `IGNITION_OFF`이다. 같은 스냅샷에 CONFIRMED가 있으면 래치가 다시 설정된다(순위 1). | FALSE 주입 첫 평가에 좌·우 `RELEASE` + `OFF` + `IGNITION_OFF`. 래치 상태에서 FALSE + NONE → `OFF`. FALSE + CONFIRMED → `EMERGENCY`, `RELEASE`. 이후 ON에서 래치 없음. | OEM-FR-007, IF-009 |

### 3.12 센서 고장

| ID | ASIL | 요구사항 | 검증 기준 | 출처 |
|---|---|---|---|---|
| SWR-021 | B | SW는 IF-009가 유효하고 `sensor_fault = TRUE`이면 새 명령과 하위 우선순위 규칙을 적용하지 않고 직전 확정 출력을 유지해야 한다. 상태는 `FAULT`, 경고 코드(`reason_code`)는 `W_SENSOR_FAULT`이다. 충돌 CONFIRMED(순위 1)는 예외로 적용한다. | TRUE 첫 평가에 좌·우 출력 유지 + `FAULT` + `W_SENSOR_FAULT`. TRUE 중 잠금·해제 명령, 차속, 접근위험 변화에도 유지. TRUE 중 CONFIRMED → `RELEASE`. | OEM-SR-004, IF-009 |

## 4. 이유 코드

| `priority_reason` | `reason_code` | 상황 |
|---|---|---|
| `CRASH` | `CRASH_CONFIRMED` | 충돌 해제 |
| `SENSOR_FAULT` | `W_SENSOR_FAULT` | 센서 고장 (경고 코드) |
| `APPROACH_RISK` | `APPROACH_RISK` | 접근위험 잠금 |
| `APPROACH_RISK` | `APPROACH_OVERRIDE` | 접근위험 override 해제 |
| `DEGRADED` | `INPUT_INVALID` | 안전 입력 그룹 무효 (지연과 동시면 이것을 우선) |
| `DEGRADED` | `INPUT_STALE` | 스냅샷 지연·입력 중단 |
| `IGNITION_OFF` | `IGNITION_OFF` | 시동 OFF |
| `FORCED_RELEASE` | `FIRE` / `OVERTEMP` / `ADULT_PRESENT` | 강제 해제 |
| `ISOFIX` | `ISOFIX` | ISOFIX 잠금 |
| `AUTO_LOCK` | `AUTO_LOCK_SPEED` | 주행 자동 잠금 |
| `DRIVER_COMMAND` | `DRIVER_LOCK` / `DRIVER_UNLOCK` | 운전자 명령 적용 |
| `NONE` | `NO_CHANGE` | 결정 규칙 없음 |

알림(`notices`, 출력을 결정하지 않는 부가 정보): `CRASH_PENDING`, `COMMAND_REJECTED`, `DRIVER_UNLOCK_REJECTED`, `UNLOCK_SUPPRESSED`.

## 5. 가정 목록

가정의 근거와 OEM 질의는 `oem_queries.md`에 있다.

| ID | 가정 | 관련 SWR |
|---|---|---|
| A-01 | 스냅샷·tick 평가, 공칭 주기 50 ms. 시간 요구는 같은 평가 반영으로 만족 | 전체, SWR-022 |
| A-02 | `source_timestamp_s`가 스냅샷 전체 시각이며, `now`보다 미래이면 무효 | SWR-006, 013 |
| A-03 | 기동 시 출력 `RELEASE`, 상태 `OFF`, 첫 스냅샷 전 감시 없음 | SWR-013, 020, 021, 022 |
| A-04 | 검증은 입력 그룹 단위. 안전 입력 그룹은 IF-002/003/009와 freshness | SWR-013 |
| A-05 | 운전자 해제는 정지(3.0 km/h 미만)·위험 없음·ISOFIX 없음일 때만 허용 | SWR-004 |
| A-06 | 3.0 km/h 미만으로 내려가도 자동 해제 없음 | SWR-003 |
| A-07 | override는 해당 쪽 `RELEASE`, 위험 FALSE 등까지 유지. 10,000 ms 이하 포함, 초과 시 다시 억제. DEGRADED 중 금지 | SWR-006 |
| A-08 | 충돌 해제는 시동 OFF까지 래치. 지연·타 그룹 무효와 무관 | SWR-007 |
| A-09 | PENDING은 출력에 영향 없음 | SWR-008 |
| A-10 | DEGRADED 동안 상위 규칙이 결정하지 않은 쪽은 직전 확정 출력 유지 | SWR-013 |
| A-11 | HTTP 엔드포인트 경로와 400 처리 | SWR-015 |
| A-12 | ISOFIX FALSE 전환 시 자동 해제 없음 | SWR-018 |
| A-13 | 우선순위 표 | SWR-019 |
| A-14 | 상태는 DEF-10 순서로 하나만 표시 | DEF-10, SWR-014 |
| A-15 | 시간은 ms 정수로 반올림해 비교 | DEF-04 |
| A-16 | 운전자 명령은 1회성 이벤트(연속 스냅샷의 같은 명령은 한 입력) | SWR-006 |
| A-17 | 1회 평가 처리 시간 10 ms 이하 | SWR-023 |

## 6. 범위 밖으로 둔 OEM 입력

| 항목 | 처리 |
|---|---|
| `gear` (IF-001) | 검증만 한다. 이를 사용하는 OEM 요구가 없다(질의 Q-11). |
| 7장 법규 후보 | 차량 수준 적용 후보이며 SW 요구로 파생하지 않는다. 충돌 후 해제 개념은 SWR-007로 반영. 개인정보 제약은 SWR-011, SWR-026으로 반영. |
| OEM-IF-005 적용 feedback | OEM 문서에 따라 범위 밖. |

## 7. 개정 이력

| 개정 | 일자 | 내용 |
|---|---|---|
| 0.1 | 2026-11-26 | 최초 작성 (SWR-001~021) |
| 0.2 | 2026-11-26 | 독립 검토 RV-01 결과 반영: 안전 입력 그룹 정의(DEF-08), 충돌 해제의 지연·무효 무관 적용, 입력 중단 감시(SWR-022), override 지속·종료 조건, 명령 1회성(DEF-09), 상태 결정 규칙(DEF-10), `priority_reason` 목록과 `notices` 분리, 처리 시간(SWR-023), 실행 환경(SWR-024), Web 화면(SWR-025), 입력 필드 제한(SWR-026), 시간 비교 ms 정수화 |
