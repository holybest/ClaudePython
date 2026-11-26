# build_workbook.py 입력 JSON 형식

```json
{
  "project": "BCM 차속 표시 SW",
  "basis_document": "SWRS_BCM_v1.3.docx",
  "environment": "HIL (dSPACE SCALEXIO), CANoe 16",
  "test_basis": [
    {
      "id": "SWRS-012",
      "title": "차속 0~250 km/h 표시",
      "category": "functional",
      "asil": "QM",
      "testable": true,
      "untestable_reason": ""
    }
  ],
  "test_cases": [
    {
      "id": "STC-F-001",
      "basis_ids": ["SWRS-012"],
      "category": "functional",
      "suggested": false,
      "objective": "차속 상한 경계값(250 km/h)에서 표시값 확인",
      "preconditions": "1. IGN ON\n2. 클러스터 초기화 완료(전원 인가 후 2 s 경과)",
      "inputs": "VehSpd (CAN 0x1A0) = 250 km/h",
      "procedure": "1. VehSpd = 250 송신 시작 (주기 10 ms)\n2. 300 ms 대기\n3. Disp_Speed 신호 확인",
      "expected": "Disp_Speed = 250, 송신 시작 후 300 ms 이내 반영",
      "pass_criteria": "Disp_Speed = 250 (허용오차 0)",
      "techniques": ["경계값 분석"],
      "environment": "",
      "asil": "",
      "priority": "High",
      "notes": ""
    }
  ],
  "pict_models": [
    {
      "name": "표시 모드 조합",
      "basis_ids": ["SWRS-020"],
      "model": "IGN: OFF, ACC, ON\nGear: P, R, N, D\n...",
      "options": "/o:2 /r:1",
      "result_tsv": "IGN\tGear\t...\nON\tD\t...",
      "test_case_ids": ["STC-F-010", "STC-F-011"]
    }
  ],
  "findings": [
    {
      "basis_id": "SWRS-015",
      "type": "모호",
      "description": "경고 지연 시간의 허용오차가 정의되지 않음",
      "proposal": "±20 ms 허용오차 명시 요청"
    }
  ],
  "summary_notes": ["페어와이즈: SWRS-020에 적용. 그 외 항목은 독립 파라미터 3개 미만이라 미적용."]
}
```

## 필드 설명

- `category`: `functional` 또는 `non-functional`. 테스트 케이스는 이 값에 따라 시트가 나뉜다.
- `suggested`: 베이시스에서 직접 도출되지 않고 추가로 제안한 케이스면 `true`. Excel에서 `구분 = 제안`.
- `testable: false`인 베이시스는 커버리지 분모에는 포함되지만 미커버로 보고된다. 반드시 `untestable_reason`과 `findings` 항목을 함께 쓴다.
- 줄바꿈은 `\n`. Excel 셀 안에서 줄바꿈된다.
- 선택 필드(`environment`, `asil`, `priority`, `notes`)가 모든 케이스에서 비어 있으면 해당 열은 생략된다.
- `findings.type` 예: `모호`, `누락`, `시험 불가`, `모순`, `기대 동작 정의 필요`, `요구사항 추가 필요`.

## 사용자 양식(--template)을 쓸 때

양식 xlsx의 헤더 행 열 이름을 JSON 필드에 연결하는 `column_map`을 추가한다. 키는 양식의 헤더 문자열, 값은 필드 이름이다.

```json
"column_map": {
  "TC No.": "id",
  "Requirement ID": "basis_ids",
  "Test Objective": "objective",
  "Precondition": "preconditions",
  "Test Input": "inputs",
  "Test Steps": "procedure",
  "Expected Result": "expected",
  "Test Method": "techniques",
  "Type": "suggested"
}
```

사용 가능한 필드: `id, basis_ids, suggested, objective, preconditions, inputs, procedure, expected, pass_criteria, techniques, environment, asil, priority, notes`.
목록 필드는 `, `로 이어지고, `suggested`는 `제안`/`기본`으로 쓰인다. 매핑되지 않은 양식 열은 비워 둔다.
양식에 기법·베이시스 ID 열이 없어 필수 항목을 담을 수 없으면 사용자에게 알리고 열 추가를 제안한다.
