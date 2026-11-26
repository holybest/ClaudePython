"""!
@brief SWU-09 Web API (QM).

표준 라이브러리 http.server로 시뮬레이터 화면과 JSON API를 제공한다. 요청 필드를 제한하고(SWR-026)
직렬화 실패는 HTTP 500으로 응답한다(SWR-015). (SWDD 10장, SWAD 4.3~4.4)
"""

import json
import math
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NoReturn

from child_lock.app.event_log import Event
from child_lock.app.service import ChildLockService
from child_lock.core.model import Decision

## 스냅샷 요청에 허용하는 키 (SWAD 4.4)
SNAPSHOT_KEYS = frozenset(
    {
        "vehicle_speed_kph",
        "gear",
        "source_timestamp_s",
        "crash_status",
        "rear_left_approach_risk",
        "rear_right_approach_risk",
        "command",
        "fire_detected",
        "overtemperature_detected",
        "adult_present",
        "isofix_left",
        "isofix_right",
        "ignition_on",
        "sensor_fault",
    }
)
## 운전자 명령 객체에 허용하는 키
COMMAND_KEYS = frozenset({"side", "action", "source"})
## 요청 본문 최대 크기(바이트)
MAX_BODY_BYTES = 65536
## 오류 응답 전에 읽어서 버릴 본문 상한(바이트). 읽지 않은 본문이 있으면 연결이 강제로 끊길 수 있다
DRAIN_LIMIT_BYTES = 1048576
## 시뮬레이터 화면 파일
INDEX_PATH = Path(__file__).with_name("static") / "index.html"
## JSON 응답 형식
JSON_TYPE = "application/json; charset=utf-8"


class RequestError(Exception):
    """!
    @brief 잘못된 요청 (HTTP 400).
    """


class SerializationError(Exception):
    """!
    @brief 응답 직렬화 실패 (HTTP 500).
    """


def _reject_constant(name: str) -> NoReturn:
    """!
    @brief NaN, Infinity, -Infinity 리터럴을 거절한다.
    @param name 리터럴 이름
    """
    raise RequestError(f"허용되지 않는 숫자: {name}")


def _parse_float(text: str) -> float:
    """!
    @brief 실수 리터럴을 읽고 유한하지 않으면(예: 1e400) 거절한다.
    @param text 실수 리터럴
    @return 실수 값
    """
    value = float(text)
    if not math.isfinite(value):
        raise RequestError(f"허용되지 않는 숫자: {text}")
    return value


def _check_keys(data: dict[str, object]) -> None:
    """!
    @brief 정의되지 않은 필드가 있으면 거절한다 (SWR-026).
    @param data 요청 객체
    """
    extra = set(data) - SNAPSHOT_KEYS
    command = data.get("command")
    if isinstance(command, dict):
        extra |= {f"command.{k}" for k in set(command) - COMMAND_KEYS}
    if extra:
        raise RequestError(f"정의되지 않은 필드: {', '.join(sorted(extra))}")


def parse_snapshot(body: bytes, now_s: float) -> dict[str, object]:
    """!
    @brief 스냅샷 요청 본문을 검사하고 사전으로 바꾼다.
    @param body 요청 본문
    @param now_s 런타임 시계 값(시각이 없을 때 채움)
    @return 원시 스냅샷 사전
    """
    try:
        data = json.loads(
            body.decode("utf-8"), parse_constant=_reject_constant, parse_float=_parse_float
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestError("JSON 형식 오류") from exc
    if not isinstance(data, dict):
        raise RequestError("최상위는 JSON 객체여야 합니다")
    _check_keys(data)
    data.setdefault("source_timestamp_s", now_s)
    return data


def decision_to_dict(d: Decision) -> dict[str, object]:
    """!
    @brief 판정 결과를 JSON 사전으로 바꾼다 (SWR-014).
    @param d 판정 결과
    @return JSON 사전
    """
    return {
        "lock_left": d.lock_left.value,
        "lock_right": d.lock_right.value,
        "state": d.state.value,
        "input_validity": d.input_validity.as_dict(),
        "priority_reason": d.priority_reason.value,
        "reason_code": d.reason_code.value,
        "notices": [n.value for n in d.notices],
        "timestamp_s": d.timestamp_s,
    }


def event_to_dict(e: Event) -> dict[str, object]:
    """!
    @brief 결정 이벤트를 JSON 사전으로 바꾼다 (SWR-011 허용 필드만).
    @param e 결정 이벤트
    @return JSON 사전
    """
    return {
        "event_id": e.event_id,
        "timestamp_s": e.timestamp_s,
        "lock_left": e.lock_left.value,
        "lock_right": e.lock_right.value,
        "state": e.state.value,
        "priority_reason": e.priority_reason.value,
        "reason_code": e.reason_code.value,
        "notices": [n.value for n in e.notices],
    }


def to_json_bytes(obj: object) -> bytes:
    """!
    @brief 객체를 UTF-8 JSON 바이트로 직렬화한다.
    @param obj 직렬화할 객체
    @return JSON 바이트
    """
    try:
        return json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SerializationError(str(exc)) from exc


class ChildLockServer(ThreadingHTTPServer):
    """!
    @brief 서비스를 속성으로 가진 HTTP 서버.
    """

    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: ChildLockService) -> None:
        """!
        @brief 서버를 만든다.
        @param address (호스트, 포트)
        @param service 응용 서비스
        """
        super().__init__(address, ChildLockHandler)
        self.service = service


