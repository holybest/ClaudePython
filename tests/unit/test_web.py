"""!
@brief SWU-09 Web API, SWU-10 실행 진입점 단위 시험 (SWDD 10~11장, SWR-011, 014, 015, 025, 026).
"""

import http.client
import json
import runpy
import sys
import threading

import pytest

import child_lock.web.server as server_mod
from child_lock.app.event_log import EventLog
from child_lock.app.service import create_service
from child_lock.core import model as m
from child_lock.web import __main__ as entry
from child_lock.web.server import (
    RequestError,
    SerializationError,
    decision_to_dict,
    event_to_dict,
    make_server,
    parse_snapshot,
    to_json_bytes,
)
from tests.unit.helpers import cmd, raw_snapshot

# ---------------------------------------------------------------- 요청 파싱 (SWR-015, 026)


def _body(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


def test_parse_fills_missing_timestamp_with_server_time():
    raw = raw_snapshot(None)
    assert parse_snapshot(_body(raw), 7.5) == {**raw, "source_timestamp_s": 7.5}


def test_parse_keeps_given_timestamp_and_command():
    raw = raw_snapshot(3.0, command=cmd("left", "unlock", "voice"))
    assert parse_snapshot(_body(raw), 9.0) == raw


def test_parse_allows_missing_fields_for_core_to_invalidate():
    assert parse_snapshot(b"{}", 1.0) == {"source_timestamp_s": 1.0}


@pytest.mark.parametrize(
    "body",
    [
        b"\xff\xfe",  # UTF-8 아님
        b"{not json",
        b"[1, 2]",  # 최상위가 객체 아님
        b'{"vehicle_speed_kph": NaN}',
        b'{"vehicle_speed_kph": Infinity}',
        b'{"vehicle_speed_kph": -Infinity}',
        b'{"vehicle_speed_kph": 1e400}',
        b'{"video_frame": "abc"}',  # 정의되지 않은 필드 (개인정보)
        b'{"driver_name": "kim"}',
        b'{"command": {"side": "left", "action": "lock", "source": "avn", "voice_clip": "x"}}',
    ],
)
def test_parse_rejects_bad_bodies(body):
    with pytest.raises(RequestError):
        parse_snapshot(body, 1.0)


def test_parse_passes_non_object_command_to_core():
    assert parse_snapshot(b'{"command": "left"}', 1.0)["command"] == "left"


# ---------------------------------------------------------------- 직렬화 (SWR-011, 014)


def _decision() -> m.Decision:
    validity = m.InputValidity(*([m.Validity.VALID] * 7), m.Validity.STALE)
    return m.Decision(
        m.LockOutput.LOCK,
        m.LockOutput.RELEASE,
        m.State.DEGRADED,
        validity,
        m.PriorityReason.DEGRADED,
        m.ReasonCode.INPUT_STALE,
        (m.Notice.CRASH_PENDING,),
        2.5,
    )


def test_decision_to_dict_has_swr_014_fields():
    assert decision_to_dict(_decision()) == {
        "lock_left": "LOCK",
        "lock_right": "RELEASE",
        "state": "DEGRADED",
        "input_validity": {
            "IF-001": "VALID",
            "IF-002": "VALID",
            "IF-003": "VALID",
            "IF-004": "VALID",
            "IF-007": "VALID",
            "IF-008": "VALID",
            "IF-009": "VALID",
            "FRESHNESS": "STALE",
        },
        "priority_reason": "DEGRADED",
        "reason_code": "INPUT_STALE",
        "notices": ["CRASH_PENDING"],
        "timestamp_s": 2.5,
    }


def test_event_to_dict_has_only_swr_011_fields():
    event = EventLog().record(_decision(), is_tick=False)
    assert event_to_dict(event) == {
        "event_id": 1,
        "timestamp_s": 2.5,
        "lock_left": "LOCK",
        "lock_right": "RELEASE",
        "state": "DEGRADED",
        "priority_reason": "DEGRADED",
        "reason_code": "INPUT_STALE",
        "notices": ["CRASH_PENDING"],
    }


def test_to_json_bytes_encodes_utf8_and_rejects_unserializable():
    assert to_json_bytes({"a": "한글"}) == '{"a": "한글"}'.encode()
    with pytest.raises(SerializationError):
        to_json_bytes({"a": object()})
    with pytest.raises(SerializationError):
        to_json_bytes({"a": float("nan")})


# ---------------------------------------------------------------- HTTP (SWR-015, 025, 026)


class FakeClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def web():
    """임의 포트에 실제 HTTP 서버를 띄운다."""
    clock = FakeClock()
    service = create_service(clock)
    srv = make_server(service, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, service, clock
    srv.shutdown()
    srv.server_close()


def _request(srv, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type"), data


def test_make_server_holds_service(web):
    srv, service, _ = web
    assert srv.service is service


def test_get_index_returns_simulator_page(web):
    status, ctype, data = _request(web[0], "GET", "/")
    assert (status, ctype) == (200, "text/html; charset=utf-8")
    assert "차일드락" in data.decode("utf-8")


def test_post_snapshot_evaluates_and_returns_decision(web):
    srv, service, _ = web
    body = _body(raw_snapshot(None, command=cmd("all", "lock")))
    status, ctype, data = _request(srv, "POST", "/api/snapshot", body)
    assert (status, ctype) == (200, "application/json; charset=utf-8")
    result = json.loads(data)
    assert (result["lock_left"], result["reason_code"], result["timestamp_s"]) == (
        "LOCK",
        "DRIVER_LOCK",
        10.0,
    )
    assert len(service.events()) == 1


def test_get_status_runs_tick_and_get_events_lists_history(web):
    srv, _, clock = web
    _request(srv, "POST", "/api/snapshot", _body(raw_snapshot(None)))
    clock.now = 10.3  # 입력 중단 300 ms
    status, _, data = _request(srv, "GET", "/api/status")
    assert status == 200
    assert json.loads(data)["state"] == "DEGRADED"
    status, _, data = _request(srv, "GET", "/api/events")
    events = json.loads(data)
    assert status == 200
    assert [e["reason_code"] for e in events] == ["NO_CHANGE", "INPUT_STALE"]
    assert set(events[0]) == {
        "event_id",
        "timestamp_s",
        "lock_left",
        "lock_right",
        "state",
        "priority_reason",
        "reason_code",
        "notices",
    }


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"{bad", None),
        (b'{"face_image": "x"}', None),
        (b"", {"Content-Length": "abc"}),
        (b"x" * 70000, None),
    ],
)
def test_post_bad_request_returns_400_and_changes_nothing(web, body, headers):
    srv, service, _ = web
    status, _, data = _request(srv, "POST", "/api/snapshot", body, headers)
    assert status == 400
    assert "error" in json.loads(data)
    assert service.events() == ()


