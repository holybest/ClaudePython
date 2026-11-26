"""!
@brief 시스템 시험 D 묶음: STC-F-131 ~ STC-F-167, STC-NF-001 ~ STC-NF-007.

케이스 1건 = 시험 함수 1개. 단계별 기대값은 system_test_cases.json의 "예상 출력값"을 그대로 옮긴다.
notices는 케이스 합격 기준대로 집합 비교한다(_summary가 정렬해서 비교).
장시간 케이스(STC-NF-002)는 반복 횟수를 환경 변수로 줄일 수 있다(기본값은 케이스 사양).
"""

import base64
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import tomllib
import urllib.parse
from pathlib import Path

from tests.system.harness import DROP, ROOT, Simulator, b0, cmd, expect, summary

## N: 왼쪽 접근위험 TRUE 스냅샷
N = b0(rear_left_approach_risk=True)

## 지연 스냅샷의 지연량(초): source_timestamp_s = T - 0.300
STALE_DELAY_S = 0.300

## Python 3.12 실행 파일 (STC-NF-003)
PY312 = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe")

## 화면 시험에 쓸 브라우저 후보 (STC-F-162, 163)
BROWSERS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
)


# ---------------------------------------------------------------- 지역 도우미


def _summary(d: dict[str, object]) -> dict[str, object]:
    """판정 비교 필드를 뽑고 notices를 정렬한다(집합 비교)."""
    s = summary(d)
    s["notices"] = sorted(s["notices"])
    return s


def _stale_ts(sim: Simulator) -> float:
    """지연 스냅샷 시각: T(GET /api/status timestamp_s) - 0.300."""
    return sim.now() - STALE_DELAY_S


def _runs(name: str, default: int) -> int:
    """반복 횟수를 환경 변수에서 읽는다(없으면 케이스 사양 값)."""
    return int(os.environ.get(name, default))


def _free_port() -> int:
    """비어 있는 루프백 포트를 구한다."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(predicate, timeout: float = 5.0, period: float = 0.01) -> bool:
    """조건이 참이 될 때까지 기다린다. 제한 시간 안에 참이 되면 True."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(period)
    return bool(predicate())


# ---------------------------------------------------------------- 브라우저(CDP) 도우미