class ChildLockHandler(BaseHTTPRequestHandler):
    """!
    @brief HTTP 요청 처리기 (SWDD 10.3).
    """

    server: ChildLockServer

    def do_GET(self) -> None:
        """!
        @brief GET 경로를 처리한다.
        """
        routes: dict[str, Callable[[], None]] = {
            "/": self._index,
            "/api/status": self._status,
            "/api/events": self._events,
        }
        self._dispatch(routes.get(self.path))

    def do_POST(self) -> None:
        """!
        @brief POST 경로를 처리한다. 응답 전에 본문을 먼저 읽는다.
        """
        body = self._take_body()
        if self.path != "/api/snapshot":
            self._dispatch(None)
            return
        self._dispatch(lambda: self._snapshot(body))

    def _dispatch(self, handler: Callable[[], None] | None) -> None:
        """!
        @brief 처리 함수를 실행하고 오류를 HTTP 상태로 바꾼다.
        @param handler 처리 함수(없으면 404)
        """
        if handler is None:
            self._send_json(404, {"error": "경로 없음"})
            return
        try:
            handler()
        except RequestError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception:
            self._send_json(500, {"error": "내부 오류"})

    def _index(self) -> None:
        """!
        @brief 시뮬레이터 화면을 보낸다 (SWR-025).
        """
        self._send(200, "text/html; charset=utf-8", INDEX_PATH.read_bytes())

    def _status(self) -> None:
        """!
        @brief tick 1회 후 상태를 보낸다 (SWR-014, 022).
        """
        self._send(200, JSON_TYPE, to_json_bytes(decision_to_dict(self.server.service.status())))

    def _events(self) -> None:
        """!
        @brief 결정 이력을 보낸다 (SWR-012).
        """
        events = [event_to_dict(e) for e in self.server.service.events()]
        self._send(200, JSON_TYPE, to_json_bytes(events))

    def _snapshot(self, body: bytes | None) -> None:
        """!
        @brief 스냅샷을 평가하고 판정 결과를 보낸다.
        @param body 요청 본문(길이 오류면 None)
        """
        if body is None:
            raise RequestError("Content-Length가 없거나 너무 큽니다")
        raw = parse_snapshot(body, self.server.service.now())
        decision = self.server.service.submit_snapshot(raw)
        self._send(200, JSON_TYPE, to_json_bytes(decision_to_dict(decision)))

    def _take_body(self) -> bytes | None:
        """!
        @brief 요청 본문을 읽는다. 너무 크면 상한까지 읽어서 버린다(연결 강제 종료 방지).
        @return 요청 본문, Content-Length가 없거나 형식 오류·크기 초과면 None
        """
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            return None
        size = int(length)
        data = self.rfile.read(min(size, DRAIN_LIMIT_BYTES))
        return data if size <= MAX_BODY_BYTES else None

    def _send_json(self, status: int, payload: dict[str, str]) -> None:
        """!
        @brief 오류 JSON을 보낸다.
        @param status HTTP 상태 코드
        @param payload 오류 객체
        """
        self._send(status, JSON_TYPE, to_json_bytes(payload))

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        """!
        @brief 응답을 보낸다.
        @param status HTTP 상태 코드
        @param content_type Content-Type
        @param body 응답 본문
        """
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """!
        @brief 요청 로그를 남기지 않는다(요청 본문·개인정보 보호, SWR-026).
        @param format 로그 형식
        @param args 로그 인자
        """


def make_server(
    service: ChildLockService, host: str = "127.0.0.1", port: int = 8000
) -> ChildLockServer:
    """!
    @brief HTTP 서버를 만든다.
    @param service 응용 서비스
    @param host 바인드 주소
    @param port 포트(0이면 임의 포트)
    @return 서버
    """
    return ChildLockServer((host, port), service)
