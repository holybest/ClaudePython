"""!
@brief 제품 코드(src/child_lock)의 아키텍처 의존 규칙 시험 (SWAD DEP-01~05, DEP-07, SA-05).
"""

from pathlib import Path

from tools import arch_check

## 검사 대상 패키지 폴더
PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "child_lock"


def test_product_code_follows_architecture_dependency_rules():
    assert PACKAGE_DIR.is_dir()
    assert arch_check.check_package(PACKAGE_DIR) == []