class _WebSocket:
    """표준 라이브러리만으로 만든 최소 WebSocket 클라이언트(CDP 통신용)."""

    def __init__(self, url: str) -> None:
        parts = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self._recv_some()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        assert b" 101 " in head.split(b"\r\n")[0], head

    def _recv_some(self) -> bytes:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("WebSocket 연결 종료")
        return chunk

    def _exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            self.buf += self._recv_some()
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def send(self, text: str) -> None:
        data = text.encode()
        n = len(data)
        header = bytearray([0x81])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += n.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += n.to_bytes(8, "big")
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _frame(self) -> tuple[int, bool, bytes]:
        b1, b2 = self._exact(2)
        n = b2 & 0x7F
        if n == 126:
            n = int.from_bytes(self._exact(2), "big")
        elif n == 127:
            n = int.from_bytes(self._exact(8), "big")
        mask = self._exact(4) if b2 & 0x80 else b""
        data = self._exact(n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return b1 & 0x0F, bool(b1 & 0x80), data

    def recv(self) -> str:
        parts: list[bytes] = []
        while True:
            opcode, fin, data = self._frame()
            if opcode == 0x8:
                raise ConnectionError("WebSocket 닫힘")
            if opcode in (0x9, 0xA):
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode()

    def close(self) -> None:
        self.sock.close()


class _Browser:
    """헤드리스 Edge/Chrome을 띄워 DevTools 프로토콜로 화면을 조작한다(사람의 조작 대행)."""

    def __init__(self, profile: Path) -> None:
        exe = next((p for p in BROWSERS if p.exists()), None)
        assert exe is not None, "시험 환경에 Edge/Chrome이 없습니다(화면 시험 불가)"
        profile.mkdir(parents=True, exist_ok=True)
        args = [
            str(exe),
            "--headless=new",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "about:blank",
        ]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = profile / "DevToolsActivePort"
        assert _wait_for(port_file.exists, timeout=30), "브라우저 DevTools 포트를 얻지 못했습니다"
        _wait_for(lambda: port_file.read_text().strip() != "", timeout=5)
        port = int(port_file.read_text().split()[0])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/json/list")
        targets = json.loads(conn.getresponse().read())
        conn.close()
        page = next(t for t in targets if t["type"] == "page")
        self.ws = _WebSocket(page["webSocketDebuggerUrl"])
        self.next_id = 0

    def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.next_id:
                assert "error" not in msg, msg
                return msg["result"]

    def eval(self, expression: str) -> object:
        """페이지에서 JavaScript 식을 평가하고 값을 돌려준다."""
        res = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        assert "exceptionDetails" not in res, res
        return res["result"].get("value")

    def open(self, url: str) -> None:
        """화면을 열고 로드를 기다린 뒤 POST 완료(show 반영) 계수기를 심는다."""
        self.call("Page.navigate", {"url": url})
        ok = _wait_for(
            lambda: self.eval(
                "document.readyState === 'complete' && !!document.getElementById('send')"
            )
        )
        assert ok, "화면 로드 실패"
        # 관찰용 계수기: 스냅샷 POST 응답의 json()이 끝나고 show()까지 실행된 뒤 1 증가
        self.eval(
            """(() => {
              window.__done = 0;
              const orig = window.fetch.bind(window);
              window.fetch = async (u, o) => {
                const res = await orig(u, o);
                if (u === '/api/snapshot') {
                  const j = res.json.bind(res);
                  res.json = async () => {
                    const v = await j();
                    setTimeout(() => { window.__done++; }, 0);
                    return v;
                  };
                }
                return res;
              };
              return true;
            })()"""
        )

    def click_and_wait(self, button_id: str, posts: int) -> None:
        """버튼을 누르고 스냅샷 POST posts건이 화면에 반영될 때까지 기다린다."""
        target = int(self.eval("window.__done")) + posts
        self.eval(f"document.getElementById('{button_id}').click(), true")
        assert _wait_for(lambda: int(self.eval("window.__done")) >= target), "전송 완료 대기 초과"

    def screen(self) -> dict[str, object]:
        """화면의 판정 표시를 summary와 같은 형식으로 읽는다."""
        raw = self.eval(
            """(() => { const t = (id) => document.getElementById(id).textContent;
              return {l: t('out_left'), r: t('out_right'), s: t('out_state'),
                      p: t('out_priority'), c: t('out_reason'), n: t('out_notices')}; })()"""
        )
        notices = [] if raw["n"] == "—" else raw["n"].split(", ")
        return {
            "lock_left": raw["l"].split()[-1],
            "lock_right": raw["r"].split()[-1],
            "state": raw["s"],
            "priority_reason": raw["p"],
            "reason_code": raw["c"],
            "notices": sorted(notices),
        }

    def history(self) -> list[list[str]]:
        """화면 결정 이력 표의 행을 오래된 순으로 읽는다: [id, 시각, 좌, 우, 상태, 이유]."""
        rows = self.eval(
            """Array.from(document.querySelectorAll('#events tr'))
                 .map(tr => Array.from(tr.children).map(td => td.textContent))"""
        )
        return list(reversed(rows))

    def close(self) -> None:
        with contextlib.suppress(OSError, ConnectionError):
            self.call("Browser.close")
        self.ws.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _set_controls(br: _Browser, values: dict[str, object]) -> None:
    """화면 입력 컨트롤 값을 설정한다(숫자·선택은 value, 체크박스는 checked)."""
    br.eval(
        f"""(() => {{ const v = {json.dumps(values)};
          for (const [k, x] of Object.entries(v)) {{
            const el = document.getElementById(k);
            if (el.type === 'checkbox') el.checked = x; else el.value = String(x);
          }} return true; }})()"""
    )


# ---------------------------------------------------------------- SWR-019 우선순위 조합


def test_stc_f_131_pict_sensor_fault_over_risk_stale(sim):
    """STC-F-131 (SWR-019) PICT 행: 센서 고장·접근위험·지연·ISOFIX·잠금 명령 조합은 FAULT."""
    sim.s_lock()
    ts = _stale_ts(sim)
    raw = b0(
        sensor_fault=True,
        rear_left_approach_risk=True,
        source_timestamp_s=ts,
        isofix_left=True,
        command=cmd("all", "lock"),
    )
    assert _summary(sim.send(raw)) == expect(
        "LOCK", "LOCK", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT"
    )


def test_stc_f_132_pict_crash_with_stale_fire_isofix(sim):
    """STC-F-132 (SWR-019) PICT 행: CONFIRMED·지연·화재·ISOFIX 조합은 EMERGENCY."""
    sim.s0()
    ts = _stale_ts(sim)
    raw = b0(crash_status="CONFIRMED", source_timestamp_s=ts, fire_detected=True, isofix_left=True)
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )


def test_stc_f_133_pict_crash_with_fault_risk_speed(sim):
    """STC-F-133 (SWR-019) PICT 행: CONFIRMED·센서 고장·접근위험·ISOFIX·차속 3.0은 EMERGENCY."""
    sim.s_lock()
    raw = b0(
        crash_status="CONFIRMED",
        sensor_fault=True,
        rear_left_approach_risk=True,
        isofix_left=True,
        vehicle_speed_kph=3.0,
    )
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )


def test_stc_f_134_pict_ignition_off_over_isofix_speed_cmd(sim):
    """STC-F-134 (SWR-019) PICT 행: 시동 OFF·ISOFIX·차속 3.0·잠금 명령은 좌·우 RELEASE OFF."""
    sim.s_lock()
    raw = b0(ignition_on=False, isofix_left=True, vehicle_speed_kph=3.0, command=cmd("all", "lock"))
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )


def test_stc_f_135_pict_crash_with_all_lower_rules(sim):
    """STC-F-135 (SWR-019) PICT 행: CONFIRMED와 하위 규칙 전부 동시 활성은 EMERGENCY."""
    sim.s0()
    ts = _stale_ts(sim)
    raw = b0(
        crash_status="CONFIRMED",
        sensor_fault=True,
        rear_left_approach_risk=True,
        source_timestamp_s=ts,
        isofix_left=True,
        vehicle_speed_kph=3.0,
        command=cmd("all", "lock"),
    )
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )


def test_stc_f_136_crash_beats_approach_risk(sim):
    """STC-F-136 (SWR-019) 순위 1과 3: CONFIRMED와 왼쪽 접근위험 동시면 좌·우 RELEASE."""
    sim.s0()
    raw = b0(crash_status="CONFIRMED", rear_left_approach_risk=True)
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )


def test_stc_f_137_crash_beats_fire_reason(sim):
    """STC-F-137 (SWR-019) 순위 1과 6: CONFIRMED와 화재 동시면 priority_reason은 CRASH."""
    sim.s_lock()
    raw = b0(crash_status="CONFIRMED", fire_detected=True)
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )


