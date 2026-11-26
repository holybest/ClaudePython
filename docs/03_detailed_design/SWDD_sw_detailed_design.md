# SW 상세 설계서 (SWDD)

| 항목 | 내용 |
|---|---|
| 문서 ID | SWDD-ECL-001 |
| 개정 | 0.2 (독립 검토 RV-05 결과 반영) |
| 입력 | SWRS-ECL-001 (BL-SWR-1.0), SWAD-ECL-001 (BL-SWA-1.0) |
| 목표 베이스라인 | BL-SWD-1.0 (게이트 G2) |
| 상태 | 초안 — 사용자 승인 대기 |
| 작성일 | 2026-11-26 |

## 1. 개요

### 1.1 목적
SWAD의 컴포넌트를 SW 유닛(모듈)과 함수로 나누고, 각 함수의 입력·출력·처리 절차·오류 처리를 구현 가능한 수준으로 정의한다. 4단계 구현과 단위 시험은 이 문서를 기준으로 한다.

### 1.2 설계 표기
- 처리 절차는 의사코드로 적는다. 실제 코드의 이름·순서와 일치시킨다.
- 시각은 초(float)로 보관하고, **두 시각의 차이**를 `diff_ms(a_s, b_s)`로 한 번만 ms 정수 반올림해 비교한다(DEF-04: 0.5 올림). 시각 자체를 각각 반올림하지 않는다.
- 모든 함수는 순환 복잡도 10 이하, 순수 코드 50줄 이하가 되도록 나눈다(CLAUDE.md).

### 1.3 SW 유닛

| 유닛 | 모듈 | 컴포넌트 | ASIL |
|---|---|---|---|
| SWU-01 | `child_lock/core/model.py` | SWC-01 도메인 모델 | B |
| SWU-02 | `child_lock/core/validation.py` | SWC-02 입력 검증 | B |
| SWU-03 | `child_lock/core/arbitration.py` | SWC-03 우선순위 판정 (순서·결과 조립) | B |
| SWU-04 | `child_lock/core/rules.py` | SWC-03 우선순위 판정 (규칙 1~9) | B |
| SWU-05 | `child_lock/core/controller.py` | SWC-04 컨트롤러 | B |
| SWU-06 | `child_lock/runtime/runtime.py` | SWC-10 안전 런타임 | B |
| SWU-07 | `child_lock/app/event_log.py` | SWC-06 결정 이력 | QM |
| SWU-08 | `child_lock/app/service.py` | SWC-07 응용 조립 | QM |
| SWU-09 | `child_lock/web/server.py` | SWC-08 Web API | QM |
| SWU-10 | `child_lock/web/__main__.py` | SWC-08 실행 진입점 | QM |
| SWU-11 | `child_lock/web/static/index.html` | SWC-09 Web 화면 | QM |

### 1.4 SWAD 대비 구체화 (변경 요청 CR-02)

다음은 아키텍처를 바꾸지 않는 구체화이지만, SWAD 본문과 표기가 달라 SWAD 개정 요청 CR-02로 기록한다.

| 항목 | SWAD | SWDD | 이유 |
|---|---|---|---|
| SWC-03 모듈 | `arbitration.py` 하나 | `arbitration.py` + `rules.py` | 규칙 9개를 한 모듈에 두면 모듈 크기·시험 단위가 커짐. 같은 컴포넌트·ASIL 안의 분할 |
| `EvalContext` | `snapshot \| None`, `now_s`, `is_tick`, `fresh`, `command_is_new` | `snapshot`(None 불가), `now_s`, `is_tick`, `validity`(freshness 반영본), `command_is_new` | 첫 스냅샷 전 tick은 별도 처리(`_initial_tick`)하므로 None 불필요. `fresh`는 `validity.freshness`로 표현 |

## 2. SWU-01 도메인 모델 (`core/model.py`)

### 2.1 열거형 (모두 `str` 기반 `Enum`, 값 = JSON 표기)

| 이름 | 값 |
|---|---|
| `LockOutput` | `LOCK`, `RELEASE` |
| `Side` | `left`, `right` |
| `CommandSide` | `left`, `right`, `all` |
| `Action` | `lock`, `unlock` |
| `CommandSource` | `physical_button`, `avn`, `voice`, `mobile_app` |
| `Gear` | `P`, `N`, `D`, `R` |
| `CrashStatus` | `NONE`, `PENDING`, `CONFIRMED` |
| `State` | `OFF`, `NORMAL`, `OVERRIDE`, `EMERGENCY`, `DEGRADED`, `FAULT` |
| `Validity` | `VALID`, `INVALID`, `STALE` |
| `PriorityReason` | `CRASH`, `SENSOR_FAULT`, `APPROACH_RISK`, `DEGRADED`, `IGNITION_OFF`, `FORCED_RELEASE`, `ISOFIX`, `AUTO_LOCK`, `DRIVER_COMMAND`, `NONE` |
| `ReasonCode` | `CRASH_CONFIRMED`, `W_SENSOR_FAULT`, `APPROACH_RISK`, `APPROACH_OVERRIDE`, `INPUT_INVALID`, `INPUT_STALE`, `IGNITION_OFF`, `FIRE`, `OVERTEMP`, `ADULT_PRESENT`, `ISOFIX`, `AUTO_LOCK_SPEED`, `DRIVER_LOCK`, `DRIVER_UNLOCK`, `NO_CHANGE` |
| `Notice` | `CRASH_PENDING`, `COMMAND_REJECTED`, `DRIVER_UNLOCK_REJECTED`, `UNLOCK_SUPPRESSED` (정의 순서 = 출력 순서) |

