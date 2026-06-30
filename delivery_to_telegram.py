"""전체송달문서 → PDF 다운로드 → 텔레그램 전송 + 사건 폴더 저장.

⚠️ 주의: 송달문서를 '확인'하면 송달 효력이 발생할 수 있습니다.
   미확인 문서를 자동으로 여는 동작의 법적 효과를 반드시 검토하세요.

⚠️ 상태: 실험적(experimental). 송달문서 행 링크 클릭이 일부 환경에서
   SgvDownloader를 트리거하지 못할 수 있습니다.

- 송달문서 목록 조회 (최근 1개월)
- 각 문서 PDF 다운로드 (SgvDownloader)
- 준비서면은 서증 제외, 본문만
- 텔레그램으로 PDF 전송
- 사건 폴더에 저장

사용법:
  python delivery_to_telegram.py            # 전체
  python delivery_to_telegram.py --new-only # 미확인만

환경변수(.env):
  ECOURT_CASES_DIR, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import os
import re
import sys
import time
import json
import shutil
import threading
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv

from ecourt_download import prepare_edge_profile, login, DOWNLOADS_DIR
from ecourt_update import handle_downloader_fast
from playwright.sync_api import sync_playwright

load_dotenv()

PROJECT_DIR = Path(__file__).parent
_cases_dir = os.getenv("ECOURT_CASES_DIR")
if not _cases_dir:
    raise SystemExit("환경변수 ECOURT_CASES_DIR 가 설정되지 않았습니다 (.env 참고).")
ONEDRIVE_DIR = Path(_cases_dir)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OUT = PROJECT_DIR / "output" / "delivery"
OUT.mkdir(parents=True, exist_ok=True)

_step = 0


def ss(page, name):
    global _step
    _step += 1
    try:
        page.screenshot(path=str(OUT / f"{_step:02d}_{name}.png"), full_page=True, timeout=10000)
    except Exception:
        pass


# ─── 텔레그램 ────────────────────────────────────────
def load_bot_token():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN 가 없습니다 (.env 참고).")
    return token


def tg_text(token, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text}).encode('utf-8')
    try:
        with urllib.request.urlopen(url, data=data, timeout=30) as r:
            return r.status == 200
    except Exception as e:
        print(f"[텔레그램 텍스트 실패] {e}")
        return False


def tg_document(token, file_path, caption=""):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    boundary = "----TGB" + os.urandom(8).hex()
    body = []
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{CHAT_ID}\r\n".encode('utf-8'))
    if caption:
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode('utf-8'))
    fname = file_path.name
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{fname}\"\r\nContent-Type: application/pdf\r\n\r\n".encode('utf-8'))
    body.append(file_path.read_bytes())
    body.append(f"\r\n--{boundary}--\r\n".encode('utf-8'))
    data = b"".join(body)
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status == 200
    except Exception as e:
        print(f"[텔레그램 파일 실패] {fname}: {e}")
        return False


# ─── 송달문서 목록 ────────────────────────────────────
def get_delivery_list(page):
    """전체송달문서 메뉴 → 1개월 조회 → 목록 반환"""
    menu = page.query_selector("#mf_pfheader_depth1_menu5")
    if menu:
        menu.hover()
        time.sleep(1)
    page.click("#mf_pfheader_anc_menuid_150503")
    time.sleep(5)

    # 1개월 버튼
    for btn in page.query_selector_all("button, a, input[type='button']"):
        try:
            text = btn.inner_text().strip() if btn.inner_text() else (btn.get_attribute("value") or "")
            if text == "1개월":
                btn.click()
                time.sleep(2)
                break
        except Exception:
            pass

    search_btn = page.query_selector("#mf_pfwork_btn_search")
    if search_btn:
        search_btn.click()
        time.sleep(5)
    ss(page, "delivery_list")

    # 행 데이터 추출 (col0~col7)
    rows = []
    for r in range(100):
        c0 = page.evaluate(f"""() => {{
            const cells = document.querySelectorAll('[id$="dlvr_cell_{r}_0"]');
            for (const c of cells) {{ if (c.id.includes('grd') && !c.id.includes('head')) return c.innerText; }}
            return null;
        }}""")
        if not c0:
            break
        row = {}
        for c in range(8):
            v = page.evaluate(f"""() => {{
                const cells = document.querySelectorAll('[id$="dlvr_cell_{r}_{c}"]');
                for (const cell of cells) {{ if (cell.id.includes('grd') && !cell.id.includes('head')) return cell.innerText; }}
                return '';
            }}""")
            row[f"col{c}"] = (v or "").strip()
        row['row'] = r
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-only", action="store_true", help="미확인 송달문서만")
    args = parser.parse_args()

    token = load_bot_token()
    profile_dir = prepare_edge_profile()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, channel="msedge", headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            slow_mo=200, accept_downloads=True, locale="ko-KR",
        )
        page = context.new_page()
        try:
            login(page)
            rows = get_delivery_list(page)
            print(f"송달문서 {len(rows)}건")

            # 처리 대상 필터
            targets = []
            for row in rows:
                case_no = row['col3']
                doc_name = row['col5']
                send_date = row['col6']
                confirm = row['col7']  # '미확인' 또는 날짜
                is_new = (confirm == '미확인')
                if args.new_only and not is_new:
                    continue
                targets.append(row)

            print(f"처리 대상: {len(targets)}건")
            tg_text(token, f"[송달문서] {len(targets)}건 다운로드 시작\n준비서면은 본문만(서증 제외)")

            sent = 0
            for idx, row in enumerate(targets):
                r = row['row']
                case_no = row['col3']
                court = row['col1']
                doc_name = row['col5']
                print(f"\n[{idx+1}/{len(targets)}] {court} {case_no} - {doc_name}")

                # 다운로드 전 기존 파일
                before = set(f.name for f in DOWNLOADS_DIR.iterdir() if f.is_file())

                # 다운로더 스레드
                dl_thread = threading.Thread(target=handle_downloader_fast, daemon=True)
                dl_thread.start()

                # 문서 링크 클릭
                try:
                    page.evaluate(f"""() => {{
                        const cells = document.querySelectorAll('[id$="dlvr_cell_{r}_5"]');
                        for (const cell of cells) {{
                            if (cell.id.includes('grd') && !cell.id.includes('head')) {{
                                const a = cell.querySelector('a');
                                if (a) {{ a.click(); return; }}
                                cell.click(); return;
                            }}
                        }}
                    }}""")
                    print("  문서 링크 클릭")
                    time.sleep(3)
                    dl_thread.join(timeout=120)
                except Exception as e:
                    print(f"  [오류] {e}")
                    dl_thread.join(timeout=5)

                time.sleep(5)

                # 열린 탭 닫기 (메인 외)
                for pg in context.pages:
                    if pg is not page and 'index.on' not in pg.url:
                        try:
                            pg.close()
                        except Exception:
                            pass
                time.sleep(2)

                # 새 파일 찾기
                after = set(f.name for f in DOWNLOADS_DIR.iterdir() if f.is_file())
                new_files = [DOWNLOADS_DIR / n for n in (after - before)
                             if n.endswith('.pdf')]

                if not new_files:
                    print("  [!] 다운로드 파일 없음")
                    continue

                # 준비서면이면 서증 제외 (본문만)
                is_preparatory = '준비서면' in doc_name
                for f in new_files:
                    if is_preparatory and '서증' in f.name:
                        print(f"    [스킵-서증] {f.name[:50]}")
                        f.unlink()  # 서증 삭제
                        continue

                    # 사건 폴더로 이동
                    folder = None
                    for d in ONEDRIVE_DIR.iterdir():
                        if d.is_dir() and case_no in d.name:
                            folder = d
                            break
                    if folder:
                        dest = folder / f.name
                        if not dest.exists():
                            shutil.copy2(str(f), str(dest))

                    # 텔레그램 전송
                    caption = f"{court} {case_no}\n{doc_name}"
                    if tg_document(token, f, caption=caption):
                        print(f"    [전송] {f.name[:50]}")
                        sent += 1

            tg_text(token, f"[송달문서] 완료 - {sent}개 PDF 전송됨")
            print(f"\n완료: {sent}개 전송")

        finally:
            context.close()


if __name__ == "__main__":
    main()
