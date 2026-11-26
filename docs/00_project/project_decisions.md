# 프로젝트 결정 기록

- 프로젝트: 전자식 차일드락 제어 SW (OEM 입력: OEM-SWR-001 Rev 1.0, 베이스라인 BL-OEM-1.0)
- 단계: 0. 착수
- 작성일: 2026-11-26

| ID | 결정 | 근거 | 영향 |
|---|---|---|---|
| D-01 | Python 3.12 호환으로 개발한다(`requires-python >= 3.12`, Ruff `target-version = py312`). 시험은 3.12(`.venv`)와 3.14(`.venv-py314`)에서 모두 실행한다. | OEM-SWR-001 3장이 실행 환경을 Python 3.12 PC/SIL로 지정. CLAUDE.md는 최신 버전 사용 → 3.12 호환을 유지하면서 최신 버전에서도 동작을 확인 | 3.13 이상 전용 문법·표준 라이브러리 사용 금지 |
| D-02 | Web 시뮬레이터·상태 조회 API는 Python 표준 라이브러리(`http.server`, `json`)로 구현한다. | 외부 패키지가 없으면 SBOM과 정적 분석 범위가 작고, OEM-IF-006(직렬화 실패 시 HTTP 500) 구현에 충분 | 런타임 의존성 0개. 개발 의존성은 pytest, pytest-cov, Ruff |
| D-03 | OEM 입력 문서(`OEM/`)는 git에 올리지 않는다(`.gitignore`). | 문서의 사용 조건이 교육 과정 밖 배포·공개를 금지하고, 저장소가 공개(PUBLIC) 상태 | OEM 원문은 로컬에서만 참조 |
| D-04 | 주석률·함수 순수 코드 줄 수는 `tools/quality_check.py`로 측정한다. 정의는 CLAUDE.md "소스코드 품질"을 따른다. | 두 기준을 자동으로 재는 기존 도구가 없음 | PR 전 `python -m tools.quality_check src tools` 통과 필수 |
| D-05 | 제품 패키지는 `src/child_lock/`(src 레이아웃), 시험은 `tests/`(단위 `tests/unit`, 통합 `tests/integration`, 도구 `tests/tools`)에 둔다. | 설치 없이 시험 가능(`pythonpath` 설정), 제품 코드와 도구 분리 | 커버리지 측정 대상: `src`, `tools` |
| D-06 | OEM 요구사항의 미정의·모순 사항은 1단계(요구사항 분석)에서 OEM 질의 목록과 임시 가정으로 관리한다. 임시 가정은 SWR에 "가정" 표시를 하고, OEM 답변 후 갱신한다. | 사용자 지시: 개발 계획의 권장 사항대로 진행 | 1단계 산출물에 질의 목록 포함 |
