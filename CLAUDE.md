# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

ClaudePython — AI를 이용한 파이썬 코드 작성용 저장소 (README 기준).

## 개발환경

- 개발 언어는 Python 최신 안정 버전을 사용한다. 현재 기준은 Python 3.14이다.
- 단위 테스트 프레임워크는 pytest를 사용하고, 커버리지는 pytest-cov로 측정한다.
- 정적 분석과 코드 포맷은 Ruff를 사용한다. 순환 복잡도는 Ruff의 `C901` 규칙(`max-complexity = 10`)으로 검사한다.
- 도구 설정은 `pyproject.toml`에 둔다. 아직 없으므로 첫 코드 작업 때 만든다.

### 기본 명령

```bash
ruff check .                     # 정적 분석 (복잡도 C901 포함)
ruff format --check .            # 포맷 검사 (수정은 ruff format .)
pytest --cov --cov-branch --cov-report=term-missing --cov-fail-under=100
pytest tests/test_x.py::test_y   # 단일 테스트 실행
```

## 개발 절차

- 개발은 요구사항 분석 → 아키텍처 설계 → 상세 설계 → 구현 → 단위 테스트 → 통합 테스트 → 시스템 테스트 순서로 진행한다.
- 개발은 기본적으로 A-SPICE 절차를 준수한다. 각 단계의 산출물은 이전 단계 산출물(요구사항 ID 등)로 추적할 수 있어야 한다.
- 구현 시 TDD를 사용한다. 구현을 시작하기 전에 `test-driven-development` 스킬을 호출하고 그 절차(RED → GREEN → REFACTOR)를 따른다.
- 시스템 테스트 케이스는 요구사항 분석이 끝난 뒤 `sw-system-test-designer` 에이전트(`sw-system-test-case` 스킬 사용)로 만든다.

## 소스코드 품질

아래 기준은 모두 PR 병합 조건이다. 하나라도 만족하지 못하면 병합할 수 없다.

| 항목 | 기준 | 측정 방법 |
|---|---|---|
| 단위 테스트 Branch 커버리지 | **반드시** 100% | `pytest --cov --cov-branch --cov-fail-under=100` |
| 단위 테스트 성공률 | 100% (실패·에러 0건) | `pytest` 결과 |
| 주석률 | 20% 이상 | 아래 정의 참고 |
| 함수 길이 | 순수 코드 50줄 이하 | 아래 정의 참고 |
| 함수 순환 복잡도 | **반드시** 10 이하 | `ruff check` (`C901`) |
| 명명 규칙 | Google Python Style Guide | 리뷰 + Ruff `N` 규칙 |

- **커버리지 100% 미달 시**: 목표를 달성할 때까지 테스트를 추가한다. 도달할 수 없는 코드는 테스트로 억지로 덮지 말고 코드를 삭제하거나 설계를 고친다. `# pragma: no cover`, `pytest.mark.skip`, `xfail`은 사용자 승인 없이 쓰지 않는다.
- **주석률**: (주석 줄 수 + docstring 줄 수) ÷ (빈 줄을 제외한 전체 줄 수) × 100. 모듈(파일) 단위로 계산한다. 테스트 코드는 제외한다.
- **순수 코드 줄 수**: 함수 본문에서 빈 줄, 주석 줄, docstring 줄을 뺀 줄 수. 시그니처(`def` 줄)는 포함하지 않는다.
- **주석 형식**: Doxygen 스타일을 쓴다. 함수·클래스·모듈에는 `"""!`로 시작하는 docstring에 `@brief`, `@param`, `@return`(필요 시 `@exception`)을 적는다.
- **명명 규칙(Google Python Style Guide)**: 모듈·패키지·함수·메서드·변수는 `lower_with_under`, 클래스·예외는 `CapWords`, 상수는 `CAPS_WITH_UNDER`, 내부용은 `_` 접두사. Google 스타일은 명명 규칙에만 적용하고, 주석 형식은 위의 Doxygen 스타일을 따른다.

## Git 브랜치 규칙

- 브랜치 전략은 **GitHub Flow**를 따른다. 장기 브랜치는 `main` 하나뿐이다.
- `main`에 직접 커밋·푸시하지 않는다. 모든 작업은 `main`에서 새 브랜치를 만들어 진행한다.
- 브랜치 이름은 `<유형>/<짧은-설명>` 형식이며 설명은 영문 소문자와 하이픈으로 쓴다. 예: `feature/speed-display`, `fix/timer-overflow`.
  - 유형: `feature`(기능), `fix`(버그 수정), `refactor`(리팩터링), `test`(테스트만), `docs`(문서), `chore`(설정·빌드·도구)
- 커밋 메시지와 PR 제목·본문은 한글로 쓴다. PR 본문에는 관련 요구사항 ID와 품질 기준 확인 결과를 적는다.
- `main` 반영은 PR로만 하고, 병합 방식은 **Squash merge**를 사용한다. 병합한 브랜치는 삭제한다.
- **병합 조건**: 아래를 모두 만족해야 한다.
  1. 소스코드 품질 기준을 모두 충족
  2. CI(Jenkins) 통과. CI 구성 전에는 위 "기본 명령"을 로컬에서 실행한 결과를 PR 본문에 첨부
  3. 사용자의 리뷰 또는 병합 요청
- Claude는 위 조건을 모두 만족하고 사용자가 병합을 요청한 경우에만 PR을 병합할 수 있다. 그 외에는 PR 생성·수정까지만 한다.

## CI

- CI는 Jenkins를 사용한다. 서버는 172.16.7.121에 있다.
- **현재 미구성 상태이다.** 목표는 저장소에 `Jenkinsfile`을 두고 PR마다 Ruff 검사, pytest(커버리지 100% 확인), 품질 기준 검사를 실행하는 것이다. 접속 URL(포트), Job 이름, 트리거 방식이 정해지면 이 절에 적는다.

## 기타

- CLAUDE.md는 한글로 작성한다.
- 모든 산출물(문서, 테스트 케이스, 커밋 메시지, PR, 코드 주석)은 한글로 작성한다. 단, 코드 식별자와 브랜치 이름은 영문으로 쓴다.
- 의미 없는 사과를 하지 않는다.
- 반말하지 않는다. 존댓말(합니다체)을 쓴다.
