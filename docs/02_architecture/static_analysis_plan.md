# 정적 분석 계획

| 항목 | 내용 |
|---|---|
| 문서 ID | SAP-ECL-001 |
| 개정 | 0.2 (독립 검토 RV-03 결과 반영) |
| 관련 문서 | SWAD-ECL-001, CLAUDE.md 소스코드 품질 기준 |
| 작성일 | 2026-11-26 |

## 1. 목적
구현 코드가 코딩 규칙, 복잡도·크기 제한, 주석 형식, 아키텍처 의존 규칙, Python 버전 호환을 지키는지 자동으로 확인하는 방법과 합격 기준을 정한다. ISO 26262-6의 코딩 지침(강한 타입, 복잡도 제한, 방어적 구현, 정적 분석)을 Python 환경에 맞게 적용한다.

## 2. 분석 항목

| ID | 항목 | 도구·명령 | 대상 | 합격 기준 |
|---|---|---|---|---|
| SA-01 | 코딩 규칙·잠재 버그 | `ruff check .` (E, W, F, I, N, B, UP, SIM, C90, **SLF**) | `src`, `tests`, `tools` | 위반 0건. `SLF001`은 SWAD DEP-06 근거 |
| SA-02 | 포맷 | `ruff format --check .` | 같음 | 차이 0건 |
| SA-03 | 순환 복잡도 | Ruff `C901` (`max-complexity = 10`) | `src`, `tools` | 모든 함수 10 이하 |
| SA-04 | 주석률·함수 길이 | `python -m tools.quality_check src tools` | `src`, `tools` | 모듈 주석률 20% 이상, 함수 순수 코드 50줄 이하 |
| SA-05 | 아키텍처 의존 규칙 | 아키텍처 시험 `tests/architecture/` (AST 분석) | `src/child_lock` | SWAD DEP-01~05 위반 0건. 코어의 import는 허용 목록만, 금지 내장 함수(`open`, `print`, `input`, `eval`, `exec`, `compile`, `__import__`) 호출 0건 |
| SA-06 | 타입 검사 | `mypy` (`strict = true`, `python_version = "3.12"`) | `src` | 오류 0건. `python_version` 설정으로 3.13 이상 전용 표준 라이브러리 API 사용도 검출 |
| SA-07 | Python 버전 호환 | Ruff `target-version = py312` + 3.12(`.venv`)·3.14(`.venv-py314`)에서 전체 시험 | 전체 | 두 버전 모두 시험 100% 통과, 커버리지 100% |
| SA-08 | 런타임 의존성 | `pyproject.toml`의 `dependencies` | – | 빈 목록 |
| SA-09 | 주석 형식 (Doxygen) | `quality_check` 확장: 모듈·클래스·공개 함수 docstring이 `"""!`로 시작하고 `@brief`를 포함. 인자가 있는 함수는 `@param`, 값을 반환하는 함수는 `@return` 포함 | `src`, `tools` | 위반 0건 |
| SA-10 | 규칙 예외 표기 | `quality_check` 확장: `# noqa`, `# type: ignore`, `# pragma: no cover`, `pytest.mark.skip`, `pytest.mark.xfail`, `pytest.skip(` 검출 | `src`, `tests`, `tools` | 0건 (사용자 승인 예외는 허용 목록 파일에 위치·사유 기록) |

## 3. 도입 계획
- SA-01~04, SA-07, SA-08: 0단계에서 구성했다. SA-01의 `SLF` 규칙은 4단계 시작 시 추가한다.
- SA-05, SA-09, SA-10: 4단계 첫 작업으로 TDD로 만든다.
- SA-06: 4단계 시작 시 개발 의존성에 `mypy`를 추가하고 `pyproject.toml`에 설정한다. 런타임 의존성이 아니므로 SWR-024에 영향 없다.

## 4. 실행 시점
- 개발자(Claude)는 PR 전에 SA-01~SA-10을 모두 실행하고 결과를 PR 본문에 적는다.
- Jenkins 구성 후에는 같은 항목을 PR마다 자동 실행한다(CLAUDE.md CI 절).

## 5. 위반 처리
- 위반은 코드를 고쳐 해결한다. 규칙 예외는 사용자 승인 없이 쓰지 않는다(CLAUDE.md).
- 승인된 예외는 위치와 사유를 PR 본문과 SA-10 허용 목록 파일에 기록한다.

## 6. 개정 이력

| 개정 | 일자 | 내용 |
|---|---|---|
| 0.1 | 2026-11-26 | 최초 작성 |
| 0.2 | 2026-11-26 | RV-03 반영: SLF 규칙, 코어 금지 내장 함수 검사, mypy `python_version`, 3.14 시험, Doxygen 형식(SA-09), 예외 표기 검사(SA-10) 추가 |