`REASON_PRIORITY: Mapping[ReasonCode, PriorityReason]`은 SWRS 4장 표 그대로의 N:1 매핑이다(SWR-014).

### 2.2 상수

| 이름 | 값 | 근거 |
|---|---|---|
| `SPEED_MIN_KPH`, `SPEED_MAX_KPH` | 0.0, 300.0 | OEM-IF-001 |
| `AUTO_LOCK_SPEED_KPH` | 3.0 | SWR-003, 004 |
| `STALE_LIMIT_MS` | 200 | SWR-013, 022 |
| `OVERRIDE_WINDOW_MS` | 10000 | SWR-006 |
| `COMMAND_NOTICES` | `{COMMAND_REJECTED, DRIVER_UNLOCK_REJECTED, UNLOCK_SUPPRESSED}` | tick에서 제외(SWAD 3.2) |

### 2.3 데이터 타입 (모두 `@dataclass(frozen=True, slots=True)`)

| 타입 | 필드 | 메서드 |
|---|---|---|
| `SidePair[T]` (Generic) | `left: T`, `right: T` | `get(side) -> T`, `replace(side, value) -> SidePair[T]` |
| `DriverCommand` | `side: CommandSide`, `action: Action`, `source: CommandSource` | `covers(side: Side) -> bool` (`all`이거나 같은 쪽) |
| `ForcedRelease` | `fire: bool`, `overtemp: bool`, `adult: bool` | – |
| `InputValidity` | `if_001`, `if_002`, `if_003`, `if_004`, `if_007`, `if_008`, `if_009`, `freshness`: 모두 `Validity` | `safety_abnormal() -> bool`: `freshness`가 `STALE`이거나 `if_002`/`if_003`/`if_009` 중 `VALID`가 아닌 것이 있으면 참(DEF-08). `as_dict() -> dict[str, str]`: 키 `"IF-001"`…`"IF-009"`, `"FRESHNESS"` |
| `VehicleSnapshot` | `speed_kph: float \| None`, `gear: Gear \| None`, `source_timestamp_s: float \| None`, `crash_status: CrashStatus \| None`, `approach_risk: SidePair[bool] \| None`, `command: DriverCommand \| None`, `forced_release: ForcedRelease \| None`, `isofix: SidePair[bool] \| None`, `ignition_on: bool \| None`, `sensor_fault: bool \| None`, `validity: InputValidity` | – |
| `EvalContext` | `snapshot: VehicleSnapshot`, `now_s: float`, `is_tick: bool`, `validity: InputValidity`(freshness 반영본), `command_is_new: bool` | – |
| `DoorGuard` | `suppressed_at_s: float \| None`, `override_active: bool` | 모듈 상수 `IDLE_GUARD = DoorGuard(None, False)` |
| `CoreState` | `outputs: SidePair[LockOutput]`, `crash_latched: bool`, `doors: SidePair[DoorGuard]`, `last_snapshot: VehicleSnapshot \| None`, `last_now_s: float \| None` | – |
| `Decision` | `lock_left`, `lock_right: LockOutput`, `state: State`, `input_validity: InputValidity`, `priority_reason: PriorityReason`, `reason_code: ReasonCode`, `notices: tuple[Notice, ...]`, `timestamp_s: float` | – |

### 2.4 함수

| 함수 | 처리 |
|---|---|
| `diff_ms(a_s: float, b_s: float) -> int` | `math.floor((a_s - b_s) * 1000 + 0.5)` (DEF-04) |
| `initial_state() -> CoreState` | 출력 좌·우 `RELEASE`, 래치 거짓, 문 가드 `IDLE_GUARD`, 직전 스냅샷 없음, 직전 시각 없음(DEF-06) |
| `all_invalid() -> InputValidity` | 8개 키 모두 `INVALID` |
| `initial_decision(now_s: float) -> Decision` | 출력 좌·우 `RELEASE`, `OFF`, `all_invalid()`, `NONE`/`NO_CHANGE`, 알림 없음, `timestamp_s = now_s` (DEF-06) |

## 3. SWU-02 입력 검증 (`core/validation.py`)

시각과 무관한 형식·범위·enum만 검사한다. 미래 시각과 freshness는 SWU-05가 판단한다(tick에서도 같은 계산이 필요하므로).

### 3.1 공통 판정

| 함수 | 처리 |
|---|---|
| `_as_float(v) -> float \| None` | `type(v) is float`: `math.isfinite(v)`이면 `v`, 아니면 `None`. `type(v) is int`: `float(v)`(실패 `OverflowError` → `None`). 그 외(bool 포함) `None`. 결과도 유한해야 한다 |
| `_is_bool(v) -> bool` | `type(v) is bool` |
| `_enum_value(enum_cls, v) -> Enum \| None` | `v`가 `str`이고 enum 값에 있으면 그 멤버, 아니면 `None` |

### 3.2 그룹 검증 함수
각 함수는 `(값들, Validity)`를 반환한다. 키 누락이나 형식·범위 오류이면 그룹 전체를 `INVALID`로 하고 값은 `None`이다.