def test_stc_f_138_sensor_fault_holds_despite_risk(sim):
    """STC-F-138 (SWR-019) 순위 2와 3: 센서 고장과 접근위험 동시면 직전 출력 유지(FAULT)."""
    sim.s0()
    raw = b0(sensor_fault=True, rear_left_approach_risk=True)
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT"
    )


def test_stc_f_139_sensor_fault_state_over_degraded(sim):
    """STC-F-139 (SWR-019) 순위 2와 4: 센서 고장과 지연 동시면 상태 FAULT."""
    sim.s_lock()
    raw = b0(sensor_fault=True, source_timestamp_s=_stale_ts(sim))
    assert _summary(sim.send(raw)) == expect(
        "LOCK", "LOCK", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT"
    )


def test_stc_f_140_risk_and_ignition_off_split_sides(sim):
    """STC-F-140 (SWR-019) 순위 3과 5: 접근위험 쪽 LOCK, 반대쪽 RELEASE, 상태 OFF."""
    sim.s_lock()
    raw = b0(rear_left_approach_risk=True, ignition_on=False)
    assert _summary(sim.send(raw)) == expect(
        "LOCK", "RELEASE", "OFF", "APPROACH_RISK", "APPROACH_RISK"
    )


def test_stc_f_141_risk_and_fire_split_sides(sim):
    """STC-F-141 (SWR-019) 순위 3과 6: 접근위험 쪽 LOCK, 남은 쪽만 화재 해제."""
    sim.s_lock()
    raw = b0(rear_left_approach_risk=True, fire_detected=True)
    assert _summary(sim.send(raw)) == expect(
        "LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK"
    )


def test_stc_f_142_risk_and_speed_reason_is_risk(sim):
    """STC-F-142 (SWR-019) 순위 3과 8: 좌·우 LOCK, priority_reason은 APPROACH_RISK."""
    sim.s0()
    raw = b0(rear_left_approach_risk=True, vehicle_speed_kph=3.0)
    assert _summary(sim.send(raw)) == expect(
        "LOCK", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK"
    )


def test_stc_f_143_ignition_off_and_fire_reason(sim):
    """STC-F-143 (SWR-019) 순위 5와 6: 시동 OFF와 화재 동시면 IGNITION_OFF, 상태 OFF."""
    sim.s_lock()
    raw = b0(ignition_on=False, fire_detected=True)
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )


def test_stc_f_144_ignition_off_beats_speed_and_lock(sim):
    """STC-F-144 (SWR-019) 순위 5와 8, 9: 시동 OFF가 차속 3.0과 잠금 명령을 이김."""
    sim.s0()
    raw = b0(ignition_on=False, vehicle_speed_kph=3.0, command=cmd("all", "lock"))
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )


def test_stc_f_145_fire_beats_isofix_speed_lock(sim):
    """STC-F-145 (SWR-019) 순위 6~9: 화재가 ISOFIX·차속·잠금 명령보다 앞서 좌·우 RELEASE."""
    sim.s0()
    raw = b0(
        fire_detected=True, isofix_left=True, vehicle_speed_kph=3.0, command=cmd("all", "lock")
    )
    assert _summary(sim.send(raw)) == expect(
        "RELEASE", "RELEASE", "NORMAL", "FORCED_RELEASE", "FIRE"
    )


def test_stc_f_146_isofix_reason_over_speed(sim):
    """STC-F-146 (SWR-019) 순위 7과 8: 좌·우 LOCK, priority_reason은 ISOFIX."""
    sim.s0()
    raw = b0(isofix_left=True, vehicle_speed_kph=3.0)
    assert _summary(sim.send(raw)) == expect("LOCK", "LOCK", "NORMAL", "ISOFIX", "ISOFIX")


# ---------------------------------------------------------------- SWR-020 시동 OFF


def test_stc_f_147_ignition_off_then_on(sim):
    """STC-F-147 (SWR-020) 시동 OFF 첫 평가에 좌·우 RELEASE OFF, ON 복귀 시 출력 유지 NORMAL."""
    sim.s_lock()
    assert _summary(sim.send(b0(ignition_on=False))) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )
    assert _summary(sim.send(b0())) == expect("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")


def test_stc_f_148_ignition_off_with_crash_relatches(sim):
    """STC-F-148 (SWR-020) 같은 스냅샷의 시동 OFF와 CONFIRMED는 초기화 후 래치 재설정."""
    sim.s0()
    emergency = expect("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")
    assert _summary(sim.send(b0(ignition_on=False, crash_status="CONFIRMED"))) == emergency
    assert _summary(sim.send(b0())) == emergency
    assert _summary(sim.send(b0(ignition_on=False))) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )
    assert _summary(sim.send(b0())) == expect("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")


def test_stc_f_149_invalid_if009_does_not_clear_latch(sim):
    """STC-F-149 (SWR-020) IF-009 무효(sensor_fault 누락)인 시동 OFF는 래치를 해제하지 않음."""
    sim.s_lock()
    sim.send(b0(crash_status="CONFIRMED"))
    assert _summary(sim.send(b0(ignition_on=False, sensor_fault=DROP))) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )
    assert _summary(sim.send(b0(ignition_on=False))) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )


