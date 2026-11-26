"""!
@brief SWU-10 Web 시뮬레이터 실행 진입점 (QM).

사용법: python -m child_lock.web [--host H] [--port P]
런타임을 직접 호출하지 않고 응용 서비스만 쓴다(SWAD DEP-05). (SWDD 11장)
"""

import argparse
import sys

from child_lock.app.service import create_service
from child_lock.web.server import make_server


def main(argv: list[str] | None = None) -> int:
    """!
    @brief 서비스와 HTTP 서버를 시작하고 Ctrl+C까지 실행한다.
    @param argv 명령줄 인자(None이면 sys.argv 사용)
    @return 종료 코드
    """
    parser = argparse.ArgumentParser(description="전자식 차일드락 Web 시뮬레이터")
    parser.add_argument("--host", default="127.0.0.1", help="바인드 주소")
    parser.add_argument("--port", type=int, default=8000, help="포트")
    args = parser.parse_args(argv)
    service = create_service()
    server = make_server(service, host=args.host, port=args.port)
    service.start()
    print(f"차일드락 시뮬레이터: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