| 함수 | 입력 키 | 유효 조건 | 근거 |
|---|---|---|---|
| `_validate_motion(raw)` | `vehicle_speed_kph`, `gear` | `_as_float`가 값을 주고 0.0 ≤ v ≤ 300.0, 기어가 `Gear` 값 | IF-001 |
| `_validate_timestamp(raw)` | `source_timestamp_s` | `_as_float`가 값을 주고 ≥ 0.0. 무효면 `None`(freshness가 STALE이 됨) | IF-001, SWAD 2.3 |
| `_validate_crash(raw)` | `crash_status` | `CrashStatus` 값 | IF-002 |
| `_validate_side_pair(raw, left_key, right_key)` | 두 bool 키 | 둘 다 bool | IF-003, IF-008 |
| `_validate_command(raw)` | `command` | 키 없음 또는 `None` → (명령 없음, `VALID`). dict이고 `side`·`action`·`source`가 모두 enum 값 → (`DriverCommand`, `VALID`). 그 외 → (`None`, `INVALID`) | IF-004, SWR-002 |
| `_validate_forced(raw)` | `fire_detected`, `overtemperature_detected`, `adult_present` | 셋 다 bool | IF-007 |
| `_validate_ignition(raw)` | `ignition_on`, `sensor_fault` | 둘 다 bool | IF-009 |

### 3.3 `validate(raw: Mapping[str, object]) -> VehicleSnapshot`
```
if raw is not a Mapping: raw = {}                    # 모든 그룹 누락 → INVALID
motion  = _validate_motion(raw)
ts      = _validate_timestamp(raw)
crash   = _validate_crash(raw)
risk    = _validate_side_pair(raw, "rear_left_approach_risk", "rear_right_approach_risk")
command = _validate_command(raw)
forced  = _validate_forced(raw)
isofix  = _validate_side_pair(raw, "isofix_left", "isofix_right")
ign     = _validate_ignition(raw)
freshness = VALID if ts is not None else STALE       # 시각 기준 판단은 SWU-05에서 추가
return VehicleSnapshot(..., validity=InputValidity(...))
```
- 정의되지 않은 키는 무시한다. 거절은 Web 계층(SWU-09) 책임이다(SWR-026).
- 예외를 던지지 않는다(큰 정수, NaN, 무한대 포함).

## 4. SWU-05 컨트롤러 (`core/controller.py`)

### 4.1 클래스 `ChildLockController`

| 멤버 | 설명 |
|---|---|
| `_state: CoreState` | `initial_state()`로 시작 |
| `_last: Decision` | `initial_decision(0.0)` |
| `evaluate_snapshot(raw, now_s) -> Decision` | `return self._evaluate(validate(raw), now_s, is_tick=False)` |
| `evaluate_tick(now_s) -> Decision` | `last_snapshot`이 없으면 `self._initial_tick(now_s)`, 있으면 `self._evaluate(last_snapshot, now_s, is_tick=True)` |
| `last_decision` (property) | `self._last` |

### 4.2 `_evaluate(snapshot, now_s, is_tick) -> Decision`
```
context = build_context(snapshot, now_s, is_tick, self._state)
state   = reset_on_ignition_off(self._state, context)
decision, next_state = arbitrate(context, state)
next_state = replace(next_state,
                     last_snapshot = snapshot,
                     last_now_s    = latest_time(self._state.last_now_s, now_s))
self._state = next_state      # 판정이 모두 끝난 뒤 한 번에 교체 (예외 시 변경 없음)
self._last  = decision
return decision
```

### 4.3 `_initial_tick(now_s) -> Decision` (메서드)
`decision = initial_decision(now_s)`; `self._state = replace(self._state, last_now_s = latest_time(...))`; `self._last = decision`; `return decision`. (DEF-06, SWAD 3.2)

### 4.4 보조 함수 (모듈 수준 순수 함수)

| 함수 | 처리 | 근거 |
|---|---|---|
| `is_fresh(ts_s, now_s, last_now_s) -> bool` | `ts_s is None` → 거짓. `last_now_s is not None and now_s < last_now_s`(시각 역행) → 거짓. `age = diff_ms(now_s, ts_s)`; `age < 0`(미래) → 거짓; `age > STALE_LIMIT_MS` → 거짓. 그 외 참 | SWR-013, 022, DEF-04 |
| `is_new_command(snapshot, is_tick, previous) -> bool` | `is_tick` → 거짓. `snapshot.command is None` → 거짓. `previous is None or previous.command != snapshot.command` → 참. 그 외 거짓 | DEF-09 |
| `build_context(snapshot, now_s, is_tick, state) -> EvalContext` | `fresh = is_fresh(snapshot.source_timestamp_s, now_s, state.last_now_s)`; `validity = replace(snapshot.validity, freshness = VALID if fresh else STALE)`; `command_is_new = is_new_command(snapshot, is_tick, state.last_snapshot)` | SWAD 3.3 |
| `ignition_off_effective(context) -> bool` | `v = context.validity`; `v.if_009 == VALID` 그리고 `snapshot.ignition_on is False` 그리고 `snapshot.sensor_fault is False` 그리고 `not v.safety_abnormal()` | SWR-020, 019 (5.3 해설) |
| `reset_on_ignition_off(state, context) -> CoreState` | `ignition_off_effective(context)`이면 `crash_latched = False`, 문 가드 둘 다 `IDLE_GUARD`. 아니면 그대로 | SWR-020 |
| `latest_time(last, now) -> float` | `last is None` → `now`, 아니면 `max(last, now)` (역행 후에도 기준 시각 유지) | SWAD 6.1 |

**시동 OFF 초기화 조건 해설**: SWR-020의 초기화는 순위 5(시동 OFF) 규칙의 효과이다. 상위 규칙인 센서 고장(순위 2)이나 안전 입력 이상(순위 4)이 활성이면 순위 5가 적용되지 않으므로 초기화도 하지 않는다. 이렇게 하면 지연(STALE) 데이터의 `ignition_on = FALSE`로 ASIL B 충돌 래치가 풀리지 않는다(검토 D-08).

