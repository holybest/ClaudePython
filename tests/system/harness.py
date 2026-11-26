"""!
@brief SW 시스템 시험(SWE.6) 실행 도구.

납품 형태 그대로 `python -m child_lock.web`을 별도 프로세스로 실행하고 HTTP로만 입력·관찰한다.
표기는 docs/06_system_test/system_test_cases.json의 environment 필드를 따른다.
- B0: 모든 입력 정상(정지, 시동 ON) 스냅샷. `b0(key=value)`로 일부만 바꾸고, `DROP`으로 필드를 뺀다.
- cmd(side, action[, source]): 운전자 명령 객체(기본 source = physical_button).
- S0: 신규 기동 후 B0 1회 전송(좌·우 RELEASE, NORMAL).
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

## 저장소 루트
ROOT = Path(__file__).resolve().parents[2]

## 스냅샷에서 필드를 빼라는 표시 (표기 B0{-k})
DROP = object()

## B0: 모든 입력 정상 (command, source_timestamp_s 없음)
B0: dict[str, object] = {
    "vehicle_speed_kph": 0.0,
    "gear": "P",
    "crash_status": "NONE",
    "rear_left_approach_risk": False,
    "rear_right_approach_risk": False,
    "fire_detected": False,
    "overtemperature_detected": False,
    "adult_present": False,
    "isofix_left": False,
    "isofix_right": False,
    "ignition_on": True,
    "sensor_fault": False,
}


def b0(**changes: object) -> dict[str, object]:
    """B0에서 지정한 필드만 바꾼 스냅샷을 만든다. 값이 DROP이면 그 필드를 뺀다."""
    raw = {**B0, **changes}
    return {k: v for k, v in raw.items() if v is not DROP}


def cmd(side: str, action: str, source: str = "physical_button") -> dict[str, str]:
    """운전자 명령 객체를 만든다."""
    return {"side": side, "action": action, "source": source}


def floor_ms(seconds: float) -> float:
    """초 단위 시각을 ms 단위로 내림한다(표기 floor_ms)."""
    return int(seconds * 1000) / 1000


def summary(d: dict[str, object]) -> dict[str, object]:
    """판정 JSON에서 비교 대상 필드만 뽑는다."""
    keys = ("lock_left", "lock_right", "state", "priority_reason", "reason_code", "notices")
    return {k: d[k] for k in keys}


def expect(
    lock_left: str,
    lock_right: str,
    state: str,
    priority_reason: str,
    reason_code: str,
    notices: list[str] | None = None,
) -> dict[str, object]:
    """기대 판정을 만든다(summary와 같은 형식)."""
    return {
        "lock_left": lock_left,
        "lock_right": lock_right,
        "state": state,
        "priority_reason": priority_reason,
        "reason_code": reason_code,
        "notices": notices or [],
    }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Simulator:
    """별도 프로세스로 실행한 Web 시뮬레이터(시험 대상)."""

    def __init__(self) -> None:
        self.port = _free_port()
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "child_lock.web", "--port", str(self.port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_ready()

    def _wait_ready(self, timeout: float = 15.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                self.request_raw("GET", "/")
                return
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise RuntimeError("시뮬레이터가 기동되지 않았습니다")

    def stop(self) -> None:
        """프로세스를 종료한다."""
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    # ---- HTTP

    def request_raw(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        """요청을 보내고 (상태 코드, 본문 바이트)를 돌려준다."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def post(self, raw: object) -> tuple[int, dict[str, object]]:
        """스냅샷 JSON을 보내고 (상태 코드, 응답 JSON)을 돌려준다."""
        status, data = self.request_raw("POST", "/api/snapshot", json.dumps(raw).encode("utf-8"))
        return status, json.loads(data)

    def send(self, raw: object) -> dict[str, object]:
        """스냅샷을 보내고 200을 확인한 뒤 판정 JSON을 돌려준다."""
        status, payload = self.post(raw)
        assert status == 200, (status, payload)
        return payload

    def status(self) -> dict[str, object]:
        """GET /api/status 결과(서버는 조회 시 tick 1회 수행)."""
        status, data = self.request_raw("GET", "/api/status")
        assert status == 200
        return json.loads(data)

    def events(self) -> list[dict[str, object]]:
        """GET /api/events 결과."""
        status, data = self.request_raw("GET", "/api/events")
        assert status == 200
        return json.loads(data)

    def now(self) -> float:
        """표기 T: 최신 GET /api/status의 timestamp_s(서버 시각)."""
        return float(self.status()["timestamp_s"])

    def wait_until_server_time(self, t: float) -> None:
        """서버 시각이 t 이상이 될 때까지 기다린다(미래 시각 STALE 방지)."""
        while self.now() < t:
            time.sleep(0.01)

    # ---- 사전조건

    def s0(self) -> dict[str, object]:
        """S0: B0 1회 전송, 좌·우 RELEASE NORMAL 확인."""
        d = self.send(b0())
        assert (d["lock_left"], d["lock_right"], d["state"]) == ("RELEASE", "RELEASE", "NORMAL")
        return d

    def s_lock(self) -> dict[str, object]:
        """S-LOCK: S0 → 전체 잠금 명령 → 명령 없는 B0 (좌·우 LOCK)."""
        self.s0()
        self.send(b0(command=cmd("all", "lock")))
        d = self.send(b0())
        assert (d["lock_left"], d["lock_right"]) == ("LOCK", "LOCK")
        return d

    def s_mix(self) -> dict[str, object]:
        """S-MIX: S0 → 좌 ISOFIX → B0 (좌 LOCK, 우 RELEASE)."""
        self.s0()
        self.send(b0(isofix_left=True))
        d = self.send(b0())
        assert (d["lock_left"], d["lock_right"]) == ("LOCK", "RELEASE")
        return d

    @contextmanager
    def keepalive(self, raw: dict[str, object], period_s: float = 0.1) -> Iterator[None]:
        """KA: 단계 사이 대기 동안 raw(명령 제외)를 100 ms 주기로 반복 전송해 입력 중단을 막는다."""
        body = {k: v for k, v in raw.items() if k not in ("command", "source_timestamp_s")}
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(period_s):
                self.post(body)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()
