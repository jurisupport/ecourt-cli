"""전자소송 사건기록 업데이트 다운로드

사건 폴더(ECOURT_CASES_DIR)와 ecfs 진행중사건을 비교하여
새 서류가 있는 사건만 ecfs에서 다운로드.

사용법:
  # 1) 감지만 (다운로드 없이 비교 결과 출력)
  python ecourt_update.py --detect --data case_data.json

  # 2) 감지 + 다운로드
  python ecourt_update.py --download --data case_data.json

  # 3) ecfs 신규 사건 감지 + 전체 업데이트 다운로드 (메인 모드)
  python ecourt_update.py --sync

  # 4) 폴더 날짜 기준 전체 재다운로드
  python ecourt_update.py --download-all

환경변수(.env):
  ECOURT_CASES_DIR  사건 폴더(법원명_사건번호) 저장 위치
  ECFS_USER_ID, ECFS_CERT_PW, ECFS_CERT_NAME  (ecourt_download.py 참고)
"""

import argparse
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── 설정 ───────────────────────────────────────────────

_cases_dir = os.getenv("ECOURT_CASES_DIR")
if not _cases_dir:
    raise SystemExit(
        "환경변수 ECOURT_CASES_DIR 가 설정되지 않았습니다.\n"
        "사건 폴더(법원명_사건번호)들이 모여 있는 디렉토리 경로를 .env 에 지정하세요.\n"
        "예) ECOURT_CASES_DIR=D:/CloudSync/진행중사건"
    )
ONEDRIVE_DIR = Path(_cases_dir)
DOWNLOADS_DIR = Path.home() / "Downloads"
PROJECT_DIR = Path(__file__).parent
DETECT_OUTPUT = PROJECT_DIR / "output" / "updates"
DETECT_OUTPUT.mkdir(parents=True, exist_ok=True)


# ─── 1. 폴더 파싱 ───────────────────────────────────────

def parse_folder_files(folder_path: Path) -> dict:
    """사건 폴더 파일명 파싱 → 날짜/문서유형/시퀀스 추출"""
    files = []
    max_seq = 0
    dates_with_docs: dict[str, set[str]] = {}
    hearing_records: dict[str, int] = {}  # date_str -> 회차

    for fname in os.listdir(folder_path):
        if not fname.endswith('.pdf'):
            continue
        files.append(fname)

        parts = fname.split('_')
        if len(parts) >= 5:
            try:
                seq = int(parts[2])
                max_seq = max(max_seq, seq)
            except ValueError:
                pass

            date_str = parts[3]  # e.g., 2026.03.17
            doc_type = parts[4] if len(parts) > 4 else ''

            if date_str not in dates_with_docs:
                dates_with_docs[date_str] = set()
            dates_with_docs[date_str].add(doc_type)

        # 변론조서 회차 추출
        m = re.search(r'변론조서\s*\((\d+)회\)', fname)
        if m:
            hearing_records[fname.split('_')[3]] = int(m.group(1))

        if '판결선고조서' in fname:
            hearing_records[fname.split('_')[3]] = -1

    return {
        'files': files,
        'count': len(files),
        'max_seq': max_seq,
        'dates_with_docs': dates_with_docs,
        'hearing_records': hearing_records,
    }


# ─── 2. 날짜 파싱 ───────────────────────────────────────

def parse_date(date_str: str) -> datetime | None:
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S', '%Y.%m.%d'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


# ─── 3. 신규 서류 감지 ──────────────────────────────────

