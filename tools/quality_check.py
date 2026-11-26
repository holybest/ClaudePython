"""!
@brief 소스코드 품질 기준(주석률, 함수 순수 코드 줄 수) 검사 도구.
"""

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

## 코드로 보지 않는 토큰 종류
_NON_CODE_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}


def _docstring_lines(tree: ast.AST) -> set[int]:
    """!
    @brief 모듈·클래스·함수 docstring이 차지하는 줄 번호를 모은다.
    @param tree 파싱된 모듈 AST
    @return docstring 줄 번호 집합
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        # docstring = 본문 첫 문장이 문자열 상수 표현식인 경우
        value = first.value if isinstance(first, ast.Expr) else None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


def _token_lines(source: str) -> tuple[set[int], set[int]]:
    """!
    @brief 코드 토큰이 있는 줄과 주석 토큰이 있는 줄을 구한다.
    @param source 파이썬 소스 문자열
    @return (코드 줄 번호 집합, 주석 줄 번호 집합)
    """
    code: set[int] = set()
    comments: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            comments.add(tok.start[0])
        elif tok.type not in _NON_CODE_TOKENS:
            code.update(range(tok.start[0], tok.end[0] + 1))
    return code, comments


def _functions(node: ast.AST, prefix: str = ""):
    """!
    @brief 함수·메서드 노드를 정규화된 이름(Class.method, outer.inner)과 함께 순회한다.
    @param node 탐색을 시작할 AST 노드
    @param prefix 상위 이름 접두사
    @return (정규화된 이름, 함수 노드) 생성기
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            name = prefix + child.name
            if not isinstance(child, ast.ClassDef):
                yield name, child
            yield from _functions(child, name + ".")
        else:
            yield from _functions(child, prefix)


def function_lengths(source: str) -> list[tuple[str, int, int]]:
    """!
    @brief 함수별 순수 코드 줄 수(빈 줄, 주석, docstring, 시그니처 제외)를 구한다.
    @param source 파이썬 소스 문자열
    @return (정규화된 이름, def 줄 번호, 순수 코드 줄 수) 목록
    """
    tree = ast.parse(source)
    docstrings = _docstring_lines(tree)
    code, _ = _token_lines(source)
    result = []
    for name, func in _functions(tree):
        body = set(range(func.body[0].lineno, func.end_lineno + 1))
        result.append((name, func.lineno, len((body & code) - docstrings)))
    return result


def comment_ratio(source: str) -> float:
    """!
    @brief 주석률 = (주석 줄 + docstring 줄) / 비공백 줄 × 100.
    @param source 파이썬 소스 문자열
    @return 주석률(%)
    """
    docstrings = _docstring_lines(ast.parse(source))
    code, comments = _token_lines(source)
    comment_only = comments - code
    nonblank = [n for n, line in enumerate(source.splitlines(), 1) if line.strip()]
    if not nonblank:
        return 0.0
    commented = comment_only | docstrings
    return len(commented) * 100.0 / len(nonblank)


## 규칙 예외 주석 표기 (SA-10)
_MARKER_COMMENTS = (
    (re.compile(r"#\s*noqa\b"), "# noqa"),
    (re.compile(r"#\s*type:\s*ignore\b"), "# type: ignore"),
    (re.compile(r"pragma:\s*no\s*cover\b"), "# pragma: no cover"),
)

## 금지된 pytest 건너뛰기·실패 예상 표기 (SA-10)
_MARKER_ATTRIBUTES = frozenset(
    {"pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail", "pytest.skip", "pytest.xfail"}
)

