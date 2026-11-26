"""!
@brief SW 통합 시험 (SWE.5). 실제 시계·tick 스레드·HTTP 서버·별도 프로세스까지 연결해 확인한다.

시험 ID(ITC-xx)는 docs/05_integration/integration_test_report.md의 통합 시험 사양과 같다.
"""

import hashlib
import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from child_lock.app.event_log import EventLog
from child_lock.app.service import ChildLockService, create_service
from child_lock.core.controller import ChildLockController
from child_lock.core.model import Decision
from child_lock.runtime.runtime import MonotonicClock, SafetyRuntime
from child_lock.web.server import decision_to_dict, event_to_dict, make_server
from tests.unit.helpers import cmd, raw_snapshot

ROOT = Path(__file__).resolve().parents[2]


class FixedClock:
    """재생용 고정 시계."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Stack:
    """서비스·런타임·HTTP 서버를 실제로 연결한 시험 대상."""

    def __init__(self, tick_period_s: float = 0.05) -> None:
        self.ticks: list[float] = []
        self.log = EventLog()
        clock = MonotonicClock()
        self.runtime = SafetyRuntime(ChildLockController(), clock, self._on_decision, tick_period_s)
        self.service = ChildLockService(self.runtime, self.log)
        self.server = make_server(self.service, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _on_decision(self, decision: Decision, is_tick: bool) -> None:
        if is_tick and threading.current_thread().name == "tick":  # 조회 시 tick은 제외
            self.ticks.append(time.perf_counter())
        self.log.record(decision, is_tick)

    def __enter__(self) -> "Stack":
        self.thread.start()
        self.service.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.service.stop()
        self.server.shutdown()
        self.server.server_close()

    def request(self, method: str, path: str, body: object = None) -> tuple[int, object]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        data = None if body is None else json.dumps(body).encode("utf-8")
        conn.request(method, path, body=data)
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        conn.close()
        return resp.status, payload


def _wait(cond, timeout: float):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = cond()
        if value:
            return value
        time.sleep(0.005)
    return None


# ---- ITC-01 데이터 흐름


def test_itc01_http_snapshot_flows_through_runtime_core_and_event_log():
    with Stack() as s:
        status, decision = s.request(
            "POST", "/api/snapshot", raw_snapshot(None, command=cmd("all", "lock"))
        )
        assert status == 200
        assert (decision["lock_left"], decision["lock_right"]) == ("LOCK", "LOCK")
        _, events = s.request("GET", "/api/events")
        assert events[0]["reason_code"] == "DRIVER_LOCK"
        assert events[0]["timestamp_s"] == decision["timestamp_s"]
        _, status_now = s.request("GET", "/api/status")
        assert (status_now["lock_left"], status_now["state"]) == ("LOCK", "NORMAL")


# ---- ITC-02 입력 중단 감시 (SWR-022)


def test_itc02_tick_thread_detects_input_interruption_within_300ms():
    with Stack() as s:
        _, d = s.request("POST", "/api/snapshot", raw_snapshot(None))
        sent_at = d["timestamp_s"]

        def degraded_event():
            return next((e for e in s.service.events() if e.state.value == "DEGRADED"), None)

        event = _wait(degraded_event, timeout=2.0)  # 상태 조회 없이 tick 스레드만으로 검출
        assert event is not None
        assert event.reason_code.value == "INPUT_STALE"
        assert 0.200 < event.timestamp_s - sent_at <= 0.300


# ---- ITC-03 HTTP 부하 중 tick 간격 (SWAD 6.1)


def test_itc03_tick_interval_stays_within_100ms_under_http_load():
    with Stack() as s:
        stop = threading.Event()
        errors: list[BaseException] = []

        def client() -> None:
            # 5 ms 간격: 연결을 너무 빨리 만들면 클라이언트 임시 포트가 고갈된다(WinError 10048)
            while not stop.wait(0.005):
                try:
                    s.request("POST", "/api/snapshot", raw_snapshot(None))
                    s.request("GET", "/api/status")
                except BaseException as exc:  # 부하 중 오류 수집
                    errors.append(exc)

        clients = [threading.Thread(target=client) for _ in range(4)]
        for c in clients:
            c.start()
        time.sleep(2.0)
        stop.set()
        for c in clients:
            c.join()
        gaps = [b - a for a, b in zip(s.ticks, s.ticks[1:], strict=False)]
        assert errors == []
        assert len(gaps) > 20
        assert max(gaps) <= 0.100


# ---- ITC-04 결정론 (SWR-016)


def _replay_vector() -> list[tuple[str, float, dict[str, object] | None]]:
    """다양한 규칙을 거치는 고정 입력 벡터 (스냅샷·tick)."""
    steps: list[tuple[str, float, dict[str, object] | None]] = [
        ("snap", 0.00, raw_snapshot(0.00, command=cmd("all", "lock"))),
        ("snap", 0.05, raw_snapshot(0.05)),
        (
            "snap",
            0.10,
            raw_snapshot(0.10, rear_left_approach_risk=True, command=cmd("left", "unlock")),
        ),
        ("snap", 0.15, raw_snapshot(0.15, rear_left_approach_risk=True)),
        (
            "snap",
            5.00,
            raw_snapshot(5.00, rear_left_approach_risk=True, command=cmd("left", "unlock")),
        ),
        ("tick", 5.05, None),
        ("snap", 5.10, raw_snapshot(5.10, vehicle_speed_kph=40.0, crash_status="PENDING")),
        ("tick", 5.40, None),
        ("snap", 5.45, raw_snapshot(5.45, vehicle_speed_kph=40.0, isofix_right=True)),
        ("snap", 5.50, raw_snapshot(5.50, fire_detected=True)),
        ("snap", 5.55, raw_snapshot(5.55, sensor_fault=True, command=cmd("all", "lock"))),
        ("snap", 5.60, raw_snapshot(5.60, crash_status="CONFIRMED")),
        ("tick", 6.00, None),
        ("snap", 6.05, raw_snapshot(6.05, ignition_on=False)),
        ("snap", 6.10, raw_snapshot(6.10, command={"side": "x"})),
    ]
    return steps


def _replay_hash() -> str:
    clock = FixedClock()
    svc = create_service(clock)
    results = []
    for kind, now, raw in _replay_vector():
        clock.now = now
        d = svc.submit_snapshot(raw) if kind == "snap" and raw is not None else svc.status()
        results.append(decision_to_dict(d))
    results.append([event_to_dict(e) for e in svc.events()])
    data = json.dumps(results, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def test_itc04_same_inputs_and_clock_give_identical_results_1000_times():
    hashes = {_replay_hash() for _ in range(1000)}
    assert len(hashes) == 1


# ---- ITC-05 처리 시간 (SWR-023)


def test_itc05_single_evaluation_takes_at_most_10ms():
    rt = SafetyRuntime(ChildLockController(), MonotonicClock(), EventLog().record)
    durations = []
    for i in range(1000):
        raw = raw_snapshot(
            rt.now(), rear_left_approach_risk=bool(i % 2), command=cmd("all", "unlock")
        )
        start = time.perf_counter()
        rt.evaluate_snapshot(raw)
        rt.tick()
        durations.append((time.perf_counter() - start) / 2)
    assert max(durations) <= 0.010


# ---- ITC-06 비영속성 (SWR-012)


def test_itc06_history_is_not_persisted_across_processes(tmp_path):
    code = (
        "from child_lock.app.service import create_service\n"
        "s = create_service()\n"
        "s.submit_snapshot({'source_timestamp_s': 0.0})\n"
        "print(len(s.events()))\n"
    )
    env_path = str(ROOT / "src")
    run = [sys.executable, "-c", code]
    first = subprocess.run(run, cwd=tmp_path, capture_output=True, text=True, env=_env(env_path))
    second_code = (
        "from child_lock.app.service import create_service\nprint(len(create_service().events()))\n"
    )
    second = subprocess.run(
        [sys.executable, "-c", second_code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_env(env_path),
    )
    assert (first.stdout.strip(), second.stdout.strip()) == ("1", "0")
    assert list(tmp_path.iterdir()) == []  # 파일 생성 없음


def _env(src: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = src
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# ---- ITC-07 실행 진입점 (SWU-10, SWR-025)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_itc07_module_entry_point_serves_page_and_api():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "child_lock.web", "--port", str(port)],
        env=_env(str(ROOT / "src")),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:

        def get(path: str):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", path)
                resp = conn.getresponse()
                return resp.status, resp.read()
            except OSError:
                return None

        page = _wait(lambda: get("/"), timeout=10.0)
        assert page is not None and page[0] == 200
        assert "차일드락" in page[1].decode("utf-8")
        status, body = get("/api/status")
        assert status == 200
        assert json.loads(body)["state"] == "OFF"  # 첫 스냅샷 전 (DEF-06)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---- ITC-08 화면 명령 순서로 override (SWDD 12장)


def test_itc08_ui_command_sequence_enables_override_via_http():
    with Stack() as s:
        risk = {"rear_left_approach_risk": True}
        s.request(
            "POST", "/api/snapshot", raw_snapshot(None, command=cmd("left", "unlock"), **risk)
        )
        _, first = s.request(
            "POST", "/api/snapshot", raw_snapshot(None, **risk)
        )  # 화면의 후속 전송
        assert first["lock_left"] == "LOCK"
        s.request(
            "POST", "/api/snapshot", raw_snapshot(None, command=cmd("left", "unlock"), **risk)
        )
        _, after = s.request("POST", "/api/snapshot", raw_snapshot(None, **risk))
        assert (after["lock_left"], after["state"], after["reason_code"]) == (
            "RELEASE",
            "OVERRIDE",
            "APPROACH_OVERRIDE",
        )


# ---- ITC-09 동시 요청 (SWAD 6.1 실행 순서)


def test_itc09_concurrent_requests_keep_event_ids_unique_and_sequential():
    with Stack() as s:
        errors: list[BaseException] = []

        def client(i: int) -> None:
            try:
                for j in range(25):
                    side = "left" if (i + j) % 2 else "right"
                    s.request(
                        "POST", "/api/snapshot", raw_snapshot(None, command=cmd(side, "lock"))
                    )
                    s.request("POST", "/api/snapshot", raw_snapshot(None))
            except BaseException as exc:  # 동시 실행 오류 수집
                errors.append(exc)

        threads = [threading.Thread(target=client, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ids = [e.event_id for e in s.service.events()]
        assert errors == []
        assert ids == list(range(ids[0], ids[0] + len(ids)))
        assert len(ids) == 100  # 최근 100건만 보관 (SWR-012)


@pytest.mark.parametrize("path", ["/api/status", "/api/events"])
def test_itc10_status_and_events_are_valid_json_while_tick_thread_runs(path):
    with Stack() as s:
        for _ in range(20):
            status, payload = s.request("GET", path)
            assert status == 200
            assert isinstance(payload, (dict, list))