## 5. SWU-03 우선순위 판정 (`core/arbitration.py`)

### 5.1 중간 결과 `Resolution` (frozen)

| 필드 | 설명 |
|---|---|
| `outputs: SidePair[LockOutput \| None]` | 결정된 쪽만 값, 미결정은 `None` |
| `deciders: SidePair[PriorityReason \| None]` | 그 쪽을 결정한 규칙 |
| `reason: tuple[PriorityReason, ReasonCode] \| None` | 처음으로 쪽을 결정한 규칙의 이유(규칙이 순위 순으로 실행되므로 최상위) |
| `notices: frozenset[Notice]` | 수집한 알림 |
| `doors: SidePair[DoorGuard]` | 갱신 중인 문 가드 |
| `crash_latched: bool` | 갱신 중인 래치 |

메서드(모두 새 `Resolution` 반환): `start(doors, crash_latched)`(클래스 메서드), `decide(side, output, reason_pair)`(미결정인 쪽만 결정, `reason`이 비어 있으면 설정), `is_open(side) -> bool`, `add_notice(n)`, `with_door(side, guard)`, `with_reason(reason_pair)`(이유 덮어쓰기), `with_latch(value)`.

### 5.2 `arbitrate(context, state) -> tuple[Decision, CoreState]`
```
res = Resolution.start(doors = update_guards(context, state.doors),
                       crash_latched = state.crash_latched)
for rule in RULES:                  # SWU-04, 순위 1 → 9 순서의 튜플
    res = rule(context, state, res)
outputs = fill_undecided(res.outputs, state.outputs)   # 미결정 쪽 = 직전 확정 출력
reason  = res.reason or (PriorityReason.NONE, ReasonCode.NO_CHANGE)
decision = Decision(
    lock_left = outputs.left, lock_right = outputs.right,
    state = compute_state(context, res),
    input_validity = context.validity,                 # freshness 반영본
    priority_reason = reason[0], reason_code = reason[1],
    notices = ordered_notices(res.notices, context.is_tick),
    timestamp_s = context.now_s)
next_state = CoreState(outputs, res.crash_latched, res.doors,
                       state.last_snapshot, state.last_now_s)
return decision, next_state
```

| 함수 | 처리 | 근거 |
|---|---|---|
| `update_guards(context, doors) -> SidePair[DoorGuard]` | `v = context.validity`. 쪽마다: `v.if_003 == VALID`이고 해당 쪽 위험 FALSE → `IDLE_GUARD`. 아니고 `v.safety_abnormal()` 또는 (`v.if_009 == VALID`이고 `sensor_fault`) → `override_active = False`(억제 시각 유지). 그 외 그대로 | SWR-006, SWAD 3.4 |
| `fill_undecided(decided, previous) -> SidePair[LockOutput]` | 쪽마다 `decided`가 `None`이면 `previous` 값 | SWR-013, 021 |
| `ordered_notices(notices, is_tick) -> tuple[Notice, ...]` | `is_tick`이면 `COMMAND_NOTICES` 제거. `Notice` 정의 순서로 정렬 | SWAD 3.2 |
| `compute_state(context, res) -> State` | `v = context.validity`. `res.crash_latched` → `EMERGENCY`; `v.if_009 == VALID`이고 `sensor_fault` → `FAULT`; `v.safety_abnormal()` → `DEGRADED`; `res.doors` 중 `override_active` → `OVERRIDE`; `v.if_009 == VALID`이고 `not ignition_on` → `OFF`; 그 외 `NORMAL` | DEF-10 |

## 6. SWU-04 규칙 (`core/rules.py`)

모든 규칙의 형식: `rule_x(context, state, res) -> Resolution`. 규칙은 **미결정 쪽만** 결정한다. 아래에서 `snap = context.snapshot`, `v = context.validity`, `prev = state.outputs`.

| 순위 | 함수 | 활성 조건 | 처리 | 이유 | 근거 |
|---|---|---|---|---|---|
| 1 | `rule_crash` | (`v.if_002 == VALID`이고 `snap.crash_status == CONFIRMED`) 또는 `res.crash_latched` | `with_latch(True)`, 문 가드 둘 다 `IDLE_GUARD`, 좌·우 `RELEASE`. 별도로 `v.if_002 == VALID`이고 `PENDING`이면 알림 `CRASH_PENDING`(활성 여부와 무관) | `CRASH` / `CRASH_CONFIRMED` | SWR-007, 008. freshness와 무관 |
| 2 | `rule_sensor_fault` | `v.if_009 == VALID`이고 `snap.sensor_fault` | 미결정 쪽 = `prev` 값 | `SENSOR_FAULT` / `W_SENSOR_FAULT` | SWR-021 |
| 3 | `rule_approach_risk` | `v.if_003 == VALID`이고 해당 쪽 위험 TRUE (쪽마다) | 6.1 | `APPROACH_RISK` / `APPROACH_RISK` 또는 `APPROACH_OVERRIDE` | SWR-005, 006, 009 |
| 4 | `rule_degraded` | `v.safety_abnormal()` | 미결정 쪽 = `prev` 값 | `DEGRADED` / `INPUT_INVALID`(IF-002·003·009 중 `INVALID` 있음) 또는 `INPUT_STALE` | SWR-013, 022 |
| 5 | `rule_ignition_off` | `v.if_009 == VALID`이고 `snap.ignition_on is False` | 미결정 쪽 `RELEASE` | `IGNITION_OFF` / `IGNITION_OFF` | SWR-020 |
| 6 | `rule_forced_release` | `v.if_007 == VALID`이고 셋 중 하나 TRUE | 미결정 쪽 `RELEASE` | `FORCED_RELEASE` / `FIRE` > `OVERTEMP` > `ADULT_PRESENT` 중 처음 TRUE | SWR-017 |
| 7 | `rule_isofix` | `v.if_008 == VALID`이고 해당 쪽 TRUE (쪽마다) | 그 쪽이 미결정이면 `LOCK` | `ISOFIX` / `ISOFIX` | SWR-018, 009 |
| 8 | `rule_auto_lock` | `v.if_001 == VALID`이고 `snap.speed_kph >= 3.0` | 미결정 쪽 `LOCK` | `AUTO_LOCK` / `AUTO_LOCK_SPEED` | SWR-003 |
| 9 | `rule_driver_command` | 6.2 | 6.2 | `DRIVER_COMMAND` / `DRIVER_LOCK`·`DRIVER_UNLOCK` | SWR-001, 002, 004 |