def test_post_without_content_length_returns_400(web):
    srv = web[0]
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    conn.putrequest("POST", "/api/snapshot")
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 400
    conn.close()


@pytest.mark.parametrize(("method", "path"), [("GET", "/nope"), ("POST", "/api/status")])
def test_unknown_route_returns_404(web, method, path):
    assert _request(web[0], method, path, b"{}" if method == "POST" else None)[0] == 404


def test_serialization_failure_returns_500(web, monkeypatch):
    monkeypatch.setattr(server_mod, "decision_to_dict", lambda _d: {"bad": object()})
    status, _, data = _request(web[0], "GET", "/api/status")
    assert status == 500
    assert json.loads(data) == {"error": "내부 오류"}


def test_service_exception_returns_500(web, monkeypatch):
    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(web[1], "events", boom)
    assert _request(web[0], "GET", "/api/events")[0] == 500


def test_missing_index_file_returns_500(web, monkeypatch, tmp_path):
    monkeypatch.setattr(server_mod, "INDEX_PATH", tmp_path / "none.html")
    assert _request(web[0], "GET", "/")[0] == 500


# ---------------------------------------------------------------- 실행 진입점 (SWU-10)


class FakeServer:
    def __init__(self) -> None:
        self.server_port = 8123
        self.closed = False

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.closed = True


class FakeService:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def stop(self) -> None:
        self.events.append("stop")


def test_main_starts_service_serves_and_cleans_up_on_interrupt(monkeypatch, capsys):
    svc, fake = FakeService(), FakeServer()
    created = {}

    def fake_make_server(service, host, port):
        created.update(service=service, host=host, port=port)
        return fake

    monkeypatch.setattr(entry, "create_service", lambda: svc)
    monkeypatch.setattr(entry, "make_server", fake_make_server)
    assert entry.main(["--host", "0.0.0.0", "--port", "8123"]) == 0
    assert created == {"service": svc, "host": "0.0.0.0", "port": 8123}
    assert svc.events == ["start", "stop"]
    assert fake.closed
    assert "http://0.0.0.0:8123" in capsys.readouterr().out


def test_module_execution_runs_main(monkeypatch):
    monkeypatch.setattr(server_mod, "make_server", lambda *_a, **_k: FakeServer())
    monkeypatch.setattr(sys, "argv", ["child_lock.web", "--port", "0"])
    monkeypatch.delitem(sys.modules, "child_lock.web.__main__")
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("child_lock.web", run_name="__main__")
    assert exc.value.code == 0


def test_error_responses_are_delivered_reliably_even_with_unread_bodies(web):
    # 본문을 읽지 않고 응답하면 Windows에서 연결이 강제로 끊길 수 있다(RST). 반복 요청으로 확인한다.
    srv = web[0]
    failures = []
    for _ in range(300):
        for path, body, expected in (
            ("/api/status", b"{}", 404),
            ("/api/snapshot", b"x" * 70000, 400),
        ):
            try:
                status = _request(srv, "POST", path, body)[0]
            except OSError as exc:
                failures.append(type(exc).__name__)
                continue
            if status != expected:
                failures.append(status)
    assert failures == []
