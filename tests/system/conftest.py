"""!
@brief 시스템 시험 픽스처: 케이스마다 시뮬레이터를 새로 기동한다(사전조건 "서버 신규 기동").
"""

from collections.abc import Iterator

import pytest

from tests.system.harness import Simulator


@pytest.fixture
def sim() -> Iterator[Simulator]:
    simulator = Simulator()
    try:
        yield simulator
    finally:
        simulator.stop()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """tests/system 아래 시험에 system 표지를 붙인다(기본 실행에서 제외, -m system으로 실행)."""
    for item in items:
        if "tests/system/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.system)
