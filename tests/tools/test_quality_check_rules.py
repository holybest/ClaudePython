"""!
@brief tools/quality_check.py 단위 시험 (Doxygen 주석 형식 SA-09, 규칙 예외 표기 SA-10).
"""

import textwrap

from tools import quality_check


def _src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


_GOOD_MODULE = '"""!\n@brief 모듈\n"""\n'


def test_docstring_check_accepts_complete_doxygen_comments():
    source = _GOOD_MODULE + _src(
        '''
        class Box:
            """!
            @brief 상자
            """

            def __init__(self, size: int) -> None:
                """!
                @brief 생성
                @param size 크기
                """
                self.size = size

            def area(self) -> int:
                """!
                @brief 넓이
                @return 넓이 값
                """
                return self.size * self.size
        '''
    )
    assert quality_check.docstring_violations(source) == []


def test_docstring_check_reports_missing_module_docstring_and_missing_exclamation():
    source = _src(
        '''
        def f() -> None:
            """설명만 있음"""
        '''
    )
    assert quality_check.docstring_violations(source) == [
        (1, "<module>: Doxygen docstring 없음"),
        (1, "f: Doxygen docstring 없음"),
    ]


def test_docstring_check_requires_brief_tag():
    source = '"""!\n모듈 설명\n"""\n'
    assert quality_check.docstring_violations(source) == [(1, "<module>: @brief 없음")]


def test_docstring_check_requires_param_for_each_argument_except_self_and_cls():
    source = _GOOD_MODULE + _src(
        '''
        class C:
            """!
            @brief 클래스
            """

            @classmethod
            def make(cls, a: int, b: int) -> None:
                """!
                @brief 생성
                @param a 첫째
                """
        '''
    )
    assert quality_check.docstring_violations(source) == [(10, "C.make: @param b 없음")]


def test_docstring_check_requires_return_when_annotation_is_not_none():
    source = _GOOD_MODULE + _src(
        '''
        def f() -> int:
            """!
            @brief 값
            """
            return 1


        def g() -> None:
            """!
            @brief 반환 없음
            """
        '''
    )
    assert quality_check.docstring_violations(source) == [(4, "f: @return 없음")]


def test_docstring_check_does_not_require_return_for_noreturn_or_never():
    source = _GOOD_MODULE + _src(
        '''
        from typing import Never, NoReturn
        import typing


        def a() -> NoReturn:
            """!
            @brief 항상 예외
            """
            raise ValueError


        def b() -> Never:
            """!
            @brief 항상 예외
            """
            raise ValueError


        def c() -> typing.NoReturn:
            """!
            @brief 항상 예외
            """
            raise ValueError
        '''
    )
    assert quality_check.docstring_violations(source) == []


def test_docstring_check_requires_return_for_unannotated_function_returning_value():
    source = _GOOD_MODULE + _src(
        '''
        def f():
            """!
            @brief 값
            """
            return 1


        def g():
            """!
            @brief 값 없는 return
            """
            return
        '''
    )
    assert quality_check.docstring_violations(source) == [(4, "f: @return 없음")]


def test_docstring_check_ignores_return_inside_nested_function_of_unannotated_outer():
    source = _GOOD_MODULE + _src(
        '''
        def outer():
            """!
            @brief 바깥 함수는 값을 반환하지 않음
            """
            def inner() -> int:
                """!
                @brief 안쪽
                @return 1
                """
                return 1
            inner()
        '''
    )
    assert quality_check.docstring_violations(source) == []


def test_docstring_check_covers_keyword_only_and_variadic_arguments():
    source = _GOOD_MODULE + _src(
        '''
        def f(*args: int, key: int, **kwargs: int) -> None:
            """!
            @brief 가변 인자
            @param args 위치 인자
            @param key 키
            """
        '''
    )
    assert quality_check.docstring_violations(source) == [(4, "f: @param kwargs 없음")]


def test_marker_check_reports_rule_exception_comments():
    source = _src(
        """
        a = 1  # noqa: E501
        b = 2  # type: ignore[assignment]
        if a:  # pragma: no cover
            pass
        c = "# noqa 는 문자열 안이라 대상 아님"
        """
    )
    assert quality_check.marker_violations(source) == [
        (1, "# noqa"),
        (2, "# type: ignore"),
        (3, "# pragma: no cover"),
    ]


def test_marker_check_reports_pytest_skip_and_xfail_usage():
    source = _src(
        """
        import pytest

        @pytest.mark.skip(reason="x")
        def test_a(): ...

        @pytest.mark.skipif(True, reason="x")
        def test_b(): ...

        @pytest.mark.xfail
        def test_c():
            pytest.skip("x")
            pytest.xfail("x")
        """
    )
    assert quality_check.marker_violations(source) == [
        (3, "pytest.mark.skip"),
        (6, "pytest.mark.skipif"),
        (9, "pytest.mark.xfail"),
        (11, "pytest.skip"),
        (12, "pytest.xfail"),
    ]


def test_marker_check_ignores_attribute_chains_not_rooted_at_a_name():
    source = "def test_a(make):\n    make().pytest.skip\n"
    assert quality_check.marker_violations(source) == []


def test_main_reports_docstring_violations_for_source_paths(tmp_path, capsys):
    bad = tmp_path / "bad.py"
    bad.write_text("# 주석\n# 주석\nX = 1\n", encoding="utf-8")
    assert quality_check.main([str(bad)]) == 1
    assert "<module>: Doxygen docstring 없음" in capsys.readouterr().out


def test_main_markers_only_mode_skips_other_checks_and_reports_markers(tmp_path, capsys):
    test_file = tmp_path / "test_x.py"
    test_file.write_text("def test_a():\n    assert 1  # noqa\n", encoding="utf-8")
    assert quality_check.main(["--markers-only", str(test_file)]) == 1
    out = capsys.readouterr().out
    assert "# noqa" in out
    assert "주석률" not in out
    assert "docstring" not in out


def test_main_markers_only_mode_passes_clean_test_file(tmp_path):
    test_file = tmp_path / "test_x.py"
    test_file.write_text("def test_a():\n    assert 1\n", encoding="utf-8")
    assert quality_check.main(["--markers-only", str(test_file)]) == 0