`RULES = (rule_crash, rule_sensor_fault, rule_approach_risk, rule_degraded, rule_ignition_off, rule_forced_release, rule_isofix, rule_auto_lock, rule_driver_command)` — 순서가 곧 SWR-019 우선순위이다.

### 6.1 `rule_approach_risk`
```
def _unlock_requested(context, side) -> bool:
    cmd = context.snapshot.command
    return (context.command_is_new and cmd is not None
            and cmd.action == UNLOCK and cmd.covers(side))

def _window_ok(req_s, t0_s) -> bool:                       # 0 ≤ 경과 ≤ 10,000 ms
    elapsed = diff_ms(req_s, t0_s)
    return 0 <= elapsed <= OVERRIDE_WINDOW_MS

def _risk_side(context, res, side) -> Resolution:
    if not res.is_open(side) or not risk(side): return res
    guard = res.doors.get(side)
    if guard.override_active:                               # override 지속 (종료는 update_guards)
        return res.decide(side, RELEASE, (APPROACH_RISK, APPROACH_OVERRIDE))
    if _unlock_requested(context, side):
        fresh = context.validity.freshness == VALID
        req_s = context.snapshot.source_timestamp_s if fresh else None
        if (req_s is not None and guard.suppressed_at_s is not None
                and _window_ok(req_s, guard.suppressed_at_s)
                and not context.validity.safety_abnormal()):
            res = res.with_door(side, DoorGuard(guard.suppressed_at_s, True))
            return res.decide(side, RELEASE, (APPROACH_RISK, APPROACH_OVERRIDE))
        res = res.with_door(side, DoorGuard(req_s, False))  # 첫 요청·창 밖·지연: t0 기록(지연이면 None)
        res = res.add_notice(UNLOCK_SUPPRESSED)
    return res.decide(side, LOCK, (APPROACH_RISK, APPROACH_RISK))

def rule_approach_risk(context, state, res) -> Resolution:
    if context.validity.if_003 != VALID: return res
    res = _risk_side(context, res, LEFT)
    res = _risk_side(context, res, RIGHT)
    if any(res.deciders.get(s) == APPROACH_RISK and res.doors.get(s).override_active
           for s in (LEFT, RIGHT)):
        res = res.with_reason((APPROACH_RISK, APPROACH_OVERRIDE))
    return res
```
- **불변식**: 규칙 3이 실행될 때 `res.reason`을 설정할 수 있는 상위 규칙은 1·2뿐이고, 둘은 활성 시 좌·우를 모두 결정한다. 따라서 규칙 3이 어느 쪽이든 결정했다면 이유는 규칙 3의 것이며, `with_reason`으로 덮어써도 상위 규칙의 이유를 지우지 않는다.
- 경과 시간이 음수이면(억제 시각보다 이른 요청) override가 아니라 새 첫 요청으로 다시 억제한다(검토 D-02).
- 지연(STALE) 스냅샷의 시각은 억제 시각으로 기록하지 않는다(`None`).

### 6.2 `rule_driver_command`
```
if context.is_tick: return res
if v.if_004 == INVALID: return res.add_notice(COMMAND_REJECTED)
if not context.command_is_new: return res
cmd = snap.command
for side in (LEFT, RIGHT):
    if not cmd.covers(side): continue
    if cmd.action == LOCK:
        if res.is_open(side): res = res.decide(side, LOCK, (DRIVER_COMMAND, DRIVER_LOCK))
    else:
        res = _unlock_side(context, res, side)
return res
```
`_unlock_side(context, res, side)`: 아래를 모두 만족하면 `decide(side, RELEASE, (DRIVER_COMMAND, DRIVER_UNLOCK))`. 아니면 그 쪽 결정 규칙이 `APPROACH_RISK`가 아닐 때만 알림 `DRIVER_UNLOCK_REJECTED`(규칙 3이 이미 `UNLOCK_SUPPRESSED` 또는 override로 처리했으므로 중복 방지).
- (a) `v.if_001 == VALID`이고 `speed_kph < 3.0`
- (b) `v.if_003 == VALID`이고 해당 쪽 위험 FALSE
- (c) `v.if_008 == VALID`이고 해당 쪽 ISOFIX FALSE
- (d) `res.is_open(side)`

잠금 명령이 상위 규칙으로 결정된 쪽에 들어오면 알림 없이 적용하지 않는다. override 중인 쪽의 잠금 명령도 같다(변경 요청 CR-03 참고).

