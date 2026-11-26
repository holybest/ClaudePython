"""!
@brief tools/quality_check.py 단위 시험 (주석률, 함수 순수 코드 줄 수).
"""

import runpy
import sys
import textwrap

import pytest

from tools import quality_check


def _src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def test_comment_ratio_counts_comment_and_docstring_lines_over_nonblank_lines():
    # 비공백 8줄 중 주석 1줄 + docstring 3줄 = 4줄 → 50.0%
    source = _src(
        '''
        """!
        @brief 모듈 설명
        """
        # 상수 정의
        LIMIT = 3

        def f(x):
            y = x + 1
            return y
        '''
    )
    assert quality_check.comment_ratio(source) == 50.0


def test_comment_ratio_counts_function_and_class_docstrings():
    # 비공백 6줄 중 클래스 docstring 1줄 + 함수 docstring 1줄 = 2줄
    source = _src(
        '''
        class A:
            """클래스 설명"""
            def f(self):
                """함수 설명"""
                x = 1
                return x
        '''
    )
    assert quality_check.comment_ratio(source) == 2 * 100.0 / 6


def test_comment_ratio_ignores_trailing_comment_and_hash_inside_string():
    # 코드 뒤 주석과 문자열 속 '#'은 주석 줄이 아니다 → 0%
    source = _src(
        """
        x = 1  # 코드 뒤 주석
        y = "# 문자열"
        """
    )
    assert quality_check.comment_ratio(source) == 0.0


def test_comment_ratio_does_not_treat_non_string_first_statement_as_docstring():
    # 함수 첫 문장 `...`은 docstring이 아니다 → 주석 0줄 / 비공백 2줄
    source = "def f():\n    ...\n"
    assert quality_check.comment_ratio(source) == 0.0


def test_comment_ratio_of_empty_source_is_zero():
    assert quality_check.comment_ratio("") == 0.0


def test_function_pure_lines_exclude_signature_decorator_docstring_comment_and_blank():
    # 순수 코드: a = 1 / b = (2 + / 3) / return a + b → 4줄
    source = _src(
        '''
        @staticmethod
        def f(
            x,
        ):
            """!
            @brief 설명
            """
            # 주석
            a = 1

            b = (2 +
                 3)
            return a + b
        '''
    )
    assert quality_check.function_lengths(source) == [("f", 2, 4)]


def test_function_pure_lines_reports_methods_and_nested_functions_by_qualified_name():
    # outer 본문(def inner 포함) 3줄, inner 1줄, 메서드 1줄
    source = _src(
        """
        class C:
            def m(self):
                return 1

        def outer():
            def inner():
                return 2
            return inner()
        """
    )
    assert quality_check.function_lengths(source) == [
        ("C.m", 2, 1),
        ("outer", 5, 3),
        ("outer.inner", 6, 1),
    ]


_GOOD = '"""모듈 설명"""\n# 주석\nX = 1\n'  # 비공백 3줄 중 주석 2줄 → 66.7%


def _long_function(pure_lines: int) -> str:
    body = "".join(f"    v{i} = {i}\n" for i in range(pure_lines - 1))
    return '"""!\n@brief 긴 함수\n"""\n# 주석\n\ndef big():\n' + body + "    return 0\n"


def test_main_returns_zero_for_compliant_files_in_directory_tree(tmp_path, capsys):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(_GOOD, encoding="utf-8")
    assert quality_check.main([str(tmp_path)]) == 0
    assert "위반 0건" in capsys.readouterr().out


def test_main_reports_comment_ratio_below_20_percent(tmp_path, capsys):
    # 비공백 5줄 중 주석 1줄 → 20% 미만이 아니므로 통과, 6줄 중 1줄 → 16.7% 위반
    ok = tmp_path / "ok.py"
    ok.write_text("# c\nA = 1\nB = 2\nC = 3\nD = 4\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text("# c\nA = 1\nB = 2\nC = 3\nD = 4\nE = 5\n", encoding="utf-8")
    assert quality_check.main([str(ok)]) == 0
    assert quality_check.main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert "bad.py" in out
    assert "주석률 16.7%" in out


def test_main_reports_function_over_50_pure_lines(tmp_path, capsys):
    ok = tmp_path / "ok.py"
    ok.write_text(_long_function(50), encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text(_long_function(51), encoding="utf-8")
    assert quality_check.main([str(ok), "--min-comment", "0"]) == 0
    assert quality_check.main([str(bad), "--min-comment", "0"]) == 1
    assert "big: 순수 코드 51줄" in capsys.readouterr().out


def test_module_execution_exits_with_main_result(tmp_path, monkeypatch):
    bad = tmp_path / "bad.py"
    bad.write_text("A = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["quality_check", str(bad)])
    monkeypatch.delitem(sys.modules, "tools.quality_check")
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("tools.quality_check", run_name="__main__")
    assert exc.value.code == 1
