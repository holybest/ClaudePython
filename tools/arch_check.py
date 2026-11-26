"""!
@brief SWAD 의존 규칙 검사 도구 (SA-05).

계층별 import 규칙(DEP-01~05, DEP-07)과 안전 코어의 금지 내장 함수 호출(DEP-02)을 AST로 검사한다.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

## 검사 대상 최상위 패키지 이름
PACKAGE = "child_lock"

## 안전 코어가 import할 수 있는 표준 라이브러리 (DEP-02 허용 목록)
CORE_STDLIB = frozenset(
    {"__future__", "abc", "collections.abc", "dataclasses", "enum", "functools", "math", "typing"}
)

## 안전 코어에서 호출을 금지하는 내장 함수 (DEP-02)
FORBIDDEN_BUILTINS = frozenset({"open", "print", "input", "eval", "exec", "compile", "__import__"})


@dataclass(frozen=True)
class ImportRef:
    """!
    @brief import 문 하나의 검사 정보.
    """

    ## import 문 줄 번호
    line: int
    ## 위반 메시지에 표시할 모듈 이름
    shown: str
    ## 규칙 판정에 쓸 실제 대상 이름 목록
    targets: tuple[str, ...]


def _module_name(rel: Path) -> tuple[str, bool]:
    """!
    @brief 패키지 기준 상대 경로를 모듈 이름으로 바꾼다.
    @param rel 패키지 폴더 기준 .py 파일 경로
    @return (모듈 이름, 패키지 __init__ 여부)
    """
    parts = [PACKAGE, *rel.with_suffix("").parts]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _resolve_from(node: ast.ImportFrom, module: str, is_package: bool) -> str:
    """!
    @brief from-import의 모듈 이름을 절대 이름으로 바꾼다.
    @param node ImportFrom 노드
    @param module 현재 모듈 이름
    @param is_package 현재 모듈이 패키지 __init__인지 여부
    @return 절대 모듈 이름
    """
    if node.level == 0:
        return node.module or ""
    base = module.split(".") if is_package else module.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _imports(tree: ast.Module, module: str, is_package: bool) -> list[ImportRef]:
    """!
    @brief 모듈의 모든 import를 검사 정보로 모은다.
    @param tree 모듈 AST
    @param module 현재 모듈 이름
    @param is_package 현재 모듈이 패키지 __init__인지 여부
    @return import 검사 정보 목록
    """
    refs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs += [ImportRef(node.lineno, a.name, (a.name,)) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            name = _resolve_from(node, module, is_package)
            inner = name.split(".")[0] == PACKAGE
            targets = tuple(f"{name}.{a.name}" for a in node.names) if inner else (name,)
            refs.append(ImportRef(node.lineno, name, targets))
    return sorted(refs, key=lambda r: r.line)


def _layer(name: str) -> str | None:
    """!
    @brief 패키지 내부 이름의 계층(core, runtime, app, web)을 구한다.
    @param name 패키지 내부 모듈 이름
    @return 계층 이름, 최상위 패키지면 None
    """
    parts = name.split(".")
    return parts[1] if len(parts) > 1 else None


def _web_allowed(target: str) -> bool:
    """!
    @brief Web 계층이 import할 수 있는 대상인지 판단한다(DEP-05).
    @param target 대상 이름
    @return 허용이면 True
    """
    model = f"{PACKAGE}.core.model"
    return _layer(target) in ("app", "web") or target == model or target.startswith(model + ".")


def _internal_issue(ref: ImportRef, layer: str | None) -> str | None:
    """!
    @brief 패키지 내부 import의 계층 규칙 위반을 판정한다.
    @param ref import 검사 정보
    @param layer import하는 모듈의 계층
    @return 위반 메시지, 없으면 None
    """
    layers = {_layer(t) for t in ref.targets}
    if layer == "core" and layers != {"core"}:
        outer = sorted(x or "" for x in layers - {"core"})[0]
        return f"core 바깥 패키지 import: {'.'.join(filter(None, [PACKAGE, outer]))} (DEP-01)"
    if layer == "runtime" and not layers <= {"core", "runtime"}:
        return f"runtime 금지 import: {ref.shown} (DEP-03)"
    if layer == "app" and "web" in layers:
        return f"app 금지 import: {ref.shown} (DEP-04)"
    if layer == "web" and not all(_web_allowed(t) for t in ref.targets):
        return f"web 금지 import: {ref.shown} (DEP-05)"
    return None


def _import_issue(ref: ImportRef, layer: str | None) -> str | None:
    """!
    @brief import 하나의 규칙 위반을 판정한다.
    @param ref import 검사 정보
    @param layer import하는 모듈의 계층
    @return 위반 메시지, 없으면 None
    """
    top = ref.shown.split(".")[0]
    if top == PACKAGE:
        return _internal_issue(ref, layer)
    if top not in sys.stdlib_module_names:
        return f"외부 패키지 import: {ref.shown} (DEP-07)"
    if layer == "core" and ref.shown not in CORE_STDLIB:
        return f"core 허용 목록 밖 import: {ref.shown} (DEP-02)"
    return None


def _forbidden_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """!
    @brief 금지 내장 함수 호출을 찾는다.
    @param tree 모듈 AST
    @return (줄 번호, 함수 이름) 목록
    """
    return [
        (node.lineno, node.func.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in FORBIDDEN_BUILTINS
    ]


def _file_violations(pkg: Path, path: Path) -> list[tuple[str, int, str]]:
    """!
    @brief 파일 하나의 의존 규칙 위반을 찾는다.
    @param pkg 패키지 폴더
    @param path 검사할 파일
    @return (상대 경로, 줄 번호, 메시지) 목록
    """
    rel = path.relative_to(pkg)
    module, is_package = _module_name(rel)
    layer = _layer(module)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    shown = rel.as_posix()
    found = []
    for ref in _imports(tree, module, is_package):
        issue = _import_issue(ref, layer)
        if issue:
            found.append((shown, ref.line, issue))
    if layer == "core":
        found += [
            (shown, n, f"core 금지 내장 함수 호출: {f} (DEP-02)") for n, f in _forbidden_calls(tree)
        ]
    return found


def check_package(pkg: Path) -> list[str]:
    """!
    @brief 패키지 전체의 의존 규칙 위반을 찾는다.
    @param pkg 패키지 폴더(예: src/child_lock)
    @return "상대경로:줄 메시지" 목록, 경로·줄 순서
    """
    found = []
    for path in pkg.rglob("*.py"):
        found += _file_violations(pkg, path)
    return [f"{p}:{line} {msg}" for p, line, msg in sorted(found)]