### 6.3 판정 결과 예 (단위 시험 기대값의 기준)
모든 행은 시동 ON, 모든 입력 유효·신선, 충돌 NONE이 기본이며 표에 적은 것만 다르다.

| # | 입력 요지 | 좌 | 우 | 상태 | `priority_reason` / `reason_code` | 알림 |
|---|---|---|---|---|---|---|
| 1 | 정지, 좌 해제 명령 (직전 좌·우 LOCK) | RELEASE | LOCK | NORMAL | DRIVER_COMMAND / DRIVER_UNLOCK | – |
| 2 | 차속 3.0, 좌 해제 명령 | LOCK | LOCK | NORMAL | AUTO_LOCK / AUTO_LOCK_SPEED | DRIVER_UNLOCK_REJECTED |
| 3 | 좌 위험 TRUE, 좌 해제 명령(첫 요청) | LOCK | 직전 | NORMAL | APPROACH_RISK / APPROACH_RISK | UNLOCK_SUPPRESSED |
| 4 | 3 이후 명령 없는 스냅샷을 1회 받고, 5,000 ms 뒤 좌 해제 재요청 | RELEASE | 직전 | OVERRIDE | APPROACH_RISK / APPROACH_OVERRIDE | – |
| 5 | 3 이후 같은 좌 해제 명령이 들어 있는 스냅샷만 계속 수신(사이에 tick만 경과), 5,000 ms 뒤 | LOCK | 직전 | NORMAL | APPROACH_RISK / APPROACH_RISK | – (새 입력 아님) |
| 6 | 3 이후 명령 없는 스냅샷, 10,001 ms 뒤 재요청 | LOCK | 직전 | NORMAL | APPROACH_RISK / APPROACH_RISK | UNLOCK_SUPPRESSED (t0 갱신) |
| 7 | CONFIRMED + 센서 고장 + 좌 위험 | RELEASE | RELEASE | EMERGENCY | CRASH / CRASH_CONFIRMED | – |
| 8 | 센서 고장 + 좌 위험 (직전 좌·우 RELEASE) | RELEASE | RELEASE | FAULT | SENSOR_FAULT / W_SENSOR_FAULT | – |
| 9 | 지연 201 ms + 좌 위험 (직전 RELEASE) | LOCK | RELEASE | DEGRADED | APPROACH_RISK / APPROACH_RISK | – |
| 10 | IF-007만 무효, 차속 3.0 | LOCK | LOCK | NORMAL | AUTO_LOCK / AUTO_LOCK_SPEED | – |
| 11 | 시동 OFF + 좌 ISOFIX | RELEASE | RELEASE | OFF | IGNITION_OFF / IGNITION_OFF | – |
| 12 | 화재 + 우 ISOFIX | RELEASE | RELEASE | NORMAL | FORCED_RELEASE / FIRE | – |
| 13 | 충돌 래치 상태에서 지연 스냅샷 + 시동 OFF | RELEASE | RELEASE | EMERGENCY | CRASH / CRASH_CONFIRMED | – (래치 유지) |

Web 화면은 명령을 보낸 직후 명령 없는 스냅샷을 1회 더 보낸다(12장). 따라서 화면에서 같은 명령 버튼을 다시 누르면 4번 행처럼 새 입력이 된다.

## 7. SWU-06 안전 런타임 (`runtime/runtime.py`)

| 요소 | 처리 | 근거 |
|---|---|---|
| `MonotonicClock` | 생성 시 `self._origin = time.monotonic()`. `__call__() -> float`: `time.monotonic() - self._origin` | SWAD 4.2, 6.1 |
| `SafetyRuntime.__init__(controller, clock, on_decision=None, tick_period_s=0.05)` | `threading.Lock`, `threading.Event`(정지), 스레드 핸들 `None`, `tick_errors = 0`, `callback_errors = 0` | – |
| `evaluate_snapshot(raw) -> Decision` | `with self._lock: now = clock(); d = controller.evaluate_snapshot(raw, now); self._notify(d)`; `return d`. 컨트롤러 예외는 호출자에게 전달(코어 상태 변경 없음) | SWAD 3.1 |
| `tick() -> Decision` | 위와 같고 `evaluate_tick(now)` 호출 | SWR-022 |
| `now() -> float` | `clock()` | SWAD 4.4 |
| `last_decision() -> Decision` | `with self._lock: return controller.last_decision` | – |
| `_notify(d)` | `on_decision`이 있으면 호출. 예외는 잡아서 `callback_errors += 1` | SWAD 6.1 |
| `start()` | 스레드가 살아 있으면 무시. 아니면 정지 이벤트 `clear()` 후 데몬 스레드로 `_tick_loop` 시작 | 검토 D-10 |
| `_tick_loop()` | `while not stop.wait(period): try: tick() except Exception: tick_errors += 1` | SWAD 6.1, 6.2 |
| `stop()` | 정지 이벤트 설정, 스레드가 있으면 `join(timeout=1.0)` | – |

## 8. SWU-07 결정 이력 (`app/event_log.py`)

| 요소 | 처리 | 근거 |
|---|---|---|
| `Event` (frozen) | `event_id: int`, `timestamp_s: float`, `lock_left`, `lock_right`, `state`, `priority_reason`, `reason_code`, `notices` | SWR-011 |
| `EventLog.__init__(capacity=100)` | `collections.deque(maxlen=capacity)`, `_next_id = 1`, `threading.Lock` | SWR-012 |
| `append(decision) -> Event` | 잠금 아래에서 `Event` 생성(허용 필드만 복사), `_next_id += 1`, deque 추가(가득 차면 가장 오래된 것 자동 삭제) | SWR-010, 012 |
| `events() -> tuple[Event, ...]` | 잠금 아래에서 오래된 순 튜플 생성 | SWR-012, 검토 D-10 |

