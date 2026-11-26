// 전자식 차일드락 제어 SW CI 파이프라인 (Windows 빌드 노드)
// 품질 기준: CLAUDE.md "소스코드 품질", 정적 분석 계획 SAP-ECL-001
pipeline {
    agent any

    options {
        timeout(time: 60, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
        disableConcurrentBuilds()
    }

    environment {
        // 노드 환경 변수 PY312 / PY314가 있으면 그 값을 쓰고, 없으면 기본 설치 경로를 쓴다
        PY312 = "${env.PY312 ?: 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe'}"
        PY314 = "${env.PY314 ?: 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python314\\python.exe'}"
        PYTHONUTF8 = '1'
        PYTHONDONTWRITEBYTECODE = '1'
    }

    stages {
        stage('환경 준비') {
            steps {
                bat '"%PY312%" -m venv .ci-venv312 && .ci-venv312\\Scripts\\python.exe -m pip install -q --disable-pip-version-check -r requirements-dev.txt'
                bat '"%PY314%" -m venv .ci-venv314 && .ci-venv314\\Scripts\\python.exe -m pip install -q --disable-pip-version-check -r requirements-dev.txt'
            }
        }
        stage('정적 분석 (Ruff)') {
            steps {
                bat '.ci-venv312\\Scripts\\python.exe -m ruff check .'
                bat '.ci-venv312\\Scripts\\python.exe -m ruff format --check .'
            }
        }
        stage('타입 검사 (mypy)') {
            steps {
                bat '.ci-venv312\\Scripts\\python.exe -m mypy'
            }
        }
        stage('주석률·함수 길이·Doxygen·예외 표기') {
            steps {
                bat '.ci-venv312\\Scripts\\python.exe -m tools.quality_check src tools'
                bat '.ci-venv312\\Scripts\\python.exe -m tools.quality_check --markers-only tests'
            }
        }
        stage('단위 시험 Python 3.12') {
            steps {
                bat '.ci-venv312\\Scripts\\python.exe -m pytest -p no:cacheprovider --cov --cov-branch --cov-report=term-missing --cov-report=xml:coverage-312.xml --cov-fail-under=100 --junitxml=test-results-312.xml'
            }
        }
        stage('단위 시험 Python 3.14') {
            steps {
                bat '.ci-venv314\\Scripts\\python.exe -m pytest -p no:cacheprovider --cov --cov-branch --cov-report=term-missing --cov-report=xml:coverage-314.xml --cov-fail-under=100 --junitxml=test-results-314.xml'
            }
        }
        stage('시스템 시험 (SWE.6, Python 3.12)') {
            steps {
                // 시뮬레이터를 별도 프로세스로 실행하는 시스템 테스트 케이스 (docs/06_system_test)
                // STC-NF-002(서버 1,000회 재기동, 약 30분)는 CI에서 50회로 줄인다. 사양 값 실행 결과는 시스템 시험 보고서에 기록
                withEnv(['STC_NF_002_RUNS=50']) {
                    bat '.ci-venv312\\Scripts\\python.exe -m pytest tests/system -m system -p no:cacheprovider --junitxml=test-results-system.xml'
                }
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'test-results-*.xml'
            archiveArtifacts allowEmptyArchive: true, artifacts: 'coverage-*.xml'
        }
    }
}