def detect_new_documents(folder_path: Path, case_data: dict) -> dict:
    """
    사건 폴더 vs 진행사항(progresses) 비교.

    case_data 예시 (외부 사건관리 시스템에서 제공):
        {
            'court': str, 'caseNumber': str, 'caseName': str,
            'filingDate': str,
            'progresses': [{'date', 'type', 'content', 'result'}, ...],
        }
    """
    folder = parse_folder_files(folder_path)
    progresses = case_data.get('progresses', [])

    # 폴더 내 최신 날짜
    folder_dates = sorted(folder['dates_with_docs'].keys())
    latest_folder_date = parse_date(folder_dates[-1]) if folder_dates else None

    # --- (A) 진행사항에서 신규 제출 서류 ---
    new_submissions = []
    for p in progresses:
        p_date = parse_date(p.get('date', ''))
        if not p_date or not latest_folder_date:
            continue
        if p_date <= latest_folder_date:
            continue

        content = p.get('content', '')
        p_type = p.get('type', '')

        # "제출" 포함 = 서류 제출
        if '제출' in content:
            new_submissions.append({
                'date': p_date.strftime('%Y.%m.%d'),
                'type': p_type,
                'content': content,
            })

    # --- (B) 변론기일 → 변론조서 추정 ---
    inferred_records = []

    # 진행사항에서 변론기일/공판기일 찾기 (실제 열린 것만)
    hearing_events = []
    for p in progresses:
        content = p.get('content', '')
        p_type = p.get('type', '')
        result = p.get('result')

        is_hearing = (
            p_type == 'hearing'
            and ('변론기일(' in content or '공판기일(' in content)
        )
        if not is_hearing:
            continue

        p_date = parse_date(p.get('date', ''))
        if not p_date:
            continue

        # 기일변경 = 실제 열리지 않음 → 스킵
        if result == '기일변경':
            continue

        hearing_events.append({
            'date': p_date,
            'content': content,
            'result': result,
        })

    # 날짜순 정렬, 중복 제거
    # 같은 기일이 UTC 시간대 차이로 2일에 걸쳐 기록될 수 있음 (예: 3/17 15:00 UTC = 3/18 00:00 KST)
    # content가 동일하면 같은 기일로 간주
    hearing_events.sort(key=lambda x: x['date'])
    unique_hearings = []
    seen_contents = set()
    for h in hearing_events:
        # content에서 날짜/시간 정보를 제외한 핵심 부분으로 중복 판단
        content_key = h['content']
        if content_key not in seen_contents:
            seen_contents.add(content_key)
            unique_hearings.append(h)

    # 항소심/현 심급 접수일 이후 기일만 (filingDate 기준)
    filing_date = parse_date(case_data.get('filingDate', ''))

    now = datetime.now()
    hearing_num = 0
    for h in unique_hearings:
        # filingDate가 있으면 그 이전 기일은 이전 심급 → 스킵
        if filing_date and h['date'] < filing_date:
            continue
        hearing_num += 1

        # 미래 기일은 아직 조서 없음
        if h['date'] > now:
            continue

        # 폴더에 해당 날짜의 조서가 있는지 확인
        date_str = h['date'].strftime('%Y.%m.%d')
        has_record = False
        if date_str in folder['dates_with_docs']:
            for dt in folder['dates_with_docs'][date_str]:
                if '조서' in dt:
                    has_record = True
                    break

        if not has_record:
            inferred_records.append({
                'hearing_number': hearing_num,
                'date': date_str,
                'content': h['content'],
                'result': h['result'],
                'reason': f"변론기일({date_str}) 종료 후 변론조서 미확인",
            })

    has_updates = len(new_submissions) > 0 or len(inferred_records) > 0

    return {
        'case_number': case_data.get('caseNumber', ''),
        'case_name': case_data.get('caseName', ''),
        'court': case_data.get('court', ''),
        'folder_path': str(folder_path),
        'folder_file_count': folder['count'],
        'folder_latest_date': folder_dates[-1] if folder_dates else None,
        'new_submissions': new_submissions,
        'inferred_records': inferred_records,
        'has_updates': has_updates,
    }


# ─── 4. 사건 폴더 매칭 ──────────────────────────────────

def find_onedrive_folder(court: str, case_number: str) -> Path | None:
    """법원명_사건번호로 사건 폴더 찾기"""
    target = f"{court}_{case_number}"
    # 본소/반소 접미사 제거한 버전
    case_no_clean = re.sub(r'\([가-힣]+\)$', '', case_number)
    for d in ONEDRIVE_DIR.iterdir():
        if d.is_dir() and d.name == target:
            return d
    # 부분 매칭 (사건번호만)
    for d in ONEDRIVE_DIR.iterdir():
        if d.is_dir() and (case_number in d.name or case_no_clean in d.name):
            return d
    return None


# ─── 5. ecfs 다운로드 (날짜 기반 선택) ────────────────────

OUT_DIR = PROJECT_DIR / "output" / "updates"
OUT_DIR.mkdir(parents=True, exist_ok=True)
_ss_step = 0


def _ss(page, name):
    global _ss_step
    _ss_step += 1
    path = OUT_DIR / f"{_ss_step:02d}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [캡쳐 {_ss_step}] {name}")
    return str(path)


def _get_popup_first_date(page) -> str | None:
    """다운로드 팝업 현재 페이지 첫 행의 날짜 반환 (페이지 변경 감지용)"""
    return page.evaluate("""() => {
        const cells = document.querySelectorAll('[id*="girokDownload"][id*="cell_0_1"]');
        for (const cell of cells) {
            if (!cell.id.includes('head')) return cell.innerText.trim();
        }
        return null;
    }""")


