// 전자식 차일드락 제어 SW CI 파이프라인 (Windows 빌드 노드)
// 품질 기준: CLAUDE.md "소스코드 품질", 정적 분석 계획 SAP-ECL-001
pipeline {
    agent any

    options {
        timeout(time: 20, unit: 'MINUTES')
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
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'test-results-*.xml'
            archiveArtifacts allowEmptyArchive: true, artifacts: 'coverage-*.xml'
        }
    }
}
