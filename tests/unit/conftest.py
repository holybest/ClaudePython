"""!
@brief 단위 시험 픽스처.
"""

from collections.abc import Callable

import pytest
from tests.unit.helpers import Harness, cmd


@pytest.fixture
def h() -> Harness:
    return Harness()


@pytest.fixture
def locked(h: Harness) -> Callable[[], Harness]:
    """좌·우 LOCK 상태(정지)로 만든 하니스를 돌려주는 함수."""

    def make() -> Harness:
        h.send(0.0, command=cmd("all", "lock"))
        h.send(0.05)
        return h

    return make