def select_rows_after_date(page, after_date: str) -> int:
    """다운로드 팝업에서 after_date 이후(당일 포함) 문서만 체크박스 선택.
    after_date: 'YYYY.MM.DD' 형식.
    모든 페이지를 순회하며 선택.
    Returns: 선택한 문서 수.
    """
    selected = 0
    current_page = 1
    max_pages = 20  # 안전 장치

    while current_page <= max_pages:
        # 현재 페이지의 그리드 행 순회
        prev_first_date = _get_popup_first_date(page)

        for r in range(200):
            # 날짜 셀 읽기 (컬럼 1 = 기준일자)
            date_val = page.evaluate(f"""() => {{
                const cells = document.querySelectorAll('[id*="girokDownload"][id*="cell_{r}_1"]');
                for (const cell of cells) {{
                    if (!cell.id.includes('head')) return cell.innerText.trim();
                }}
                return null;
            }}""")
            if not date_val:
                break

            # after_date 이상(당일 포함)인지 확인
            if date_val >= after_date:
                # 체크박스 클릭
                clicked = page.evaluate(f"""() => {{
                    const chks = document.querySelectorAll(
                        '[id*="girokDownload"][id*="cell_{r}_0"] input[type="checkbox"]'
                    );
                    for (const chk of chks) {{
                        if (!chk.checked) {{ chk.click(); return true; }}
                        return false;
                    }}
                    const chks2 = document.querySelectorAll(
                        '[id*="girokDownload"][id*="checkbox_{r}"]'
                    );
                    for (const chk of chks2) {{
                        if (!chk.checked) {{ chk.click(); return true; }}
                        return false;
                    }}
                    return false;
                }}""")
                if clicked:
                    doc_name = page.evaluate(f"""() => {{
                        const cells = document.querySelectorAll('[id*="girokDownload"][id*="cell_{r}_2"]');
                        for (const cell of cells) {{
                            if (!cell.id.includes('head')) return cell.innerText.trim();
                        }}
                        return '';
                    }}""")
                    print(f"    [선택] {date_val} {doc_name}")
                    selected += 1

        # 총 건수 vs 현재까지 본 행 수로 다음 페이지 존재 여부 판단
        total_count = page.evaluate("""() => {
            const all = document.body.innerText || '';
            const m = all.match(/총\\s*(\\d+)건/);
            return m ? parseInt(m[1]) : 0;
        }""") or 0

        rows_per_page = 100
        if total_count <= 0 or current_page * rows_per_page >= total_count:
            break  # 마지막 페이지이거나 총 건수 알 수 없음

        # > 버튼 클릭하여 다음 페이지 이동
        page.evaluate("""() => {
            const btns = document.querySelectorAll('[id*="girokDownload"] [id*="next"] button, [id*="girokDownload"] [id*="next"] a');
            for (const btn of btns) {
                if (btn.offsetParent !== null) { btn.click(); return; }
            }
        }""")
        time.sleep(2)

        # 페이지가 실제로 바뀌었는지 확인
        new_first_date = _get_popup_first_date(page)
        if new_first_date == prev_first_date:
            break  # 페이지 안 바뀜 → 종료

        current_page += 1
        print(f"    --- 팝업 {current_page}페이지 ---")

    return selected


def trigger_selective_download(page, after_date: str):
    """기록다운로드 팝업 → after_date 이후 문서만 선택 → 다운로드"""
    print(f"  [선택적 다운로드] {after_date} 이후 문서")

    # 모달 강제 제거 (클릭 차단 방지)
    page.evaluate("""() => {
        document.querySelectorAll('#_modal, .w2modal_popup').forEach(m => {
            m.style.setProperty('display', 'none', 'important');
            m.style.setProperty('pointer-events', 'none', 'important');
        });
    }""")
    page.click("#mf_btn_girokDownload", force=True)
    time.sleep(3)
    _ss(page, "dl_popup_open")

    # 총 건수 확인
    total_text = page.evaluate("""() => {
        const els = document.querySelectorAll('[id*="girokDownload"]');
        for (const el of els) {
            const t = el.innerText;
            const m = t.match(/총\\s*(\\d+)건/);
            if (m) return m[0];
        }
        return '';
    }""")
    print(f"    {total_text}")

    # 날짜 기반 선택
    count = select_rows_after_date(page, after_date)
    print(f"    선택 완료: {count}건")

    if count == 0:
        print("    신규 문서 없음 - 다운로드 스킵")
        # 팝업 닫기
        close_btn = page.query_selector("[id*='girokDownload'] button:has-text('닫기')")
        if close_btn:
            close_btn.click()
        return False

    _ss(page, "dl_selected")

    # dialog 자동 수락
    try:
        page.context.on("dialog", lambda d: d.accept())
    except Exception:
        pass

    # 다운로드 버튼 클릭
    page.click("#mf_girokDownload_wframe_btn_dwld")
    print("    다운로드 트리거 완료")
    time.sleep(3)
    return True