## 함수 정의 노드 형식
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _definitions(node: ast.AST, prefix: str = ""):
    """!
    @brief 클래스·함수 정의를 정규화된 이름과 함께 순회한다.
    @param node 탐색을 시작할 AST 노드
    @param prefix 상위 이름 접두사
    @return (정규화된 이름, 정의 노드) 생성기
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            name = prefix + child.name
            yield name, child
            yield from _definitions(child, name + ".")
        else:
            yield from _definitions(child, prefix)


def _raw_docstring(node: ast.AST) -> str | None:
    """!
    @brief 정의 노드의 docstring 원문(들여쓰기 정리 전)을 구한다.
    @param node 모듈·클래스·함수 노드
    @return docstring 문자열, 없으면 None
    """
    body = getattr(node, "body", [])
    first = body[0] if body else None
    value = first.value if isinstance(first, ast.Expr) else None
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _argument_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """!
    @brief @param이 필요한 인자 이름 목록(self, cls 제외)을 구한다.
    @param func 함수 노드
    @return 인자 이름 목록
    """
    a = func.args
    names = [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
    names += [x.arg for x in (a.vararg, a.kwarg) if x is not None]
    return [n for n in names if n not in ("self", "cls")]


def _returns_value(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """!
    @brief 함수가 값을 반환하는지 판단한다(반환 주석 우선, 없으면 return 문 검사).
    @param func 함수 노드
    @return 값을 반환하면 True
    """
    if func.returns is not None:
        return not (isinstance(func.returns, ast.Constant) and func.returns.value is None)
    pending = list(func.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Return) and node.value is not None:
            return True
        if not isinstance(node, (*_FUNCTION_NODES, ast.ClassDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(node))
    return False


def _function_tag_issues(func: ast.FunctionDef | ast.AsyncFunctionDef, doc: str) -> list[str]:
    """!
    @brief 함수 docstring의 @param, @return 누락을 찾는다.
    @param func 함수 노드
    @param doc docstring 원문
    @return 누락 메시지 목록
    """
    issues = [
        f"@param {name} 없음"
        for name in _argument_names(func)
        if not re.search(rf"@param\s+{re.escape(name)}\b", doc)
    ]
    if _returns_value(func) and "@return" not in doc:
        issues.append("@return 없음")
    return issues


def _doxygen_issues(node: ast.AST) -> list[str]:
    """!
    @brief 정의 노드 하나의 Doxygen 형식 위반을 찾는다.
    @param node 모듈·클래스·함수 노드
    @return 위반 메시지 목록
    """
    doc = _raw_docstring(node)
    if doc is None or not doc.startswith("!"):
        return ["Doxygen docstring 없음"]
    issues = [] if "@brief" in doc else ["@brief 없음"]
    if isinstance(node, _FUNCTION_NODES):
        issues += _function_tag_issues(node, doc)
    return issues


def docstring_violations(source: str) -> list[tuple[int, str]]:
    """!
    @brief 모듈·클래스·함수의 Doxygen 주석 형식 위반을 찾는다(SA-09).
    @param source 파이썬 소스 문자열
    @return (줄 번호, 메시지) 목록
    """
    tree = ast.parse(source)
    found = [(1, f"<module>: {issue}") for issue in _doxygen_issues(tree)]
    for name, node in _definitions(tree):
        found += [(node.lineno, f"{name}: {issue}") for issue in _doxygen_issues(node)]
    return found


def _dotted_name(node: ast.AST) -> str | None:
    """!
    @brief 속성 접근 체인(a.b.c)을 점으로 이은 이름으로 바꾼다.
    @param node AST 노드
    @return 점 이름, 이름·속성 체인이 아니면 None
    """
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def marker_violations(source: str) -> list[tuple[int, str]]:
    """!
    @brief 규칙 예외 주석과 pytest 건너뛰기·실패 예상 표기를 찾는다(SA-10).
    @param source 파이썬 소스 문자열
    @return (줄 번호, 표기) 목록, 줄 번호 순
    """
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            found += [
                (tok.start[0], label) for rx, label in _MARKER_COMMENTS if rx.search(tok.string)
            ]
    for node in ast.walk(ast.parse(source)):
        name = _dotted_name(node) if isinstance(node, ast.Attribute) else None
        if name in _MARKER_ATTRIBUTES:
            found.append((node.lineno, name))
    return sorted(found)


def _python_files(paths: list[str]) -> list[Path]:
    """!
    @brief 경로 목록에서 검사할 .py 파일을 모은다(폴더는 하위까지).
    @param paths 파일 또는 폴더 경로 목록
    @return 정렬된 .py 파일 경로 목록
    """
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])
    return files


def _violations(path: Path, min_comment: float, max_lines: int) -> list[str]:
    """!
    @brief 파일 하나의 품질 기준 위반 메시지를 만든다.
    @param path 검사할 파일
    @param min_comment 최소 주석률(%)
    @param max_lines 함수 최대 순수 코드 줄 수
    @return 위반 메시지 목록
    """
    source = path.read_text(encoding="utf-8")
    found = []
    ratio = comment_ratio(source)
    if ratio < min_comment:
        found.append(f"{path}: 주석률 {ratio:.1f}% (기준 {min_comment:g}% 이상)")
    for name, lineno, lines in function_lengths(source):
        if lines > max_lines:
            found.append(f"{path}:{lineno} {name}: 순수 코드 {lines}줄 (기준 {max_lines}줄 이하)")
    found += [f"{path}:{line} {msg}" for line, msg in docstring_violations(source)]
    return found + _marker_messages(path, source)


def _marker_messages(path: Path, source: str) -> list[str]:
    """!
    @brief 규칙 예외 표기 위반 메시지를 만든다.
    @param path 검사한 파일
    @param source 파일 내용
    @return 위반 메시지 목록
    """
    return [f"{path}:{line} 규칙 예외 표기 {label}" for line, label in marker_violations(source)]


def main(argv: list[str] | None = None) -> int:
    """!
    @brief 명령줄 진입점. 위반이 있으면 목록을 출력하고 1을 반환한다.
    @param argv 명령줄 인자(None이면 sys.argv 사용)
    @return 종료 코드(0: 통과, 1: 위반 있음)
    """
    parser = argparse.ArgumentParser(description="주석률·함수 길이 품질 기준 검사")
    parser.add_argument("paths", nargs="+", help="검사할 파일 또는 폴더")
    parser.add_argument("--min-comment", type=float, default=20.0, help="최소 주석률(%%)")
    parser.add_argument("--max-lines", type=int, default=50, help="함수 최대 순수 코드 줄 수")
    parser.add_argument(
        "--markers-only", action="store_true", help="규칙 예외 표기만 검사(시험 코드용)"
    )
    args = parser.parse_args(argv)
    found = []
    for path in _python_files(args.paths):
        if args.markers_only:
            found += _marker_messages(path, path.read_text(encoding="utf-8"))
        else:
            found += _violations(path, args.min_comment, args.max_lines)
    for message in found:
        print(message)
    print(f"품질 검사: 위반 {len(found)}건")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