파일·DB에 쓰지 않는다. CR-01이 승인되면 기록 조건 함수를 추가한다(현재는 모두 기록).

## 9. SWU-08 응용 조립 (`app/service.py`)

| 요소 | 처리 |
|---|---|
| `ChildLockService.__init__(runtime, log)` | 보관 |
| `submit_snapshot(raw) -> Decision` | `runtime.evaluate_snapshot(raw)` |
| `status() -> Decision` | `runtime.tick()` (조회 시 tick, SWR-022) |
| `events() -> tuple[Event, ...]` | `log.events()` |
| `now() -> float` | `runtime.now()` |
| `start()` / `stop()` | `runtime.start()` / `runtime.stop()` (Web이 런타임을 직접 호출하지 않도록, DEP-05) |
| `create_service(clock=None) -> ChildLockService` | `EventLog()`, `ChildLockController()`, `SafetyRuntime(controller, clock or MonotonicClock(), on_decision=log.append)` 생성·연결 |

## 10. SWU-09 Web API (`web/server.py`)

### 10.1 요청 처리

| 함수 | 처리 | 근거 |
|---|---|---|
| `SNAPSHOT_KEYS`, `COMMAND_KEYS` | SWAD 4.4 표의 키 집합(`frozenset`) | SWR-026 |
| `RequestError(Exception)` | 400 응답용 | – |
| `_reject_constant(name)` | 항상 `RequestError` (`json.loads(parse_constant=...)`: `NaN`, `Infinity`, `-Infinity` 거절) | SWAD 4.3 |
| `_parse_float(text)` | `float(text)`가 유한하지 않으면(`1e400` 등) `RequestError`, 아니면 그 값 (`json.loads(parse_float=...)`) | 검토 D-04 |
| `parse_snapshot(body: bytes, now_s: float) -> dict[str, object]` | UTF-8 디코딩 실패·JSON 오류 → `RequestError`. 최상위가 dict가 아님 → `RequestError`. `SNAPSHOT_KEYS` 밖의 키 → `RequestError`. `command`가 dict이면 `COMMAND_KEYS` 밖의 키 → `RequestError`. `source_timestamp_s`가 없으면 `now_s`로 채움 | SWR-015, 026 |
| `MAX_BODY_BYTES = 65536` | `Content-Length`가 없거나, 정수가 아니거나, 이를 넘으면 `RequestError` | – |

큰 정수는 JSON 파싱을 통과하지만 코어의 `_as_float`가 무효로 판정한다(예외 없음).

### 10.2 응답 직렬화

| 함수 | 처리 |
|---|---|
| `decision_to_dict(d) -> dict` | SWAD 4.3 `Decision` JSON 필드. enum은 `.value`, `input_validity`는 `as_dict()`, `notices`는 값 목록 |
| `event_to_dict(e) -> dict` | SWR-011 8개 필드만 |
| `to_json_bytes(obj) -> bytes` | `json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")`. `TypeError`·`ValueError`는 `SerializationError`로 변환 |

### 10.3 HTTP 처리 (`ChildLockHandler(BaseHTTPRequestHandler)`)

| 경로 | 처리 | 오류 |
|---|---|---|
| `GET /` | `static/index.html`을 `text/html; charset=utf-8`로 응답 | 파일 읽기 실패 500 |
| `GET /api/status` | `to_json_bytes(decision_to_dict(service.status()))` | 예외 500 |
| `GET /api/events` | 이벤트 목록 직렬화 | 예외 500 |
| `POST /api/snapshot` | `parse_snapshot` → `service.submit_snapshot` → 직렬화 | `RequestError` 400, 그 외 예외 500 |
| 그 외 | 404 | – |

- 오류 본문: `{"error": "<메시지>"}`. 500 본문은 내부 정보 없이 고정 문구.
- 서비스 객체는 서버 인스턴스 속성(`server.service`)으로 전달한다(전역 변수 금지).
- 요청 본문은 로그에 남기지 않는다(개인정보, SWR-026).
- `make_server(service, host="127.0.0.1", port=8000) -> ThreadingHTTPServer`.

## 11. SWU-10 실행 진입점 (`web/__main__.py`)
`python -m child_lock.web [--host H] [--port P]`: `service = create_service()` → `service.start()` → `make_server(service, ...).serve_forever()`. 종료(Ctrl+C) 시 `service.stop()`, `server.server_close()`. 런타임을 직접 호출하지 않는다(DEP-05).