def handle_downloader_fast():
    """SgvDownloader 제어 - 소량 파일용 (대기시간 단축)"""
    try:
        from pywinauto import Application
        import pyautogui
        pyautogui.FAILSAFE = False
    except ImportError as e:
        print(f"  [다운로더] 패키지 미설치: {e}")
        return

    print("  [다운로더] 프로그램 대기...")
    app = None
    main_win = None
    for attempt in range(90):
        time.sleep(1)
        # 1) 프로세스명으로 연결 시도
        for exe in ["SgvDownloader.exe", "SgvExternalDownloader.exe"]:
            try:
                app = Application(backend="uia").connect(path=exe, timeout=1)
                break
            except Exception:
                pass
        # 2) 창 제목으로 연결 시도
        if not app:
            try:
                app = Application(backend="uia").connect(title_re=".*다운로드.*", timeout=1)
            except Exception:
                pass
            try:
                app = Application(backend="uia").connect(title_re=".*SgvDownloader.*", timeout=1)
            except Exception:
                pass
        if app:
            try:
                main_win = app.top_window()
                if main_win and main_win.is_visible():
                    title = main_win.window_text()
                    # "StartForm" 등 로딩 화면이면 실제 다운로드 창 대기
                    if '다운로드' in title or '기록' in title:
                        print(f"  [다운로더] 감지! ({attempt}초) 창: {title}")
                        break
                    else:
                        # 로딩 화면 - 계속 대기
                        if attempt % 10 == 0:
                            print(f"  [다운로더] 로딩 중... ({attempt}초) 창: {title}")
                        app = None
                else:
                    app = None
            except Exception:
                app = None

    if not app or not main_win:
        print("  [다운로더] 프로그램/창 못 찾음 (90초 초과)")
        return

    time.sleep(1)
    try:
        main_win.set_focus()
        time.sleep(1)

        # 1) '다운로드' Pane 클릭
        for ctrl in main_win.descendants():
            try:
                if ctrl.friendly_class_name() == "Pane" and ctrl.window_text() == "다운로드":
                    r = ctrl.rectangle()
                    pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                    print("  [다운로더] 다운로드 클릭")
                    break
            except Exception:
                pass

        # 2) '암호없이 계속진행' 대기 및 클릭
        time.sleep(2)
        for attempt in range(30):
            try:
                if not app.is_process_running():
                    print("  [다운로더] 완료!")
                    return
                for win in app.windows():
                    for ctrl in win.descendants():
                        try:
                            text = ctrl.window_text()
                            cls = ctrl.friendly_class_name()
                            if cls == "Pane" and "계속" in text:
                                r = ctrl.rectangle()
                                if r.width() > 5 and r.height() > 5:
                                    pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                                    print(f"  [다운로더] '{text}' 클릭")
                                    break
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(1)

        # 3) 완료 대기 (최대 90초, 파일 안정화되면 조기 종료)
        last_size = -1
        stable_count = 0
        for i in range(90):
            time.sleep(1)
            try:
                if not app.is_process_running():
                    print("  [다운로더] 완료!")
                    return
            except Exception:
                return
            # Downloads 폴더에서 최근 .crdownload/.tmp 파일이 없고 PDF 크기가 안정되면 조기 종료
            try:
                tmp_files = [f for f in DOWNLOADS_DIR.iterdir()
                             if f.suffix in ('.crdownload', '.tmp', '.part')]
                if not tmp_files:
                    # PDF 총 크기 측정 (다운로드 진행 중인지 판단)
                    pdfs = sorted([f for f in DOWNLOADS_DIR.iterdir() if f.suffix == '.pdf'],
                                  key=lambda x: x.stat().st_mtime, reverse=True)[:5]
                    cur_size = sum(f.stat().st_size for f in pdfs)
                    if cur_size == last_size:
                        stable_count += 1
                        if stable_count >= 3:  # 3초간 안정
                            print(f"  [다운로더] 파일 안정화 감지 ({i}초) - 종료")
                            return
                    else:
                        last_size = cur_size
                        stable_count = 0
            except Exception:
                pass

    except Exception as e:
        print(f"  [다운로더] 오류: {e}")
    finally:
        os.system("taskkill /F /IM SgvDownloader.exe >nul 2>&1")
        os.system("taskkill /F /IM SgvExternalDownloader.exe >nul 2>&1")


