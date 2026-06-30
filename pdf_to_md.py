"""PDF → MD 변환: 사건기록 PDF에서 텍스트 추출하여 MD 파일 생성
1 PDF = 1 MD, 파일명에서 메타데이터 파싱

환경변수(.env):
  ECOURT_CASES_DIR   변환할 PDF가 들어있는 사건 폴더 루트 (기본값)
  ECOURT_MD_OUTPUT   MD 출력 디렉토리 (선택, 기본 ./md_output)
"""
import os
import sys
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).parent

# 소스 디렉토리: ECOURT_CASES_DIR 하위를 그대로 변환 (단일 루트)
_cases_dir = os.getenv("ECOURT_CASES_DIR", str(PROJECT_DIR / "cases"))
SOURCES = {
    "사건기록": Path(_cases_dir),
}

OUTPUT_DIR = Path(os.getenv("ECOURT_MD_OUTPUT", str(PROJECT_DIR / "md_output")))


def parse_filename(filename):
    """파일명에서 메타데이터 파싱
    예: 서울중앙지방법원_2024가단100000_001001_2024.01.15_소장_(소장)_원고 대리인_홍길동.pdf
    """
    stem = Path(filename).stem
    parts = stem.split("_")

    meta = {
        "court": "",
        "case_no": "",
        "doc_index": "",
        "date": "",
        "doc_type": "",
        "detail": "",
    }

    if len(parts) >= 1:
        meta["court"] = parts[0]
    if len(parts) >= 2:
        meta["case_no"] = parts[1]
    if len(parts) >= 3:
        meta["doc_index"] = parts[2]
    if len(parts) >= 4:
        meta["date"] = parts[3]
    if len(parts) >= 5:
        meta["doc_type"] = parts[4]
    if len(parts) >= 6:
        meta["detail"] = "_".join(parts[5:])

    return meta


def extract_text(pdf_path):
    """PDF에서 텍스트 추출 (PyMuPDF)"""
    try:
        doc = fitz.open(str(pdf_path))
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"## 페이지 {i+1}\n\n{text}")
        doc.close()
        return "\n\n".join(pages)
    except Exception as e:
        return f"[텍스트 추출 실패: {e}]"


def pdf_to_md(pdf_path, case_type, output_dir):
    """1 PDF → 1 MD 변환"""
    meta = parse_filename(pdf_path.name)
    text = extract_text(pdf_path)

    if not text or text.startswith("[텍스트 추출 실패"):
        return False

    # MD frontmatter
    md_content = f"""---
court: {meta['court']}
case_no: {meta['case_no']}
case_type: {case_type}
doc_type: {meta['doc_type']}
doc_date: {meta['date']}
doc_index: {meta['doc_index']}
detail: {meta['detail']}
filename: {pdf_path.name}
---

# {meta['court']} {meta['case_no']} - {meta['doc_type']}

{text}
"""

    # 출력 경로: md_output/사건기록/법원_사건번호/001_소장.md
    case_folder = pdf_path.parent.name
    out_dir = output_dir / case_type / case_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    md_name = f"{meta['doc_index']}_{meta['doc_type']}.md"
    md_path = out_dir / md_name

    if md_path.exists():
        return True  # 이미 변환됨

    md_path.write_text(md_content, encoding="utf-8")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PDF → MD 변환")
    parser.add_argument("--limit", type=int, default=0, help="변환할 최대 PDF 수 (0=전체)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    success = 0
    skipped = 0

    for case_type, src_dir in SOURCES.items():
        if not src_dir.exists():
            print(f"{case_type}: 디렉토리 없음 ({src_dir})")
            continue

        pdfs = list(src_dir.rglob("*.pdf"))
        print(f"\n[{case_type}] {len(pdfs)}개 PDF")

        for i, pdf in enumerate(pdfs):
            if args.limit and total >= args.limit:
                break

            total += 1

            # 이미 변환된 파일 스킵
            meta = parse_filename(pdf.name)
            case_folder = pdf.parent.name
            out_dir = OUTPUT_DIR / case_type / case_folder
            md_name = f"{meta['doc_index']}_{meta['doc_type']}.md"
            if (out_dir / md_name).exists():
                skipped += 1
                continue

            ok = pdf_to_md(pdf, case_type, OUTPUT_DIR)
            if ok:
                success += 1

            if total % 500 == 0:
                print(f"  진행: {total}개 처리 ({success} 성공, {skipped} 스킵)")

    print(f"\n완료: {total}개 처리, {success}개 변환, {skipped}개 스킵")


if __name__ == "__main__":
    main()
