"""!
@brief 소스코드 품질 기준(주석률, 함수 순수 코드 줄 수) 검사 도구.
"""

import argparse
import ast
import io
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
    return found


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
    args = parser.parse_args(argv)
    found = []
    for path in _python_files(args.paths):
        found.extend(_violations(path, args.min_comment, args.max_lines))
    for message in found:
        print(message)
    print(f"품질 검사: 위반 {len(found)}건")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