_case_list_cache = None  # 사건 목록 캐시 (세션 전체 재사용)


def download_from_ecfs(page, court: str, case_number: str, folder_path: Path,
                       after_date: str | None = None):
    """ecfs에서 해당 사건의 신규 기록만 다운로드 후 사건 폴더로 이동.

    after_date: 'YYYY.MM.DD' - 이 날짜 이후 문서만 선택 다운로드.
                None이면 폴더 최신 날짜 자동 감지.
    """
    global _case_list_cache
    from ecourt_download import (
        get_case_list, navigate_to_page, open_records_tab,
        close_records_tab, dismiss_modals,
    )

    # 모달 팝업 닫기 (세션 타임아웃/프로그램 설치 등)
    dismiss_modals(page)

    # 폴더 최신 날짜 자동 감지
    if after_date is None:
        folder_info = parse_folder_files(folder_path)
        folder_dates = sorted(folder_info['dates_with_docs'].keys())
        after_date = folder_dates[-1] if folder_dates else "2000.01.01"
    print(f"  기준일: {after_date} 이후 문서 다운로드")

    # 기존 파일 목록 기록 (다운로드 전)
    existing_files = set()
    for f in folder_path.iterdir():
        if f.is_file():
            existing_files.add(f.name)

    # 진행중사건 목록 (캐시 우선, 없거나 못 찾으면 새로 조회)
    target_idx = None
    target_page = None
    if _case_list_cache:
        for c in _case_list_cache:
            if c['case_no'] == case_number:
                target_idx = c['index']
                target_page = c.get('page', 1)
                break

    if target_idx is None:
        print(f"  사건 목록 조회 (캐시 미스)")
        _case_list_cache = get_case_list(page)
        for c in _case_list_cache:
            if c['case_no'] == case_number:
                target_idx = c['index']
                target_page = c.get('page', 1)
                break

    if target_idx is None:
        print(f"  [!] ecfs 진행중사건 목록에서 {case_number} 못 찾음")
        return False

    # 페이지 이동
    navigate_to_page(page, target_page)
    time.sleep(1)

    # 기록열람 탭 열기
    view_page = open_records_tab(page, target_idx)
    if not view_page:
        print(f"  [!] 기록열람 실패")
        return False

    _ss(view_page, "records_page")

    # 다운로더 스레드 (소량 파일용 빠른 핸들러)
    dl_thread = threading.Thread(target=handle_downloader_fast, daemon=True)
    dl_thread.start()

    # 선택적 다운로드 트리거 (실패해도 close_records_tab 보장)
    try:
        triggered = trigger_selective_download(view_page, after_date)
        if triggered:
            dl_thread.join(timeout=300)
        else:
            dl_thread.join(timeout=10)
    except Exception as e:
        print(f"  [!] 다운로드 트리거 실패: {str(e)[:80]}")
        dl_thread.join(timeout=10)
    finally:
        close_records_tab(view_page)
        time.sleep(5)

    # Downloads 폴더에서 신규 파일만 사건 폴더로 이동
    new_count = 0
    for f in DOWNLOADS_DIR.iterdir():
        if f.is_file() and case_number in f.name and f.suffix not in ('.tmp', '.crdownload'):
            if f.name not in existing_files:
                dest = folder_path / f.name
                if not dest.exists():
                    shutil.move(str(f), str(dest))
                    new_count += 1
                    print(f"    + {f.name}")
                else:
                    f.unlink()
            else:
                f.unlink()

    print(f"  신규 파일 {new_count}개 이동 완료")
    _ss(page, "done")
    return True


# ─── 6. 결과 출력 ───────────────────────────────────────

