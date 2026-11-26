# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

ClaudePython — AI를 이용한 파이썬 코드 작성용 저장소 (README 기준).

## 현재 상태

저장소에는 아직 `README.md`만 있습니다(초기 커밋). 빌드, 린트, 테스트 설정이나 소스 코드가 아직 없습니다.
코드나 도구(예: `pyproject.toml`, 테스트 프레임워크)가 추가되면 이 파일에 다음 항목을 채워 넣으세요:

- 개발 환경 설정 및 의존성 설치 명령
- 실행, 린트, 테스트 명령 (단일 테스트 실행 방법 포함)
- 여러 파일을 읽어야 이해할 수 있는 상위 수준 아키텍처

## 구현 규칙: TDD

기능 추가, 버그 수정, 리팩터링, 동작 변경 등 **코드를 구현할 때는 먼저 `test-driven-development` 스킬을 호출하고 그 절차를 따릅니다.**
실패하는 테스트를 먼저 쓰고 실패를 확인한 뒤(RED), 최소한의 코드로 통과시키고(GREEN), 정리합니다(REFACTOR).
테스트 프레임워크가 아직 없으면 Python 표준인 `pytest`를 도입합니다(설치 전 사용자 확인).
예외(일회성 프로토타입, 생성된 코드, 설정 파일)는 사용자에게 확인한 뒤에만 적용합니다.

## 프로젝트 스킬

- `.claude/skills/test-driven-development/`: TDD 절차 ([obra/superpowers](https://github.com/obra/superpowers)에서 수정 없이 가져옴, MIT, 출처는 `SOURCE.md`)

- `.claude/skills/sw-system-test-case/`: A-SPICE SWE.6 / ISO 26262-6 기반 SW 시스템 테스트 케이스 생성 (Excel 출력, PICT 페어와이즈). 스크립트는 Python 3 + `openpyxl`이 필요합니다.

## 프로젝트 서브에이전트

- `.claude/agents/sw-system-test-designer.md`: SW 요구사항 분석 완료 후 시스템 테스트 케이스 생성 단계에서 사용. 모델 Sonnet 5.5, `sw-system-test-case` 스킬 사용, 결함 발견 목적의 케이스 설계.

## 환경

- Windows 11, 기본 셸은 PowerShell (Git Bash도 사용 가능)
- 사용자와는 한국어로 소통합니다.