## 12. SWU-11 Web 화면 (`web/static/index.html`)
- 입력 영역: 차속(숫자), 기어(선택), 충돌 상태(선택), 좌·우 접근위험, 화재·과온·성인, 좌·우 ISOFIX, 시동, 센서 고장(체크박스). "스냅샷 전송" 버튼.
- 명령 영역: side × action × source 선택과 "명령 전송" 버튼. 누르면 현재 입력값 + 명령으로 스냅샷 1회를 보내고, 이어서 명령 없는 같은 입력값으로 1회 더 보낸다(1회성 이벤트, DEF-09, 6.3 #4).
- 상태 영역: `GET /api/status`를 500 ms마다 조회해 좌·우 출력, 상태, 유효성, 이유, 알림 표시.
- 이력 영역: `GET /api/events` 표(오래된 순).
- 외부 스크립트·폰트를 쓰지 않는다(오프라인 동작).

## 13. 요구사항 → 유닛·함수 추적

| SWR | 유닛 · 함수 |
|---|---|
| SWR-001 | SWU-04 `rule_driver_command`, SWU-01 `DriverCommand.covers` |
| SWR-002 | SWU-02 `_validate_command`, SWU-04 `rule_driver_command` |
| SWR-003 | SWU-04 `rule_auto_lock` |
| SWR-004 | SWU-04 `_unlock_side` |
| SWR-005 | SWU-04 `rule_approach_risk`, `_risk_side` |
| SWR-006 | SWU-04 `_risk_side`, `_unlock_requested`, `_window_ok`, SWU-03 `update_guards`, `compute_state`, SWU-04 `rule_crash`, SWU-05 `is_new_command`, `reset_on_ignition_off` |
| SWR-007 | SWU-02 `_validate_crash`, SWU-04 `rule_crash`, SWU-03 `compute_state`, SWU-05 `reset_on_ignition_off` |
| SWR-008 | SWU-04 `rule_crash` |
| SWR-009 | SWU-04 `_risk_side`, `rule_isofix`, `rule_driver_command` |
| SWR-010 | SWU-07 `EventLog.append`, SWU-06 `_notify` |
| SWR-011 | SWU-07 `Event`, SWU-09 `event_to_dict` |
| SWR-012 | SWU-07 `EventLog` |
| SWR-013 | SWU-02 `validate`·그룹 함수·`_as_float`, SWU-01 `InputValidity.safety_abnormal`, SWU-05 `is_fresh`, `build_context`, SWU-04 `rule_degraded`, SWU-03 `compute_state` |
| SWR-014 | SWU-01 `Decision`, `REASON_PRIORITY`, SWU-03 `arbitrate`, `compute_state`, SWU-09 `decision_to_dict` |
| SWR-015 | SWU-09 `ChildLockHandler`, `parse_snapshot`, `to_json_bytes` |
| SWR-016 | SWU-02~05 (시각은 인자로만, 전역 상태 없음) |
| SWR-017 | SWU-04 `rule_forced_release` |
| SWR-018 | SWU-04 `rule_isofix`, `_unlock_side` |
| SWR-019 | SWU-04 `RULES`, SWU-03 `arbitrate`, `Resolution.decide` |
| SWR-020 | SWU-05 `ignition_off_effective`, `reset_on_ignition_off`, SWU-04 `rule_ignition_off`, `rule_crash`(재래치), SWU-03 `compute_state` |
| SWR-021 | SWU-04 `rule_sensor_fault`, SWU-03 `compute_state`, `update_guards` |
| SWR-022 | SWU-05 `evaluate_tick`, `is_fresh`, SWU-04 `rule_degraded`, SWU-06 `tick`, `start`, `_tick_loop`, SWU-08 `status` |
| SWR-023 | SWU-02~05 (반복 횟수 상한이 고정된 처리: 규칙 9개 × 좌우 2쪽, 재귀 없음) |
| SWR-024 | 전체 (표준 라이브러리만) |
| SWR-025 | SWU-11, SWU-09 `GET /` |
| SWR-026 | SWU-09 `parse_snapshot` |

SWR 26건 모두 하나 이상의 함수로 추적된다(26/26).

## 14. 단위 시험 방침 (4단계 입력)
- 시험 파일: `tests/unit/test_<모듈>.py`. 아키텍처 시험: `tests/architecture/`.
- ASIL B 유닛(SWU-01~06): 동치 분할, 경계값(차속 2.9/3.0/300.0/300.1, 지연 200/201 ms, override 경과 −1/0/10,000/10,001 ms, `diff_ms` 반올림 경계), 6.3 판정 표 전 행, 규칙 쌍 조합(SWR-019), 상태 전이(SWAD 3.4), 큰 정수·NaN·무한대 입력. 분기 커버리지 100%.
- QM 유닛(SWU-07~10): 요구 기반 시험과 분기 커버리지 100%. Web은 실제 `ThreadingHTTPServer`를 임의 포트로 띄워 시험한다.
- SWU-11(HTML)은 단위 시험 대상이 아니다. 통합·시스템 시험(Web)에서 확인한다.

## 15. 변경 요청

| ID | 대상 | 내용 | 상태 |
|---|---|---|---|
| CR-02 | SWAD | 1.4 표의 구체화(SWC-03 모듈 분할, `EvalContext` 필드)를 SWAD 본문에 반영 | 사용자 결정 대기 (구현은 SWDD 기준) |
| CR-03 | SWRS SWR-006 | override 중인 쪽에 운전자 잠금 명령이 들어오면 현재 정의상 무시된다(override는 위험 FALSE 등으로만 종료). 제안: 잠금 명령도 override 종료 조건에 추가해 그 쪽을 `LOCK`으로 한다(안전 방향) | 사용자 결정 대기 (결정 전까지 현재 정의대로 구현) |

## 16. 개정 이력

| 개정 | 일자 | 내용 |
|---|---|---|
| 0.1 | 2026-11-26 | 최초 작성 |
| 0.2 | 2026-11-26 | 독립 검토 RV-05 반영: 시간 차이 반올림(`diff_ms`), override 창 하한과 지연 시각 미기록, 명령 재입력 전제와 화면 동작, 큰 정수·무한대 처리, 서비스 `start/stop`, override 이유 의사코드, 모호성 해소, 시동 OFF 초기화 조건, SWAD 구체화 CR-02, 런타임 재시작·이력 잠금, 추적표 보완, CR-03 |
