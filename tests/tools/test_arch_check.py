"""!
@brief tools/arch_check.py 단위 시험 (SWAD 의존 규칙 DEP-01~05, 정적 분석 SA-05).
"""

from pathlib import Path

from tools import arch_check


def _package(root: Path, files: dict[str, str]) -> Path:
    pkg = root / "child_lock"
    for rel, text in files.items():
        path = pkg / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return pkg


def test_clean_package_has_no_violations(tmp_path):
    pkg = _package(
        tmp_path,
        {
            "core/model.py": "import dataclasses\nfrom enum import Enum\n",
            "core/rules.py": "from child_lock.core import model\nimport math\n",
            "runtime/runtime.py": "import threading\nfrom child_lock.core.controller import C\n",
            "app/service.py": "from child_lock.runtime.runtime import R\nimport collections\n",
            "web/server.py": "import json\nfrom child_lock.app import service\n"
            "from child_lock.core.model import Decision\n",
        },
    )
    assert arch_check.check_package(pkg) == []


def test_core_must_not_import_outer_layers_or_non_allowlisted_stdlib(tmp_path):
    pkg = _package(
        tmp_path,
        {"core/bad.py": "import time\nfrom child_lock.app import service\nimport os.path\n"},
    )
    assert arch_check.check_package(pkg) == [
        "core/bad.py:1 core 허용 목록 밖 import: time (DEP-02)",
        "core/bad.py:2 core 바깥 패키지 import: child_lock.app (DEP-01)",
        "core/bad.py:3 core 허용 목록 밖 import: os.path (DEP-02)",
    ]


def test_core_allows_collections_abc_but_not_collections(tmp_path):
    pkg = _package(tmp_path, {"core/x.py": "import collections.abc\nimport collections\n"})
    assert arch_check.check_package(pkg) == [
        "core/x.py:2 core 허용 목록 밖 import: collections (DEP-02)",
    ]


def test_core_must_not_call_forbidden_builtins(tmp_path):
    pkg = _package(tmp_path, {"core/x.py": "def f():\n    print(1)\n    open('a')\n    len([])\n"})
    assert arch_check.check_package(pkg) == [
        "core/x.py:2 core 금지 내장 함수 호출: print (DEP-02)",
        "core/x.py:3 core 금지 내장 함수 호출: open (DEP-02)",
    ]


def test_runtime_must_not_import_app_or_web(tmp_path):
    pkg = _package(tmp_path, {"runtime/r.py": "from child_lock.app.event_log import EventLog\n"})
    assert arch_check.check_package(pkg) == [
        "runtime/r.py:1 runtime 금지 import: child_lock.app.event_log (DEP-03)",
    ]


def test_app_must_not_import_web(tmp_path):
    pkg = _package(tmp_path, {"app/a.py": "import child_lock.web.server\n"})
    assert arch_check.check_package(pkg) == [
        "app/a.py:1 app 금지 import: child_lock.web.server (DEP-04)",
    ]


def test_web_may_import_only_app_and_core_model(tmp_path):
    pkg = _package(
        tmp_path,
        {
            "web/w.py": "from child_lock.core.controller import C\n"
            "from child_lock.runtime import r\n"
        },
    )
    assert arch_check.check_package(pkg) == [
        "web/w.py:1 web 금지 import: child_lock.core.controller (DEP-05)",
        "web/w.py:2 web 금지 import: child_lock.runtime (DEP-05)",
    ]


def test_relative_imports_are_resolved_against_the_module_package(tmp_path):
    pkg = _package(
        tmp_path,
        {
            "core/a.py": "from . import model\nfrom ..app import service\n",
            "web/__init__.py": "from .server import make_server\n",
        },
    )
    assert arch_check.check_package(pkg) == [
        "core/a.py:2 core 바깥 패키지 import: child_lock.app (DEP-01)",
    ]


def test_third_party_imports_are_reported_in_any_layer(tmp_path):
    pkg = _package(tmp_path, {"app/a.py": "import requests\n", "__init__.py": "import yaml\n"})
    assert arch_check.check_package(pkg) == [
        "__init__.py:1 외부 패키지 import: yaml (DEP-07)",
        "app/a.py:1 외부 패키지 import: requests (DEP-07)",
    ]