def test_stc_f_150_ignition_off_with_fault_keeps_latch(sim):
    """STC-F-150 (SWR-020) 센서 고장 중 시동 OFF는 래치 유지, 정상 시동 OFF에서만 초기화 (개정)."""
    sim.s_lock()
    sim.send(b0(crash_status="CONFIRMED"))
    observed = [
        _summary(sim.send(b0(ignition_on=False, sensor_fault=True))),  # (a)
        _summary(sim.send(b0())),  # (b)
        _summary(sim.send(b0(ignition_on=False))),  # (c)
        _summary(sim.send(b0())),  # (d)
    ]
    emergency = expect("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")
    assert observed == [
        emergency,
        emergency,
        expect("RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"),
        expect("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE"),
    ]


def test_stc_f_151_lock_command_ignored_during_off(sim):
    """STC-F-151 (SWR-020) 시동 OFF 중 잠금 명령은 무시되고 ON 복귀 후에도 보류되지 않음."""
    sim.s0()
    assert _summary(sim.send(b0(ignition_on=False, command=cmd("all", "lock")))) == expect(
        "RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF"
    )
    assert _summary(sim.send(b0())) == expect("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")


# ---------------------------------------------------------------- SWR-021 센서 고장

FAULT_MIX = expect("LOCK", "RELEASE", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT")


def test_stc_f_152_sensor_fault_holds_mixed_output(sim):
    """STC-F-152 (SWR-021) 센서 고장 첫 평가에 혼합 출력(L=LOCK, R=RELEASE) 유지, FAULT."""
    sim.s_mix()
    assert _summary(sim.send(b0(sensor_fault=True))) == FAULT_MIX


def test_stc_f_153_sensor_fault_ignores_all_inputs(sim):
    """STC-F-153 (SWR-021) 센서 고장 중 차속·명령·접근위험·화재 입력에도 출력 유지."""
    sim.s_mix()
    observed = {}
    observed["a"] = _summary(sim.send(b0(sensor_fault=True, vehicle_speed_kph=3.0)))
    observed["b"] = _summary(sim.send(b0(sensor_fault=True, command=cmd("all", "lock"))))
    sim.send(b0(sensor_fault=True))  # 명령 단계 사이의 명령 없는 스냅샷(판정 대상 아님)
    observed["c"] = _summary(sim.send(b0(sensor_fault=True, command=cmd("all", "unlock"))))
    observed["d"] = _summary(sim.send(b0(sensor_fault=True, rear_right_approach_risk=True)))
    observed["e"] = _summary(sim.send(b0(sensor_fault=True, fire_detected=True)))
    # (c) 해제 명령은 상위 규칙이 결정한 쪽이므로 DRIVER_UNLOCK_REJECTED (SWR-004 (d), 케이스 개정)
    expected = dict.fromkeys("abde", FAULT_MIX)
    expected["c"] = {**FAULT_MIX, "notices": ["DRIVER_UNLOCK_REJECTED"]}
    assert observed == expected


def test_stc_f_154_fault_command_not_deferred(sim):
    """STC-F-154 (SWR-021) 고장 중 해제 명령은 보류되지 않고, 해소 후 정상 평가 재개."""
    sim.s_mix()
    observed = [
        _summary(sim.send(b0(sensor_fault=True, command=cmd("all", "unlock")))),  # (a)
        _summary(sim.send(b0())),  # (b)
        _summary(sim.send(b0(vehicle_speed_kph=3.0))),  # (c)
    ]
    assert observed == [
        {**FAULT_MIX, "notices": ["DRIVER_UNLOCK_REJECTED"]},  # SWR-004 (d), 케이스 개정
        expect("LOCK", "RELEASE", "NORMAL", "NONE", "NO_CHANGE"),
        expect("LOCK", "LOCK", "NORMAL", "AUTO_LOCK", "AUTO_LOCK_SPEED"),
    ]


# ---------------------------------------------------------------- SWR-022 입력 중단 감시


def test_stc_f_155_input_stop_boundary_polling(sim):
    """STC-F-155 (SWR-022) 입력 중단 경계: age 200 ms 이하 NORMAL, 첫 DEGRADED는 201~300 ms."""
    sim.s_lock()
    t = sim.now()
    sim.send(b0(source_timestamp_s=t))
    records: list[tuple[int, dict[str, object]]] = []
    while not records or records[-1][0] < 350:
        d = sim.status()
        records.append((round((float(d["timestamp_s"]) - t) * 1000), d))
        time.sleep(0.01)
    normal = expect("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    degraded = expect("LOCK", "LOCK", "DEGRADED", "DEGRADED", "INPUT_STALE")
    for age, d in records:
        if age <= 200:
            assert (age, _summary(d), d["input_validity"]["FRESHNESS"]) == (age, normal, "VALID")
        else:
            assert (age, _summary(d), d["input_validity"]["FRESHNESS"]) == (
                age,
                degraded,
                "STALE",
            )
    # 합격 기준: 첫 DEGRADED 폴링의 age_ms가 201 이상 300 이하
    first = next(age for age, d in records if d["state"] == "DEGRADED")
    assert 201 <= first <= 300, [age for age, _ in records]


def test_stc_f_156_tick_thread_detects_input_stop(sim):
    """STC-F-156 (SWR-022) 상태 조회 없이 tick 스레드만으로 입력 중단을 200~300 ms에 기록."""
    t = sim.now()
    sim.send(b0(source_timestamp_s=t))
    time.sleep(0.5)
    events = sim.events()
    observed = [(e["event_id"], e["state"], e["priority_reason"], e["reason_code"]) for e in events]
    delay = float(events[-1]["timestamp_s"]) - t
    print(f"STC-F-156 감지 지연 {delay * 1000:.1f} ms, 이벤트 {observed}")
    # 이벤트 2건이고 2번(마지막) 이벤트가 DEGRADED/INPUT_STALE, 감지 지연 200 ms 초과 300 ms 이하
    assert (len(events), observed[-1][1:], 0.200 < delay <= 0.300) == (
        2,
        ("DEGRADED", "DEGRADED", "INPUT_STALE"),
        True,
    )


def test_stc_f_157_resume_input_returns_normal(sim):
    """STC-F-157 (SWR-022) 입력 재개 시 DEGRADED에서 NORMAL로 복귀하고 출력 유지."""
    sim.s_lock()
    time.sleep(0.4)
    assert _summary(sim.status()) == expect("LOCK", "LOCK", "DEGRADED", "DEGRADED", "INPUT_STALE")
    assert _summary(sim.send(b0())) == expect("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")


def test_stc_f_158_no_monitoring_before_first_snapshot(sim):
    """STC-F-158 (SWR-022) 첫 스냅샷 전에는 입력 중단 감시를 하지 않음(DEF-06)."""
    initial = expect("RELEASE", "RELEASE", "OFF", "NONE", "NO_CHANGE")
    observed = []
    for _ in range(15):  # 1.5 s 동안 100 ms 간격
        observed.append(_summary(sim.status()))
        time.sleep(0.1)
    events = sim.events()
    after = _summary(sim.send(b0()))
    assert (observed, events, after) == (
        [initial] * 15,
        [],
        expect("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE"),
    )


def test_stc_f_159_input_stop_keeps_emergency(sim):
    """STC-F-159 (SWR-022) 입력 중단 중에도 충돌 래치(EMERGENCY)는 DEGRADED로 바뀌지 않음."""
    sim.s_lock()
    sim.send(b0(crash_status="CONFIRMED"))
    time.sleep(0.4)
    assert _summary(sim.status()) == expect(
        "RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED"
    )


def test_stc_f_160_input_stop_keeps_fault(sim):
    """STC-F-160 (SWR-022) 입력 중단 중에도 센서 고장(FAULT)은 DEGRADED로 바뀌지 않음."""
    sim.s_lock()
    sim.send(b0(sensor_fault=True))
    time.sleep(0.4)
    assert _summary(sim.status()) == expect(
        "LOCK", "LOCK", "FAULT", "SENSOR_FAULT", "W_SENSOR_FAULT"
    )


def test_stc_f_161_slow_150ms_input_no_false_degraded(sim):
    """STC-F-161 (SWR-022) 150 ms 주기 입력과 30 ms 상태 조회 5 s 동안 DEGRADED 오탐 없음."""
    sim.s_lock()
    results: list[tuple[str, dict[str, object]]] = []
    errors: list[BaseException] = []
    stop = threading.Event()

    def poll() -> None:
        try:
            while not stop.wait(0.03):
                results.append(("GET", sim.status()))
        except BaseException as exc:  # 스레드 예외를 본 스레드에서 판정
            errors.append(exc)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    start = time.monotonic()
    k = 0
    while time.monotonic() - start < 5.0:
        results.append(("POST", sim.send(b0())))
        k += 1
        time.sleep(max(0.0, start + 0.150 * k - time.monotonic()))
    stop.set()
    poller.join()
    assert errors == []
    normal = expect("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    bad = [(kind, _summary(d)) for kind, d in results if _summary(d) != normal]
    assert bad == [], f"{len(bad)}/{len(results)} 응답 불일치"
    assert [e for e in sim.events() if e["state"] == "DEGRADED"] == []


# ---------------------------------------------------------------- SWR-025 시뮬레이터 화면

## 화면 입력 필드와 설정 가능한 값(SWRS 3.6 표, 운전자 명령)
SCREEN_FIELDS: dict[str, list[object]] = {
    "vehicle_speed_kph": ["3", "0"],
    "gear": ["P", "N", "D", "R"],
    "crash_status": ["NONE", "PENDING", "CONFIRMED"],
    "rear_left_approach_risk": [True, False],
    "rear_right_approach_risk": [True, False],
    "cmd_side": ["left", "right", "all"],
    "cmd_action": ["lock", "unlock"],
    "cmd_source": ["physical_button", "avn", "voice", "mobile_app"],
    "fire_detected": [True, False],
    "overtemperature_detected": [True, False],
    "adult_present": [True, False],
    "isofix_left": [True, False],
    "isofix_right": [True, False],
    "ignition_on": [False, True],
    "sensor_fault": [True, False],
}

## 화면 기준값(B0와 같은 값)
SCREEN_B0: dict[str, object] = {
    "vehicle_speed_kph": "0",
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


def _settable_fields(br: _Browser) -> dict[str, bool]:
    """각 입력 필드가 존재하고 모든 유효 값으로 설정·재확인되는지 확인한다."""
    return br.eval(
        f"""(() => {{ const spec = {json.dumps(SCREEN_FIELDS)}; const out = {{}};
          for (const [id, vals] of Object.entries(spec)) {{
            const el = document.getElementById(id);
            out[id] = !!el && vals.every(x => {{
              if (el.type === 'checkbox') {{ el.checked = x; return el.checked === x; }}
              el.value = String(x); return el.value === String(x); }});
          }} return out; }})()"""
    )


def test_stc_f_162_screen_inputs_match_status(sim, tmp_path):
    """STC-F-162 (SWR-025) 화면에서 모든 입력을 설정해 전송하면 화면 표시와 /api/status가 같음."""
    br = _Browser(tmp_path / "profile")
    try:
        br.open(f"http://127.0.0.1:{sim.port}/")
        assert _settable_fields(br) == dict.fromkeys(SCREEN_FIELDS, True)
        _set_controls(
            br,
            {
                **SCREEN_B0,
                "vehicle_speed_kph": "3.0",
                "gear": "D",
                "rear_left_approach_risk": True,
                "isofix_right": True,
            },
        )
        br.click_and_wait("send", posts=1)  # 명령 없음: 스냅샷 전송 버튼
        screen = br.screen()
        status = _summary(sim.status())
    finally:
        br.close()
    expected = expect("LOCK", "LOCK", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    assert (screen, status) == (expected, expected)


def test_stc_f_163_screen_command_and_history(sim, tmp_path):
    """STC-F-163 (SWR-025) 화면의 운전자 명령·시동 OFF 전송과 결정 이력 표시가 API와 일치."""
    br = _Browser(tmp_path / "profile")
    try:
        br.open(f"http://127.0.0.1:{sim.port}/")
        _set_controls(br, SCREEN_B0)
        br.click_and_wait("send", posts=1)  # (1) 기준값 전송
        _set_controls(br, {"cmd_side": "right", "cmd_action": "lock", "cmd_source": "mobile_app"})
        br.click_and_wait("send_cmd", posts=2)  # (2) 명령 전송(화면은 명령 없는 스냅샷을 이어 보냄)
        step2 = (br.screen(), _summary(sim.status()))
        _set_controls(br, {"ignition_on": False})
        br.click_and_wait("send", posts=1)  # (3) 시동 OFF, 명령 없음
        step3 = (br.screen(), _summary(sim.status()))
        time.sleep(1.2)  # 이력 표는 0.5 s 주기 갱신
        shown = [[r[0], r[2], r[3], r[4], r[5]] for r in br.history()]
        api = [
            [str(e["event_id"]), e["lock_left"], e["lock_right"], e["state"], e["reason_code"]]
            for e in sim.events()
        ]
    finally:
        br.close()
    # (2)는 화면의 후속 명령 없는 스냅샷 판정이 보인다 (케이스 개정, SWDD 12장)
    exp2 = expect("RELEASE", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    exp3 = expect("RELEASE", "RELEASE", "OFF", "IGNITION_OFF", "IGNITION_OFF")
    assert (step2, step3) == ((exp2, exp2), (exp3, exp3))
    # 이력: 화면 표와 API가 건수·순서·값 모두 같고, DRIVER_LOCK(우 LOCK) 뒤에 IGNITION_OFF가 있다
    assert shown == api
    codes = [(row[2], row[4]) for row in api]
    lock_at = codes.index(("LOCK", "DRIVER_LOCK"))
    assert any(code == "IGNITION_OFF" for _, code in codes[lock_at + 1 :])


# ---------------------------------------------------------------- SWR-026 입력 필드 제한


def test_stc_f_164_unknown_top_level_field_rejected(sim):
    """STC-F-164 (SWR-026) 정의 외 최상위 필드(camera_image)는 400, 유효 입력도 처리 안 함."""
    sim.s0()
    n = len(sim.events())
    code, _ = sim.post(b0(vehicle_speed_kph=3.0, camera_image="AAAA"))
    assert code == 400
    assert _summary(sim.status()) == expect("RELEASE", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    assert len(sim.events()) == n


def test_stc_f_165_unknown_command_field_rejected(sim):
    """STC-F-165 (SWR-026) command 안의 정의 외 필드(driver_id)는 400, 명령 미적용."""
    sim.s_mix()
    n = len(sim.events())
    bad_cmd = {"side": "all", "action": "lock", "source": "avn", "driver_id": "d1"}
    code, _ = sim.post(b0(command=bad_cmd))
    assert code == 400
    assert _summary(sim.status()) == expect("LOCK", "RELEASE", "NORMAL", "NONE", "NO_CHANGE")
    assert len(sim.events()) == n


def test_stc_f_166_case_variant_field_rejected(sim):
    """STC-F-166 (SWR-026) 대소문자만 다른 필드(Ignition_On)도 400으로 거절."""
    sim.s0()
    n = len(sim.events())
    body = b0(ignition_on=DROP)
    body["Ignition_On"] = True
    code, _ = sim.post(body)
    assert code == 400
    assert len(sim.events()) == n


def test_stc_f_167_adult_present_integer_invalid(sim):
    """STC-F-167 (SWR-026) adult_present=1(정수)은 IF-007 무효로 강제 해제 없음."""
    sim.s_lock()
    d = sim.send(b0(adult_present=1))
    assert _summary(d) == expect("LOCK", "LOCK", "NORMAL", "NONE", "NO_CHANGE")
    assert d["input_validity"]["IF-007"] == "INVALID"


# ---------------------------------------------------------------- 비기능

## 대표 입력 5종(STC-NF-001)
REPRESENTATIVE = [
    b0(),
    b0(vehicle_speed_kph=3.0),
    b0(rear_left_approach_risk=True),
    b0(isofix_left=True),
    b0(crash_status="PENDING"),
]


def _rtt_ms(sim: Simulator, body: bytes) -> float:
    """POST 1건의 왕복 시간(ms)을 잰다."""
    start = time.perf_counter()
    code, _ = sim.request_raw("POST", "/api/snapshot", body)
    elapsed = (time.perf_counter() - start) * 1000
    assert code == 200
    return elapsed


def test_stc_nf_001_end_to_end_response_time(sim):
    """STC-NF-001 (SWR-023) 대표 입력 1,000회 끝단 간 반응 시간 최대 100 ms·평균 20 ms 이하.

    SWR-023(1회 평가 10 ms 이하) 자체는 통합 시험 ITC-05에서 프로세스 내 측정으로 검증한다.
    """
    bodies = [json.dumps(r).encode() for r in REPRESENTATIVE]
    for i in range(100):  # 워밍업(결과 제외)
        _rtt_ms(sim, bodies[i % 5])
        time.sleep(0.02)
    samples = []
    for i in range(1000):
        samples.append((_rtt_ms(sim, bodies[i % 5]), i))
        time.sleep(0.02)
    values = sorted(v for v, _ in samples)
    stats = {
        "max": values[-1],
        "p99.9": values[int(len(values) * 0.999) - 1],
        "mean": sum(values) / len(values),
    }
    print(f"STC-NF-001 왕복 시간(ms): {stats}")
    assert stats["max"] <= 100.0, stats
    assert stats["mean"] <= 20.0, stats


def _nf002_vector() -> list[dict[str, object]]:
    """STC-NF-002 입력 벡터 V(20건): 요구사항 전 규칙을 지나간다."""
    return [
        b0(),
        b0(vehicle_speed_kph=3.0),
        b0(vehicle_speed_kph=0.0),
        b0(command=cmd("all", "unlock")),
        N,
        {**N, "command": cmd("left", "unlock")},
        N,
        {**N, "command": cmd("left", "unlock")},
        {**N, "command": cmd("left", "lock")},
        b0(),
        b0(command=cmd("right", "unlock", "avn")),
        b0(command=cmd("left", "unlock", "voice")),
        b0(crash_status="PENDING", command={"side": "center", "action": "lock", "source": "avn"}),
        b0(isofix_right=True, crash_status="PENDING", command=cmd("all", "unlock", "mobile_app")),
        b0(fire_detected=True, overtemperature_detected=True, adult_present=True),
        b0(gear="X", crash_status=DROP),
        b0(sensor_fault=True, command=cmd("all", "lock")),
        b0(crash_status="CONFIRMED", rear_right_approach_risk=True),
        b0(ignition_on=False),
        b0(),
    ]


def _nf002_run(vector: list[dict[str, object]]) -> str:
    """서버를 새로 기동해 V를 재생하고 스냅샷 판정 응답(timestamp_s 제외)을 직렬화한다.

    결정 이력은 비교하지 않는다(케이스 개정): 실제 시계 tick이 스냅샷 사이에 몇 번 끼는지가
    실행마다 달라 tick 이벤트 수가 달라질 수 있다. 이력 포함 결정론은 통합 시험 ITC-04(고정 시계).
    """
    sim = Simulator()
    try:
        responses = []
        for raw in vector:
            d = sim.send(raw)
            d.pop("timestamp_s")
            responses.append(d)
            time.sleep(0.05)
    finally:
        sim.stop()
    return json.dumps({"responses": responses}, sort_keys=True)


def test_stc_nf_002_determinism_across_restarts(monkeypatch):
    """STC-NF-002 (SWR-016) 서버 재기동 후 같은 입력 벡터 재생 결과 해시가 모두 같음."""
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)  # 기동마다 해시 시드가 달라지게 함
    runs = _runs("STC_NF_002_RUNS", 1000)
    vector = _nf002_vector()
    first = _nf002_run(vector)
    hashes = {hashlib.sha256(first.encode()).hexdigest()}
    diffs = []
    for k in range(1, runs):
        text = _nf002_run(vector)
        hashes.add(hashlib.sha256(text.encode()).hexdigest())
        if text != first and len(diffs) < 3:
            a, b = json.loads(first), json.loads(text)
            diffs.append(
                (
                    k,
                    [
                        i
                        for i, (x, y) in enumerate(zip(a["responses"], b["responses"], strict=True))
                        if x != y
                    ],
                )
            )
    print(f"STC-NF-002 반복 {runs}회, 해시 종류 {len(hashes)}")
    assert (len(hashes), diffs) == (1, [])


class _VenvSimulator(Simulator):
    """새 가상환경에 설치한 패키지로 시뮬레이터를 기동한다(PYTHONPATH 없이)."""

    def __init__(self, python: Path, cwd: Path, log: Path) -> None:
        self.port = _free_port()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
        }
        self.log = log.open("wb")
        self.proc = subprocess.Popen(
            [str(python), "-m", "child_lock.web", "--port", str(self.port)],
            cwd=cwd,
            env=env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self._wait_ready()

    def stop(self) -> None:
        super().stop()
        self.log.close()


def _make_py312_venv(tmp_path: Path) -> Path:
    """Python 3.12 새 venv를 만들고 외부 패키지 없이 프로젝트만 설치한다(복사본에서)."""
    assert PY312.exists(), f"Python 3.12 없음: {PY312}"
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", proj / "pyproject.toml")
    shutil.copytree(ROOT / "src", proj / "src", ignore=shutil.ignore_patterns("__pycache__"))
    venv = tmp_path / "venv312"
    subprocess.run([str(PY312), "-m", "venv", str(venv)], check=True, timeout=300)
    py = venv / "Scripts" / "python.exe"
    # --no-deps: 의존성 설치 금지. 빌드 도구(setuptools)는 pip 격리 빌드 환경에만 쓰이고
    # venv에는 남지 않음
    pip = [str(py), "-m", "pip", "--disable-pip-version-check", "install", "--no-deps", str(proj)]
    subprocess.run(pip, check=True, timeout=600, capture_output=True)
    return py


def test_stc_nf_003_python312_stdlib_only(tmp_path):
    """STC-NF-003 (SWR-024) Python 3.12 새 venv에서 기동·동작하고 런타임 의존성이 없음."""
    py = _make_py312_venv(tmp_path)
    version = subprocess.run(
        [str(py), "-c", "import sys; print(sys.version_info[:2])"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert version == "(3, 12)"
    sim = _VenvSimulator(py, tmp_path, tmp_path / "server.log")
    try:
        sim.s0()
        d = sim.send(b0(rear_left_approach_risk=True))
    finally:
        sim.stop()
    assert _summary(d) == expect("LOCK", "RELEASE", "NORMAL", "APPROACH_RISK", "APPROACH_RISK")
    assert b"Traceback" not in (tmp_path / "server.log").read_bytes()
    with (ROOT / "pyproject.toml").open("rb") as f:
        assert tomllib.load(f)["project"]["dependencies"] == []
    listed = subprocess.run(
        [str(py), "-m", "pip", "--disable-pip-version-check", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names = {p["name"].lower() for p in json.loads(listed)}
    assert names - {"pip", "setuptools", "child-lock"} == set()


def test_stc_nf_004_input_stop_detection_20_times(sim):
    """STC-NF-004 (SWR-022) 입력 중단 20회 반복: 감지 시각이 매번 200 ms 초과 300 ms 이하."""
    runs = _runs("STC_NF_004_RUNS", 20)
    failures = []
    for k in range(runs):
        t = sim.now()
        sim.send(b0(source_timestamp_s=t))
        time.sleep(0.5)
        last = sim.events()[-1]
        delay = float(last["timestamp_s"]) - t
        ok = (last["state"], last["reason_code"]) == ("DEGRADED", "INPUT_STALE")
        if not (ok and 0.200 < delay <= 0.300):
            failures.append((k, last["state"], last["reason_code"], round(delay, 4)))
        recovered = sim.send(b0())
        if recovered["state"] != "NORMAL":
            failures.append((k, "복구", recovered["state"]))
    assert failures == []


def test_stc_nf_005_crash_reaction_100_times(sim):
    """STC-NF-005 (SWR-007, SWR-023) CONFIRMED 응답에 RELEASE 반영, 응답 300 ms 이내 100회."""
    runs = _runs("STC_NF_005_RUNS", 100)
    emergency = expect("RELEASE", "RELEASE", "EMERGENCY", "CRASH", "CRASH_CONFIRMED")
    failures = []
    worst = 0.0
    for k in range(runs):
        sim.send(b0(command=cmd("all", "lock")))
        sim.send(b0())
        start = time.perf_counter()
        d = sim.send(b0(crash_status="CONFIRMED"))
        elapsed = time.perf_counter() - start
        worst = max(worst, elapsed)
        if _summary(d) != emergency or elapsed > 0.300:
            failures.append((k, _summary(d), elapsed))
        sim.send(b0(ignition_on=False))
        sim.send(b0())
    print(f"STC-NF-005 최대 응답 시간 {worst * 1000:.2f} ms")
    assert failures == []


def test_stc_nf_006_invalid_input_reaction_100_times(sim):
    """STC-NF-006 (SWR-013, SWR-023) IF-002 무효 응답에 DEGRADED 반영, 100 ms 이내 100회."""
    runs = _runs("STC_NF_006_RUNS", 100)
    failures = []
    worst = 0.0
    for k in range(runs):
        sim.send(b0())
        start = time.perf_counter()
        d = sim.send(b0(crash_status=DROP))
        elapsed = time.perf_counter() - start
        worst = max(worst, elapsed)
        got = (d["state"], d["priority_reason"], d["reason_code"])
        if got != ("DEGRADED", "DEGRADED", "INPUT_INVALID") or elapsed > 0.100:
            failures.append((k, got, elapsed))
        sim.send(b0())
    print(f"STC-NF-006 최대 응답 시간 {worst * 1000:.2f} ms")
    assert failures == []


def test_stc_nf_007_concurrent_posts_event_ids(sim):
    """STC-NF-007 (SWR-010, SWR-015) 4개 클라이언트 동시 POST 800건: 모두 200, event_id 연속."""
    barrier = threading.Barrier(4)
    results: list[list[tuple[int, object]]] = [[] for _ in range(4)]
    body = json.dumps(b0()).encode()

    def client(idx: int) -> None:
        barrier.wait()
        for _ in range(200):
            try:
                code, data = sim.request_raw("POST", "/api/snapshot", body)
                results[idx].append((code, json.loads(data).get("timestamp_s")))
            except OSError as exc:
                results[idx].append((-1, repr(exc)))

    threads = [threading.Thread(target=client, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    flat = [r for rs in results for r in rs]
    codes = {code for code, _ in flat}
    events = sim.events()
    ids = [e["event_id"] for e in events]
    stamps = [float(e["timestamp_s"]) for e in events]
    response_stamps = {ts for code, ts in flat if code == 200}
    print(f"STC-NF-007 이벤트 상태 {sorted({e['state'] for e in events})}, 첫 id {ids[:1]}")
    # 응답 시각과 모순 없음: 각 이벤트 시각은 어떤 응답의 시각이고, event_id 순으로 줄지 않는다
    observed = {
        "responses": (len(flat), codes),
        "event_ids": ids,
        "stamps_not_in_responses": [ts for ts in stamps if ts not in response_stamps],
        "stamps_sorted": stamps == sorted(stamps),
    }
    assert observed == {
        "responses": (800, {200}),
        "event_ids": list(range(701, 801)),
        "stamps_not_in_responses": [],
        "stamps_sorted": True,
    }
