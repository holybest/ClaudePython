#!/usr/bin/env python3
"""Validate test case data (traceability / coverage / quality) and build the Excel workbook.

Usage:
    python build_workbook.py data.json -o out.xlsx
    python build_workbook.py data.json -o out.xlsx --template form.xlsx --header-row 1
    python build_workbook.py data.json --check-only

Exit code 0 = success, 1 = validation errors (no workbook written), 2 = usage/IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED_TC_FIELDS = ["id", "basis_ids", "objective", "inputs", "procedure", "expected", "techniques"]
KNOWN_TECHNIQUES = {
    "동치 분할", "경계값 분석", "페어와이즈(PICT)", "WoW 검증", "요구사항 분석",
    "상태 전이", "고장 주입", "결정 테이블",
}
MANDATORY_TECHNIQUES = ["동치 분할", "경계값 분석"]
# Expected outputs consisting only of these words cannot be judged pass/fail.
VAGUE_EXPECTED = re.compile(
    r"^\s*(정상\s*(동작|작동|처리)?(한다|함|해야\s*한다)?|올바르게\s*\S*|문제\s*없(음|다)|"
    r"works?\s+(correctly|properly|as\s+expected)|ok|pass)\s*\.?\s*$",
    re.IGNORECASE,
)

CATEGORY_SHEETS = {"functional": "기능 테스트", "non-functional": "비기능 테스트"}

DEFAULT_COLUMNS = [
    ("테스트 케이스 ID", "id", 14, True),
    ("테스트 베이시스 ID", "basis_ids", 16, True),
    ("구분", "suggested", 8, True),
    ("테스트 목적", "objective", 30, True),
    ("사전조건", "preconditions", 30, True),
    ("입력값", "inputs", 30, True),
    ("절차", "procedure", 40, True),
    ("예상 출력값", "expected", 35, True),
    ("합격/불합격 기준", "pass_criteria", 25, True),
    ("사용한 테스트 기법", "techniques", 18, True),
    ("시험 환경", "environment", 18, False),
    ("ASIL", "asil", 8, False),
    ("우선순위", "priority", 10, False),
    ("비고", "notes", 25, False),
]


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(",") if s.strip()]


def cell_text(tc: dict, key: str) -> str:
    value = tc.get(key)
    if key == "suggested":
        return "제안" if value else "기본"
    if key in ("basis_ids", "techniques"):
        return ", ".join(as_list(value))
    return "" if value is None else str(value)


# --------------------------------------------------------------------------- validation

def validate(data: dict):
    errors, warnings = [], []
    basis = data.get("test_basis") or []
    tcs = data.get("test_cases") or []
    if not basis:
        errors.append("test_basis가 비어 있습니다.")
    if not tcs:
        errors.append("test_cases가 비어 있습니다.")

    basis_ids = [b.get("id") for b in basis]
    for bid, n in Counter(basis_ids).items():
        if not bid:
            errors.append("id가 없는 테스트 베이시스 항목이 있습니다.")
        elif n > 1:
            errors.append(f"베이시스 ID 중복: {bid} ({n}회)")
    basis_by_id = {b.get("id"): b for b in basis}

    for b in basis:
        if b.get("category") not in CATEGORY_SHEETS:
            errors.append(f"베이시스 {b.get('id')}: category는 functional 또는 non-functional 이어야 합니다.")
        if b.get("testable", True) is False and not str(b.get("untestable_reason", "")).strip():
            errors.append(f"베이시스 {b.get('id')}: testable=false 인데 untestable_reason이 없습니다.")

    for tid, n in Counter(tc.get("id") for tc in tcs).items():
        if n > 1:
            errors.append(f"테스트 케이스 ID 중복: {tid} ({n}회)")

    signatures = defaultdict(list)
    for tc in tcs:
        tid = tc.get("id") or "<ID 없음>"
        for field in REQUIRED_TC_FIELDS:
            if not cell_text(tc, field).strip():
                errors.append(f"{tid}: 필수 항목 '{field}'이(가) 비어 있습니다.")
        if tc.get("category") not in CATEGORY_SHEETS:
            errors.append(f"{tid}: category는 functional 또는 non-functional 이어야 합니다.")
        for bid in as_list(tc.get("basis_ids")):
            if bid not in basis_by_id:
                errors.append(f"{tid}: 존재하지 않는 베이시스 ID '{bid}'를 참조합니다 (추적성 위반).")
        if VAGUE_EXPECTED.match(cell_text(tc, "expected")):
            errors.append(f"{tid}: 예상 출력값 '{tc.get('expected')}'은(는) 판정 불가능합니다. 관찰 신호·기대값·허용오차·시간을 쓰세요.")
        for t in as_list(tc.get("techniques")):
            if t not in KNOWN_TECHNIQUES:
                warnings.append(f"{tid}: 알 수 없는 기법명 '{t}' (references/techniques.md의 이름 사용 권장)")
        sig = (
            tuple(sorted(as_list(tc.get("basis_ids")))),
            re.sub(r"\s+", " ", cell_text(tc, "preconditions")).strip(),
            re.sub(r"\s+", " ", cell_text(tc, "inputs")).strip(),
            re.sub(r"\s+", " ", cell_text(tc, "expected")).strip(),
        )
        signatures[sig].append(tid)
    for ids in signatures.values():
        if len(ids) > 1:
            errors.append(f"중복 케이스(베이시스·사전조건·입력·예상 출력 동일): {', '.join(ids)}")

    # coverage: each testable basis must be covered by at least one non-suggested TC
    covering = defaultdict(list)
    for tc in tcs:
        if not tc.get("suggested"):
            for bid in as_list(tc.get("basis_ids")):
                covering[bid].append(tc.get("id"))
    for b in basis:
        if b.get("testable", True) is not False and not covering.get(b.get("id")):
            errors.append(f"베이시스 {b.get('id')}이(가) 기본(비제안) 테스트 케이스로 커버되지 않습니다 (커버리지 미달).")

    used = Counter(t for tc in tcs for t in as_list(tc.get("techniques")))
    for t in MANDATORY_TECHNIQUES:
        if not used.get(t):
            errors.append(f"필수 기법 '{t}'이(가) 한 번도 사용되지 않았습니다.")
    if not used.get("WoW 검증"):
        warnings.append("'WoW 검증'(엣지) 케이스가 없습니다. 의도한 것인지 확인하세요.")
    if not used.get("페어와이즈(PICT)") and not data.get("summary_notes"):
        warnings.append("페어와이즈 미적용: summary_notes에 미적용 사유를 쓰세요.")

    pict_tc_ids = {tid for m in data.get("pict_models") or [] for tid in as_list(m.get("test_case_ids"))}
    for tc in tcs:
        if "페어와이즈(PICT)" in as_list(tc.get("techniques")) and tc.get("id") not in pict_tc_ids:
            errors.append(f"{tc.get('id')}: 페어와이즈 케이스인데 pict_models의 test_case_ids에 없습니다 (PICT 결과 근거 누락).")
    for m in data.get("pict_models") or []:
        if not str(m.get("model", "")).strip() or not str(m.get("result_tsv", "")).strip():
            errors.append(f"PICT 모델 '{m.get('name')}': model과 result_tsv가 모두 필요합니다.")

    testable_untestable = [b for b in basis if b.get("testable", True) is False]
    finding_ids = {f.get("basis_id") for f in data.get("findings") or []}
    for b in testable_untestable:
        if b.get("id") not in finding_ids:
            warnings.append(f"베이시스 {b.get('id')}: 시험 불가 항목인데 findings에 기록이 없습니다.")

    return errors, warnings, covering, used


# --------------------------------------------------------------------------- workbook

def build(data, covering, used, out_path: Path, template: Path | None, header_row: int):
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    sugg_fill = PatternFill("solid", fgColor="FFF2CC")
    miss_fill = PatternFill("solid", fgColor="F8CBAD")
    wrap = Alignment(wrap_text=True, vertical="top")

    def write_table(ws, headers, rows, widths=None, start_row=1, fills=None):
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=start_row, column=c, value=h)
            cell.font = Font(bold=True)
            cell.fill = head_fill
            cell.border = border
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        for r, row in enumerate(rows, start_row + 1):
            for c, v in enumerate(row, 1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.border = border
                cell.alignment = wrap
                if fills and fills[r - start_row - 1] is not None:
                    cell.fill = fills[r - start_row - 1]
        for c, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(c)].width = w
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)

    tcs = data["test_cases"]
    by_cat = {cat: [tc for tc in tcs if tc.get("category") == cat] for cat in CATEGORY_SHEETS}

    if template:
        wb = load_workbook(template)
        base = wb.worksheets[0]
        cmap = data.get("column_map") or {}
        if not cmap:
            raise SystemExit("--template 사용 시 JSON에 column_map이 필요합니다 (references/data-format.md 참고).")
        headers = {str(base.cell(row=header_row, column=c).value).strip(): c
                   for c in range(1, base.max_column + 1) if base.cell(row=header_row, column=c).value}
        missing = [h for h in cmap if h not in headers]
        if missing:
            raise SystemExit(f"양식의 {header_row}행에서 헤더를 찾을 수 없습니다: {missing}")
        for cat, sheet_name in CATEGORY_SHEETS.items():
            ws = wb.copy_worksheet(base)
            ws.title = sheet_name
            for i, tc in enumerate(by_cat[cat]):
                r = header_row + 1 + i
                for header, key in cmap.items():
                    cell = ws.cell(row=r, column=headers[header], value=cell_text(tc, key))
                    cell.alignment = wrap
                    cell.border = border
                    if tc.get("suggested"):
                        cell.fill = sugg_fill
        wb.remove(base)
    else:
        wb = Workbook()
        wb.remove(wb.active)
        cols = [c for c in DEFAULT_COLUMNS if c[3] or any(cell_text(tc, c[1]).strip() for tc in tcs)]
        for cat, sheet_name in CATEGORY_SHEETS.items():
            ws = wb.create_sheet(sheet_name)
            rows = [[cell_text(tc, c[1]) for c in cols] for tc in by_cat[cat]]
            fills = [sugg_fill if tc.get("suggested") else None for tc in by_cat[cat]]
            write_table(ws, [c[0] for c in cols], rows, [c[2] for c in cols], fills=fills)

    # traceability (basis -> TCs, both basic and suggested)
    all_cov = defaultdict(list)
    sugg_cov = defaultdict(list)
    for tc in tcs:
        for bid in as_list(tc.get("basis_ids")):
            (sugg_cov if tc.get("suggested") else all_cov)[bid].append(tc["id"])
    ws = wb.create_sheet("추적성 매트릭스")
    rows, fills = [], []
    for b in data["test_basis"]:
        bid = b["id"]
        covered = bool(covering.get(bid))
        status = "커버" if covered else ("시험 불가" if b.get("testable", True) is False else "미커버")
        rows.append([bid, b.get("title", ""), "기능" if b.get("category") == "functional" else "비기능",
                     b.get("asil", ""), ", ".join(all_cov.get(bid, [])), ", ".join(sugg_cov.get(bid, [])),
                     len(all_cov.get(bid, [])) + len(sugg_cov.get(bid, [])), status,
                     b.get("untestable_reason", "")])
        fills.append(None if covered else miss_fill)
    write_table(ws, ["테스트 베이시스 ID", "요구사항 요약", "구분", "ASIL", "테스트 케이스 (기본)",
                     "테스트 케이스 (제안)", "케이스 수", "커버리지 상태", "사유"],
                rows, [16, 40, 8, 8, 30, 25, 10, 12, 30], fills=fills)

    # reverse traceability TC -> basis
    start = len(rows) + 4
    ws.cell(row=start - 1, column=1, value="역방향 추적 (테스트 케이스 → 베이시스)").font = Font(bold=True)
    rev = [[tc["id"], "제안" if tc.get("suggested") else "기본", ", ".join(as_list(tc.get("basis_ids")))] for tc in tcs]
    write_table(ws, ["테스트 케이스 ID", "구분", "테스트 베이시스 ID"], rev, start_row=start)
    ws.freeze_panes = "A2"

    # coverage summary
    basis = data["test_basis"]
    n_basis = len(basis)
    n_cov = sum(1 for b in basis if covering.get(b["id"]))
    traced = sum(1 for tc in tcs if as_list(tc.get("basis_ids")))
    ws = wb.create_sheet("커버리지 요약")
    summary = [
        ["프로젝트", data.get("project", "")],
        ["테스트 베이시스 문서", data.get("basis_document", "")],
        ["시험 환경", data.get("environment", "")],
        ["테스트 베이시스 항목 수", n_basis],
        ["커버된 베이시스 항목 수", n_cov],
        ["베이시스 커버리지", f"{(n_cov / n_basis * 100) if n_basis else 0:.1f}%"],
        ["테스트 케이스 수 (기능 / 비기능)", f"{len(by_cat['functional'])} / {len(by_cat['non-functional'])}"],
        ["제안 케이스 수", sum(1 for tc in tcs if tc.get("suggested"))],
        ["추적성 (베이시스에 연결된 케이스 비율)", f"{(traced / len(tcs) * 100) if tcs else 0:.1f}%"],
    ]
    write_table(ws, ["항목", "값"], summary, [40, 50])
    r = len(summary) + 4
    ws.cell(row=r - 1, column=1, value="기법별 케이스 수").font = Font(bold=True)
    write_table(ws, ["기법", "케이스 수"], sorted(used.items(), key=lambda x: -x[1]), start_row=r)
    notes = data.get("summary_notes") or []
    if notes:
        r = r + len(used) + 3
        ws.cell(row=r - 1, column=1, value="비고").font = Font(bold=True)
        write_table(ws, ["내용"], [[n] for n in notes], start_row=r)
    ws.freeze_panes = None

    if data.get("pict_models"):
        ws = wb.create_sheet("PICT 모델")
        rows = [[m.get("name", ""), ", ".join(as_list(m.get("basis_ids"))), m.get("options", ""),
                 m.get("model", ""), m.get("result_tsv", ""), ", ".join(as_list(m.get("test_case_ids")))]
                for m in data["pict_models"]]
        write_table(ws, ["모델명", "베이시스 ID", "PICT 옵션", "모델", "PICT 결과", "테스트 케이스 ID"],
                    rows, [20, 16, 14, 50, 60, 30])

    ws = wb.create_sheet("검토 의견")
    rows = [[f.get("basis_id", ""), f.get("type", ""), f.get("description", ""), f.get("proposal", "")]
            for f in data.get("findings") or []]
    write_table(ws, ["테스트 베이시스 ID", "유형", "내용", "제안"], rows, [16, 14, 60, 40])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return n_basis, n_cov


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--template", type=Path)
    ap.add_argument("--header-row", type=int, default=1)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    try:
        data = json.loads(args.data.read_text(encoding="utf-8-sig"))  # tolerate BOM (Windows editors)
    except (OSError, json.JSONDecodeError) as e:
        print(f"입력 파일을 읽을 수 없습니다: {e}", file=sys.stderr)
        return 2

    errors, warnings, covering, used = validate(data)
    for w in warnings:
        print(f"[경고] {w}")
    for e in errors:
        print(f"[오류] {e}")
    if errors:
        print(f"\n검증 실패: 오류 {len(errors)}건. 워크북을 만들지 않았습니다.")
        return 1
    if args.check_only:
        print("검증 통과.")
        return 0
    if not args.output:
        print("-o/--output이 필요합니다.", file=sys.stderr)
        return 2
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl이 필요합니다: pip install openpyxl", file=sys.stderr)
        return 2

    n_basis, n_cov = build(data, covering, used, args.output, args.template, args.header_row)
    tcs = data["test_cases"]
    print(f"검증 통과. 저장: {args.output}")
    print(f"베이시스 {n_basis}건 중 {n_cov}건 커버 ({n_cov / n_basis * 100:.1f}%), "
          f"테스트 케이스 {len(tcs)}건 (제안 {sum(1 for t in tcs if t.get('suggested'))}건)")
    print("기법별: " + ", ".join(f"{k} {v}" for k, v in used.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