def print_detect_result(result: dict):
    court = result['court']
    case_no = result['case_number']
    case_name = result['case_name']

    print(f"\n{'='*60}")
    print(f"  {court} {case_no} {case_name}")
    print(f"{'='*60}")
    print(f"  폴더: {result['folder_path']}")
    print(f"  파일 수: {result['folder_file_count']}")
    print(f"  최신 날짜: {result['folder_latest_date']}")

    if result['new_submissions']:
        print(f"\n  [신규 제출 서류] {len(result['new_submissions'])}건")
        for s in result['new_submissions']:
            print(f"    [{s['date']}] {s['content']}")

    if result['inferred_records']:
        print(f"\n  [변론조서 추정] {len(result['inferred_records'])}건")
        for r in result['inferred_records']:
            print(f"    [{r['date']}] {r['hearing_number']}회 - {r['reason']}")

    if not result['has_updates']:
        print(f"\n  >> 업데이트 없음")
    else:
        total = len(result['new_submissions']) + len(result['inferred_records'])
        print(f"\n  >> 총 {total}건 신규/미확인 서류")


# ─── 7. 신규 사건 감지 (skip list) ────────────────────

SKIP_LIST_FILE = PROJECT_DIR / "skip_list.json"


def load_skip_list() -> dict:
    """skip_list.json 로드. {사건번호: 사유}"""
    if SKIP_LIST_FILE.exists():
        with open(SKIP_LIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_skip_list(skip_list: dict):
    with open(SKIP_LIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(skip_list, f, ensure_ascii=False, indent=2)


def detect_new_cases(ecfs_cases: list) -> dict:
    """ecfs 진행중사건 vs 사건 폴더 vs skip_list 비교.

    Returns:
        {
            'new_cases': [...],        # 신규 사건 (폴더 없고 skip 아닌 것)
            'skipped_cases': [...],    # skip_list에 있는 사건
            'existing_cases': [...],   # 폴더 있는 사건
        }
    """
    skip_list = load_skip_list()

    # 사건 폴더 목록
    onedrive_folders = set()
    for d in ONEDRIVE_DIR.iterdir():
        if d.is_dir():
            onedrive_folders.add(d.name)

    new_cases = []
    skipped_cases = []
    existing_cases = []

    for c in ecfs_cases:
        court = c.get('court', '')
        case_no = c.get('case_no', '')

        # skip_list 확인
        if case_no in skip_list:
            skipped_cases.append({**c, 'skip_reason': skip_list[case_no]})
            continue

        # 본소/반소 접미사 제거한 사건번호로도 매칭 시도
        case_no_clean = re.sub(r'\([가-힣]+\)$', '', case_no)

        # 사건 폴더 매칭
        target = f"{court}_{case_no}"
        has_folder = (target in onedrive_folders
                      or any(case_no in f for f in onedrive_folders)
                      or any(case_no_clean in f for f in onedrive_folders))

        if has_folder:
            existing_cases.append(c)
        else:
            new_cases.append(c)

    return {
        'new_cases': new_cases,
        'skipped_cases': skipped_cases,
        'existing_cases': existing_cases,
    }


def handle_new_cases(page, new_cases: list):
    """신규 사건 처리: 폴더 생성 + 전체 기록 다운로드"""
    from ecourt_download import navigate_to_page, open_records_tab, close_records_tab, dismiss_modals

    skip_list = load_skip_list()
    downloaded = 0

    for c in new_cases:
        court = c['court']
        case_no = c['case_no']
        case_name = c.get('case_name', '')
        party1 = c.get('party1', '')
        party2 = c.get('party2', '')
        print(f"\n  [신규] {court} {case_no} {case_name} ({party1} vs {party2})")

        # 사건 폴더 생성
        folder_name = f"{court}_{case_no}"
        folder_path = ONEDRIVE_DIR / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        print(f"    폴더 생성: {folder_path}")

        # ecfs에서 전체 기록 다운로드 시도
        try:
            dismiss_modals(page)
            target_page = c.get('page', 1)
            navigate_to_page(page, target_page)
            time.sleep(1)

            view_page = open_records_tab(page, c['index'])
            if not view_page:
                print(f"    [!] 기록열람 실패 - skip_list에 추가")
                skip_list[case_no] = f"기록열람 불가 ({court} {case_name})"
                save_skip_list(skip_list)
                continue

            _ss(view_page, f"new_{case_no}")

            # 다운로더 스레드
            dl_thread = threading.Thread(target=handle_downloader_fast, daemon=True)
            dl_thread.start()

            # 전체 다운로드 (날짜 제한 없이 = 2000.01.01 이후) - 실패해도 close 보장
            try:
                triggered = trigger_selective_download(view_page, "2000.01.01")
                if triggered:
                    dl_thread.join(timeout=300)
                else:
                    dl_thread.join(timeout=10)
            except Exception as e:
                print(f"    [!] 다운로드 트리거 실패: {str(e)[:80]}")
                dl_thread.join(timeout=10)
            finally:
                close_records_tab(view_page)
                time.sleep(5)

            # Downloads → 사건 폴더 이동
            new_count = 0
            for f in DOWNLOADS_DIR.iterdir():
                if f.is_file() and case_no in f.name and f.suffix not in ('.tmp', '.crdownload'):
                    dest = folder_path / f.name
                    if not dest.exists():
                        shutil.move(str(f), str(dest))
                        new_count += 1
                    else:
                        f.unlink()
            print(f"    신규 파일 {new_count}개 이동 완료")
            downloaded += 1

        except Exception as e:
            print(f"    [오류] {e}")
            skip_list[case_no] = f"다운로드 오류: {e} ({court} {case_name})"
            save_skip_list(skip_list)

    return downloaded


# ─── 메인 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="전자소송 사건기록 업데이트")
    parser.add_argument("--detect", action="store_true",
                        help="신규 서류 감지만 (다운로드 없이)")
    parser.add_argument("--download", action="store_true",
                        help="신규 서류 감지 + ecfs 다운로드")
    parser.add_argument("--download-all", action="store_true",
                        help="사건 폴더 날짜 기준 전체 다운로드 (감지 스킵)")
    parser.add_argument("--sync", action="store_true",
                        help="ecfs 신규 사건 감지 + 전체 업데이트 다운로드")
    parser.add_argument("--data", type=str,
                        help="사건 데이터 JSON 파일 경로 (외부 사건관리 시스템 export)")
    parser.add_argument("--case-id", type=str,
                        help="사건 식별자 (--data 미지정 시)")
    parser.add_argument("--scan-folders", action="store_true",
                        help="사건 폴더를 스캔하여 사건 목록 자동 생성")
    args = parser.parse_args()

    if not args.detect and not args.download and not args.download_all and not args.sync:
        parser.print_help()
        return

    # --sync 모드: 신규 사건 감지 + 전체 업데이트 다운로드
    if args.sync:
        from ecourt_download import prepare_edge_profile, login, get_case_list
        from playwright.sync_api import sync_playwright

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

                # 1) ecfs 진행중사건 목록 조회
                ecfs_cases = get_case_list(page)

                # 2) 신규 사건 감지
                result = detect_new_cases(ecfs_cases)
                new_cases = result['new_cases']
                skipped = result['skipped_cases']
                existing = result['existing_cases']

                print(f"\n{'='*60}")
                print(f"  ecfs 전체: {len(ecfs_cases)}건")
                print(f"  기존 (폴더 있음): {len(existing)}건")
                print(f"  제외 (skip_list): {len(skipped)}건")
                print(f"  신규: {len(new_cases)}건")
                print(f"{'='*60}")

                if new_cases:
                    print(f"\n[신규 사건]")
                    for c in new_cases:
                        print(f"  {c['court']} {c['case_no']} {c.get('case_name','')} "
                              f"({c.get('party1','')} vs {c.get('party2','')})")

                    # 신규 사건 폴더 생성 + 전체 기록 다운로드
                    print(f"\n신규 {len(new_cases)}건 다운로드 시작...")
                    dl_count = handle_new_cases(page, new_cases)
                    print(f"\n신규 사건 {dl_count}/{len(new_cases)}건 다운로드 완료")
                else:
                    print("\n신규 사건 없음")

                # 3) 기존 사건 업데이트 다운로드
                if existing:
                    print(f"\n{'='*60}")
                    print(f"  기존 {len(existing)}건 업데이트 확인...")
                    print(f"{'='*60}")

                    downloaded = 0
                    for i, c in enumerate(existing):
                        court = c['court']
                        case_no = c['case_no']
                        folder = find_onedrive_folder(court, case_no)
                        if not folder:
                            continue
                        print(f"\n[{i+1}/{len(existing)}] {court} {case_no}")
                        for retry in range(2):
                            try:
                                from ecourt_download import dismiss_modals as _dm
                                _dm(page)
                                result = download_from_ecfs(page, court, case_no, folder)
                                if result:
                                    downloaded += 1
                                break
                            except Exception as e:
                                if retry == 0:
                                    print(f"  [오류→재시도] {e}")
                                    from ecourt_download import dismiss_modals as _dm2
                                    _dm2(page)
                                    time.sleep(3)
                                else:
                                    print(f"  [오류] {e}")

                    print(f"\n기존 사건 {downloaded}건 업데이트 다운로드 완료")

            finally:
                context.close()

        # skip_list 현황
        skip_list = load_skip_list()
        if skip_list:
            print(f"\n[skip_list 현황] {len(skip_list)}건")
            for case_no, reason in skip_list.items():
                print(f"  {case_no}: {reason}")

        print(f"\n{'='*60}")
        print(f"  sync 완료")
        print(f"{'='*60}")
        return

    # 사건 데이터 로드
    if args.scan_folders or args.download_all:
        # 사건 폴더에서 사건 목록 자동 생성
        cases = []
        for d in sorted(ONEDRIVE_DIR.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            # 법원명_사건번호 형식 파싱
            parts = name.split('_', 1)
            if len(parts) == 2:
                court, case_number = parts
                cases.append({
                    'court': court,
                    'caseNumber': case_number,
                    'caseName': '',
                    'progresses': [],
                })
        print(f"사건 폴더 스캔: {len(cases)}건")
    elif args.data:
        with open(args.data, 'r', encoding='utf-8') as f:
            case_data = json.load(f)
        if isinstance(case_data, list):
            cases = case_data
        else:
            cases = [case_data]
    else:
        print("[!] --data 로 사건 데이터 JSON을 제공하세요.")
        print("    또는 --scan-folders / --download-all 을 사용하세요.")
        return

    # --download-all 모드: 감지 스킵, 모든 폴더 대상 다운로드
    if args.download_all:
        download_targets = []
        for case_data in cases:
            court = case_data.get('court', '')
            case_number = case_data.get('caseNumber', '')
            folder = find_onedrive_folder(court, case_number)
            if not folder:
                continue
            download_targets.append((case_data, folder))
            folder_info = parse_folder_files(folder)
            pdf_count = folder_info['count']
            folder_dates = sorted(folder_info['dates_with_docs'].keys())
            latest = folder_dates[-1] if folder_dates else "없음"
            print(f"  [{len(download_targets):2d}] {court} {case_number} ({pdf_count}개, 최신: {latest})")

        print(f"\n{'='*60}")
        print(f"  다운로드 대상: {len(download_targets)}건")
        print(f"{'='*60}")

        if download_targets:
            from ecourt_download import prepare_edge_profile, login
            from playwright.sync_api import sync_playwright

            profile_dir = prepare_edge_profile()
            downloaded = 0
            errors = []
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir, channel="msedge", headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                    slow_mo=200, accept_downloads=True, locale="ko-KR",
                )
                page = context.new_page()
                try:
                    login(page)
                    for i, (case_data, folder) in enumerate(download_targets):
                        court = case_data['court']
                        case_no = case_data['caseNumber']
                        print(f"\n[{i+1}/{len(download_targets)}] {court} {case_no}")
                        try:
                            result = download_from_ecfs(page, court, case_no, folder)
                            if result:
                                downloaded += 1
                        except Exception as e:
                            print(f"  [오류] {e}")
                            errors.append(f"{court} {case_no}: {e}")
                finally:
                    context.close()

            print(f"\n{'='*60}")
            print(f"  완료: {downloaded}/{len(download_targets)}건 다운로드")
            if errors:
                print(f"  오류: {len(errors)}건")
                for e in errors:
                    print(f"    - {e}")
            print(f"{'='*60}")
        return

    # 감지 모드 (--detect / --download)
    all_results = []
    need_download = []

    for case_data in cases:
        court = case_data.get('court', '')
        case_number = case_data.get('caseNumber', '')

        # 사건 폴더 찾기
        folder = find_onedrive_folder(court, case_number)
        if not folder:
            print(f"[!] 사건 폴더 없음: {court}_{case_number}")
            continue

        # 감지
        result = detect_new_documents(folder, case_data)
        all_results.append(result)
        print_detect_result(result)

        if result['has_updates']:
            need_download.append((case_data, folder, result))

    # 결과 저장
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = DETECT_OUTPUT / f"detect_{ts}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n결과 저장: {output_file}")

    # 다운로드 모드
    if args.download and need_download:
        print(f"\n{'='*60}")
        print(f"  다운로드 대상: {len(need_download)}건")
        print(f"{'='*60}")

        from ecourt_download import prepare_edge_profile, login
        from playwright.sync_api import sync_playwright

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
                for case_data, folder, result in need_download:
                    court = case_data['court']
                    case_no = case_data['caseNumber']
                    print(f"\n[다운로드] {court} {case_no}")
                    download_from_ecfs(page, court, case_no, folder)
            finally:
                context.close()

    # 요약
    updated = sum(1 for r in all_results if r['has_updates'])
    print(f"\n{'='*60}")
    print(f"  전체: {len(all_results)}건 검사, {updated}건 업데이트 감지")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
