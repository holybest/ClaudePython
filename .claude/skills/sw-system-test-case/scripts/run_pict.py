#!/usr/bin/env python3
"""Run Microsoft PICT (https://github.com/microsoft/pict) on a model file.

Usage:
    python run_pict.py model.txt --out result.tsv [--order 2] [--seed 1] [--pict PATH] [--download]

PICT lookup order: --pict, PICT_PATH env var, PATH, ~/.cache/pict/pict(.exe).
--download fetches the official Windows release binary from GitHub into ~/.cache/pict/
(only use it after the user agreed). On Linux/macOS build from source:
    git clone https://github.com/microsoft/pict && cd pict && cmake -B build && cmake --build build
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PICT_VERSION = "v3.7.4"
PICT_WIN_URL = f"https://github.com/microsoft/pict/releases/download/{PICT_VERSION}/pict.exe"
CACHE_DIR = Path.home() / ".cache" / "pict"
EXE_NAME = "pict.exe" if os.name == "nt" else "pict"


def find_pict(explicit: str | None) -> Path | None:
    for cand in (explicit, os.environ.get("PICT_PATH")):
        if cand and Path(cand).is_file():
            return Path(cand)
    found = shutil.which("pict")
    if found:
        return Path(found)
    cached = CACHE_DIR / EXE_NAME
    return cached if cached.is_file() else None


def download() -> Path:
    if os.name != "nt":
        raise SystemExit("공식 릴리스 바이너리는 Windows용만 있습니다. 소스에서 빌드하세요 (스크립트 상단 설명 참고).")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / EXE_NAME
    print(f"PICT {PICT_VERSION} 다운로드: {PICT_WIN_URL}", file=sys.stderr)
    req = urllib.request.Request(PICT_WIN_URL, headers={"User-Agent": "pict-runner"})
    with urllib.request.urlopen(req, timeout=60) as r, open(target, "wb") as f:
        shutil.copyfileobj(r, f)
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", type=Path)
    ap.add_argument("--out", type=Path, help="결과 TSV 저장 경로")
    ap.add_argument("--json", type=Path, help="결과를 JSON 배열로도 저장")
    ap.add_argument("--order", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pict")
    ap.add_argument("--download", action="store_true", help="PICT가 없으면 GitHub 공식 릴리스에서 받기 (Windows)")
    ap.add_argument("extra", nargs="*", help="PICT에 그대로 전달할 추가 옵션 (예: /c /e:seed.txt)")
    args = ap.parse_args()

    pict = find_pict(args.pict)
    if pict is None:
        if not args.download:
            print("PICT를 찾을 수 없습니다. 사용자 동의를 받은 뒤 --download 옵션으로 다시 실행하거나 "
                  "--pict 로 경로를 지정하세요. (https://github.com/microsoft/pict)", file=sys.stderr)
            return 3
        pict = download()

    cmd = [str(pict), str(args.model), f"/o:{args.order}", f"/r:{args.seed}", *args.extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return proc.returncode or 1
    tsv = proc.stdout
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t"))

    if args.out:
        args.out.write_text(tsv, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.out and not args.json:
        sys.stdout.write(tsv)
    print(f"PICT {' '.join(cmd[2:])}: {len(rows)}개 조합 생성", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
