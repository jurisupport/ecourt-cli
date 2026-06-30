"""전자소송(ecfs) 사건기록 다운로드 - 전체 자동화

흐름 (사건별 반복):
  1. Playwright(Edge) - 로그인 → 진행중사건 조회
  2. 각 사건: 메뉴 → 사건기록열람 → 기록다운로드 팝업 → 전체선택 → 다운로드
  3. pywinauto+pyautogui - SgvDownloader 프로그램 제어 (다운로드 → 암호없이 계속진행)
  4. SgvDownloader 닫기 → 기록열람 탭 닫기 → 다음 사건

사용법:
  python ecourt_download.py                  # 전체 사건 다운로드
  python ecourt_download.py --case 0         # 첫 번째 사건만
  python ecourt_download.py --case 0 2 5     # 특정 사건들만

필요 패키지:
  pip install -r requirements.txt
  python -m playwright install msedge

환경변수(.env):
  ECFS_USER_ID    전자소송 사용자 ID
  ECFS_CERT_PW    공동인증서 비밀번호
  ECFS_CERT_NAME  인증서 목록에서 선택할 이름 (보통 본인 성명)
  ECOURT_CASES_DIR  (선택) 사건 폴더 저장 위치
"""

import argparse
import os
import shutil
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

# ─── 설정 ───────────────────────────────────────────────

ECOURT_URL = "https://ecfs.scourt.go.kr"
LOGIN_URL = f"{ECOURT_URL}/psp/index.on?m=PSP101M01"

USER_ID = os.getenv("ECFS_USER_ID")
CERT_PW = os.getenv("ECFS_CERT_PW")
CERT_NAME = os.getenv("ECFS_CERT_NAME")
# 인증서 저장 위치 탭 (브라우저 / 인증서찾기 / 하드디스크 / 이동식디스크 / 스마트인증)
CERT_STORAGE = os.getenv("ECFS_CERT_STORAGE", "하드디스크")
# 브라우저 탭에 인증서가 없을 때 '인증서찾기'로 자동 등록하기 위한 NPKI 파일 위치.
#  ECFS_CERT_DIR    : signCert.der + signPri.key 가 든 폴더 전체 경로 (지정 시 최우선)
#  ECFS_CERT_SERIAL : 인증서 시리얼 일부 (NPKI 폴더명에 포함된 값으로 자동 탐색)
CERT_DIR = os.getenv("ECFS_CERT_DIR", "").strip()
CERT_SERIAL = os.getenv("ECFS_CERT_SERIAL", "").strip()

if not USER_ID or not CERT_PW or not CERT_NAME:
    raise SystemExit(
        "환경변수가 설정되지 않았습니다. .env 파일에 다음 값을 입력하세요:\n"
        "  ECFS_USER_ID, ECFS_CERT_PW, ECFS_CERT_NAME\n"
        "(.env.example 파일을 복사해 .env 로 만들고 값을 채우세요.)"
    )

EDGE_USER_DATA = Path.home() / "AppData/Local/Microsoft/Edge/User Data"
PROJECT_DIR = Path(__file__).parent
TEMP_PROFILE = PROJECT_DIR / "edge_profile"
OUT = PROJECT_DIR / "output"
OUT.mkdir(parents=True, exist_ok=True)

_step = 0


def ss(page, name):
    global _step
    _step += 1
    path = OUT / f"{_step:02d}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True, timeout=10000)
    except Exception as e:
        # 스크린샷 실패 시 작은 screenshot 시도, 그것도 실패하면 무시
        try:
            page.screenshot(path=str(path), timeout=5000)
        except Exception:
            print(f"  [ss 실패] {name}: {str(e)[:80]}")


# ─── Edge 프로필 ────────────────────────────────────────

def prepare_edge_profile():
    default_dir = TEMP_PROFILE / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    for name, sub in [("Default/Preferences", "Default/Preferences"),
                      ("Local State", "Local State")]:
        src = EDGE_USER_DATA / name
        dst = TEMP_PROFILE / sub
        if src.exists():
            shutil.copy2(str(src), str(dst))
    return str(TEMP_PROFILE)


# ─── SgvDownloader 제어 (별도 스레드) ───────────────────

def handle_downloader():
    """SgvDownloader가 뜨면: 다운로드 → 암호없이 계속진행 → 완료 대기 → 닫기"""
    try:
        from pywinauto import Application
        import pyautogui
        pyautogui.FAILSAFE = False
    except ImportError as e:
        print(f"  [다운로더] 패키지 미설치: {e}")
        return

    print("  [다운로더] 프로그램 대기...")
    app = None
    for attempt in range(60):
        time.sleep(1)
        for exe in ["SgvDownloader.exe", "SgvExternalDownloader.exe"]:
            try:
                app = Application(backend="uia").connect(path=exe, timeout=1)
                break
            except Exception:
                pass
        if app:
            print(f"  [다운로더] 감지! ({attempt+1}초)")
            break

    if not app:
        print("  [다운로더] 프로그램 못 찾음 (60초 초과)")
        return

    time.sleep(8)
    try:
        main_win = app.top_window()
        main_win.set_focus()
        print(f"  [다운로더] 창: {main_win.window_text()}")
        time.sleep(3)

        # 1) '다운로드' Pane 클릭
        clicked_dl = False
        for ctrl in main_win.descendants():
            try:
                if ctrl.friendly_class_name() == "Pane" and ctrl.window_text() == "다운로드":
                    r = ctrl.rectangle()
                    pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                    print("  [다운로더] 다운로드 클릭")
                    clicked_dl = True
                    break
            except Exception:
                pass

        if not clicked_dl:
            print("  [다운로더] 다운로드 버튼 못 찾음")

        # 2) '암호없이 계속진행' 대기 및 클릭
        time.sleep(5)
        found = False
        for attempt in range(40):
            try:
                for win in app.windows():
                    for ctrl in win.descendants():
                        try:
                            text = ctrl.window_text()
                            cls = ctrl.friendly_class_name()
                            # "암호없이 계속진행" Pane 버튼만 클릭 (Edit 텍스트 제외)
                            if cls == "Pane" and "계속" in text:
                                r = ctrl.rectangle()
                                cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
                                if r.width() > 5 and r.height() > 5:
                                    pyautogui.click(cx, cy)
                                    print(f"  [다운로더] '{text}' 클릭 ({cls}, attempt={attempt})")
                                    found = True
                                    break
                        except Exception:
                            pass
                    if found:
                        break
            except Exception:
                pass
            if found:
                break
            time.sleep(1)

        # 3) 다운로드 완료 대기
        print("  [다운로더] 다운로드 진행 중...")
        for i in range(180):
            time.sleep(1)
            try:
                if not app.is_process_running():
                    print("  [다운로더] 프로그램 종료 (완료!)")
                    return
            except Exception:
                print("  [다운로더] 완료!")
                return
            if i % 15 == 14:
                print(f"  [다운로더] 진행 중... ({i+1}초)")

        # 4) 다운로드 끝났으면 닫기
        print("  [다운로더] 닫기...")
        try:
            main_win = app.top_window()
            for ctrl in main_win.descendants():
                try:
                    if ctrl.friendly_class_name() == "Pane" and ctrl.window_text() == "닫기":
                        r = ctrl.rectangle()
                        pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                        print("  [다운로더] 닫기 클릭")
                        break
                except Exception:
                    pass
        except Exception:
            pass

    except Exception as e:
        print(f"  [다운로더] 오류: {e}")
    finally:
        # SgvDownloader 프로세스 강제 종료 (메모리 누수 방지)
        os.system("taskkill /F /IM SgvDownloader.exe >nul 2>&1")
        os.system("taskkill /F /IM SgvExternalDownloader.exe >nul 2>&1")
        print("  [다운로더] 프로세스 정리 완료")


# ─── Playwright 브라우저 조작 ───────────────────────────

def dismiss_security_modal(page):
    """보안모듈 설치 확인 팝업 등 차단 모달 제거"""
    for _ in range(3):
        # 확인/취소 팝업 버튼 클릭 (아니오/취소)
        for sel in ["[id^='confirm'] button", "[id^='confirm'] input[type='button']"]:
            for btn in page.query_selector_all(sel):
                try:
                    text = (btn.inner_text().strip() or btn.get_attribute("value") or "")
                    if any(k in text for k in ["아니", "취소", "닫기"]):
                        btn.click()
                        time.sleep(1)
                except Exception:
                    pass
        # _modal 오버레이 강제 제거
        page.evaluate("""() => {
            document.querySelectorAll('#_modal, [id^="confirm"]').forEach(el => {
                el.style.display = 'none';
                el.style.pointerEvents = 'none';
                el.remove();
            });
        }""")
        time.sleep(1)


def _npki_roots():
    """NPKI 인증서가 있을 수 있는 후보 루트 (사용자/PC 마다 다름)."""
    import string
    home = Path.home()
    roots = [home / sub for sub in (
        "AppData/LocalLow/NPKI", "AppData/Roaming/NPKI",
        "AppData/Local/NPKI", "Documents/NPKI",
    )]
    # 모든 드라이브 루트의 NPKI / GPKI (USB·외장 포함)
    for letter in string.ascii_uppercase:
        roots.append(Path(f"{letter}:/NPKI"))
        roots.append(Path(f"{letter}:/GPKI"))
    roots += [Path("C:/Program Files/NPKI"), Path("C:/Program Files (x86)/NPKI")]
    return roots


def iter_cert_dirs():
    """signCert.der + signPri.key 가 든 인증서 폴더를 모두 순회."""
    for root in _npki_roots():
        try:
            if not root.exists():
                continue
        except OSError:
            continue
        # NPKI/<CA>/USER/<cert>  및  NPKI/USER/<cert> 구조 모두 지원
        user_dirs = list(root.glob("*/USER"))
        direct = root / "USER"
        if direct.exists():
            user_dirs.append(direct)
        for user_dir in user_dirs:
            try:
                for d in user_dir.iterdir():
                    if d.is_dir() and (d / "signCert.der").exists() and (d / "signPri.key").exists():
                        yield d
            except OSError:
                pass


def find_cert_files():
    """브라우저 등록용 NPKI 인증서 파일(signCert.der + signPri.key) 탐색.

    우선순위: ECFS_CERT_DIR > ECFS_CERT_SERIAL 매칭 > ECFS_CERT_NAME 매칭.
    반환: (der_path, key_path) 또는 None.
    """
    if CERT_DIR:
        d = Path(CERT_DIR)
        der, key = d / "signCert.der", d / "signPri.key"
        if der.exists() and key.exists():
            return der, key
        print(f"  [경고] ECFS_CERT_DIR 에 인증서 파일 없음: {d}")

    name_matches = []
    for d in iter_cert_dirs():
        if CERT_SERIAL and CERT_SERIAL in d.name:
            return d / "signCert.der", d / "signPri.key"
        if CERT_NAME and CERT_NAME in d.name:
            name_matches.append((d / "signCert.der", d / "signPri.key"))
    return name_matches[0] if name_matches else None


def import_cert_via_finder(page):
    """'인증서찾기' 모달에 der+key 파일을 주입하고 '브라우저에 저장' 체크.

    성공 시 '인증서 암호' 모달이 열린 상태(비밀번호 입력 대기)가 된다.
    """
    files = find_cert_files()
    if not files:
        return False
    der, key = files
    print(f"  인증서 목록에 없음 → 인증서찾기로 브라우저 등록 시도\n    {der.parent.name}")

    # '인증서찾기' 탭 클릭
    clicked = False
    for el in page.query_selector_all("div, span, button, a, li"):
        try:
            if el.inner_text().strip() == "인증서찾기" and el.is_visible():
                el.click()
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        print("  [경고] 인증서찾기 버튼 없음")
        return False
    time.sleep(2)

    # 숨은 파일 input 에 der + key 주입
    try:
        page.set_input_files("#xwup_openFile", [str(der), str(key)])
    except Exception as e:
        print(f"  [경고] set_input_files 실패: {e}")
        return False
    time.sleep(3)

    # '인증서를 현재 브라우저에 저장합니다' 체크박스 체크
    page.evaluate("""() => {
        for (const cb of document.querySelectorAll("input[type=checkbox]")) {
            const lbl = (cb.parentElement && cb.parentElement.innerText) || '';
            if (lbl.includes('브라우저에 저장')) { if (!cb.checked) cb.click(); return; }
        }
    }""")
    time.sleep(1)
    ss(page, "cert_imported")
    return True


def login(page):
    print("\n[로그인]")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)
    dismiss_security_modal(page)

    cert_tab = page.query_selector("#mf_pfwork_tabctrl_tab_tabs1_tabHTML")
    if cert_tab:
        cert_tab.click()
        time.sleep(1)

    idfield = page.wait_for_selector("#mf_pfwork_ibx_elpUserIdForCert", timeout=5000)
    idfield.click()
    idfield.fill('')
    page.keyboard.type(USER_ID, delay=50)  # type with input events
    time.sleep(2)

    # 로그인 버튼이 disabled로 남아있는 경우 강제 활성화
    page.evaluate("""() => {
        const btn = document.querySelector('#mf_pfwork_btn_certlogin');
        if (btn) {
            btn.disabled = false;
            btn.removeAttribute('disabled');
            btn.classList.remove('w2trigger_disabled');
        }
    }""")
    time.sleep(0.5)
    btn = page.query_selector("#mf_pfwork_btn_certlogin")
    btn.click(force=True, timeout=10000)
    time.sleep(5)

    ss(page, "cert_select")

    # 공동인증서 탭 클릭 (금융인증서 탭이 기본 선택될 수 있음)
    for el in page.query_selector_all("div, span, button, a, li"):
        try:
            if el.inner_text().strip() == "공동인증서" and el.is_visible():
                el.click()
                print("  공동인증서 탭 선택")
                time.sleep(1)
                break
        except Exception:
            pass

    # 저장 위치 선택 + 인증서 목록 로드 대기 (최대 40초 폴링)
    cert_clicked = False
    for attempt in range(8):
        # 저장 위치 탭 클릭 (ECFS_CERT_STORAGE, 기본 '하드디스크')
        for el in page.query_selector_all("div, span, button, a, li"):
            try:
                text = el.inner_text().strip()
                if text == CERT_STORAGE and el.is_visible():
                    el.click()
                    if attempt == 0:
                        print(f"  저장 위치 선택: {CERT_STORAGE}")
                    time.sleep(3)
                    break
            except Exception:
                pass

        # 인증서 셀 찾기 (ECFS_CERT_NAME 포함 셀)
        for cell in page.query_selector_all("div.xwup-tableview-cell"):
            try:
                if CERT_NAME in cell.inner_text():
                    cell.click()
                    print(f"  인증서 선택 ({attempt*3+3}초)")
                    cert_clicked = True
                    break
            except Exception:
                pass
        if cert_clicked:
            break
        # 인증서 목록 아직 안 뜸 - 재시도
        print(f"  인증서 목록 로드 대기... ({attempt+1}/8)")
        time.sleep(2)

    if not cert_clicked:
        # 폴백: 인증서찾기로 NPKI 파일을 브라우저에 등록 (self-healing)
        if not import_cert_via_finder(page):
            ss(page, "cert_not_found")
            raise RuntimeError(
                f"인증서 목록을 찾을 수 없음 ('{CERT_STORAGE}'에 '{CERT_NAME}' 인증서 없음)"
            )

    time.sleep(2)
    ss(page, "cert_selected")

    # 화면에 보이는 '인증서 암호' 입력란 선택 (숨겨진 ID 로그인용 password 필드 제외)
    def _visible_pw():
        for cand in page.query_selector_all("input[type='password']"):
            try:
                if cand.is_visible():
                    return cand
            except Exception:
                pass
        return None

    pw = _visible_pw()
    if pw is None:
        print("  인증서 암호 입력란 not visible, 대기...")
        time.sleep(5)
        pw = _visible_pw()
    if pw:
        pw.click()
        pw.fill(CERT_PW)
    else:
        ss(page, "pw_not_found")
        raise RuntimeError("인증서 암호 입력란을 찾을 수 없음")
    time.sleep(1)

    # 화면에 보이는 '확인' 버튼 클릭 (모달/메인 다이얼로그 공통)
    for b in page.query_selector_all("button:has-text('확인'), input[value='확인']"):
        try:
            if b.is_visible():
                b.click()
                break
        except Exception:
            pass

    time.sleep(8)
    ss(page, "login")
    print("  완료")


def get_cell_text(page, row, col):
    """그리드 셀 텍스트 추출"""
    cell = page.query_selector(f"#mf_pfwork_grd_csAll_cell_{row}_{col}")
    return cell.inner_text().strip() if cell else ""


def get_page_cases(page):
    """현재 페이지의 사건 목록 추출"""
    cases = []
    for i in range(100):
        cell = page.query_selector(f"#mf_pfwork_grd_csAll_cell_{i}_2")
        if not cell:
            break
        case = {
            "index": i,
            "court": get_cell_text(page, i, 1),      # 법원
            "case_no": get_cell_text(page, i, 2),     # 사건번호
            "case_name": get_cell_text(page, i, 3),   # 사건명
            "role": get_cell_text(page, i, 5),        # 대리인유형
            "date": get_cell_text(page, i, 6),        # 접수일자
            "party1": get_cell_text(page, i, 7),      # 당사자1
            "party2": get_cell_text(page, i, 8),      # 당사자2
        }
        cases.append(case)
    return cases


def navigate_to_page(page, pg_num):
    """페이지 번호 버튼 클릭 (w2pageList 컴포넌트)
    페이지 그룹: 1-10, 11-20, 21-30
    next_btn/prev_btn: 그룹 단위 이동 (10페이지씩)
    page_N 버튼: 그룹 내 개별 페이지 이동
    """
    # 1) 직접 페이지 버튼이 보이면 클릭
    btn = page.query_selector(f"#mf_pfwork_pgl_inProgCs_page_{pg_num}")
    if btn and btn.is_visible():
        btn.click()
        time.sleep(3)
        return True

    # 2) 페이지 그룹 이동 필요 - 현재 보이는 페이지 그룹 확인
    visible = page.evaluate("""() => {
        const els = document.querySelectorAll("[id*='pgl_inProgCs_page_']");
        const nums = [];
        for (const el of els) {
            if (el.offsetParent !== null) nums.push(parseInt(el.textContent.trim()));
        }
        return nums;
    }""")
    if not visible:
        return False

    current_group_start = min(visible)
    target_group_start = ((pg_num - 1) // 10) * 10 + 1

    # 앞으로 이동
    while current_group_start < target_group_start:
        next_btn = page.query_selector("#mf_pfwork_pgl_inProgCs_next_btn button")
        if not next_btn:
            next_btn = page.query_selector("#mf_pfwork_pgl_inProgCs_next_btn")
        if next_btn and next_btn.is_visible():
            next_btn.click()
            time.sleep(2)
            current_group_start += 10
        else:
            return False

    # 뒤로 이동
    while current_group_start > target_group_start:
        prev_btn = page.query_selector("#mf_pfwork_pgl_inProgCs_prev_btn button")
        if not prev_btn:
            prev_btn = page.query_selector("#mf_pfwork_pgl_inProgCs_prev_btn")
        if prev_btn and prev_btn.is_visible():
            prev_btn.click()
            time.sleep(2)
            current_group_start -= 10
        else:
            return False

    # 3) 이제 목표 페이지 버튼 클릭
    btn = page.query_selector(f"#mf_pfwork_pgl_inProgCs_page_{pg_num}")
    if btn and btn.is_visible():
        btn.click()
        time.sleep(3)
        return True
    return False


def get_total_count(page):
    """총 건수 추출"""
    import re
    el = page.query_selector("#mf_pfwork_lbl_total")
    if el:
        text = el.inner_text().strip()
        m = re.search(r'(\d+)', text)
        if m:
            return int(m.group(1))
    return 0


def get_case_list(page):
    print("\n[진행중사건 조회]")
    menu = page.query_selector("#mf_pfheader_depth1_menu5")
    if menu:
        menu.hover()
        time.sleep(1)
    page.click("#mf_pfheader_anc_menuid_150201")
    time.sleep(5)
    page.click("#mf_pfwork_btn_search")
    time.sleep(5)
    ss(page, "case_list")

    # 총 건수 확인
    total = get_total_count(page)
    print(f"  총 건수: {total}건")
    total_pages = (total + 9) // 10  # 10건/페이지

    all_cases = []

    # 첫 페이지
    page_cases = get_page_cases(page)
    for c in page_cases:
        c["page"] = 1
    all_cases.extend(page_cases)

    # 나머지 페이지들
    for pg in range(2, total_pages + 1):
        if navigate_to_page(page, pg):
            page_cases = get_page_cases(page)
            if not page_cases:
                break
            for c in page_cases:
                c["page"] = pg
            all_cases.extend(page_cases)
            print(f"  페이지 {pg}/{total_pages} - {len(page_cases)}건 추가")
        else:
            # 현재 페이지 그룹에 없으면 nextPage로 이동
            next_pg_btn = page.query_selector("#mf_pfwork_pgl_inProgCs_nextPage_btn button")
            if next_pg_btn and next_pg_btn.is_visible():
                next_pg_btn.click()
                time.sleep(2)
                # 다시 해당 페이지 클릭 시도
                if navigate_to_page(page, pg):
                    page_cases = get_page_cases(page)
                    if not page_cases:
                        break
                    for c in page_cases:
                        c["page"] = pg
                    all_cases.extend(page_cases)
                    print(f"  페이지 {pg}/{total_pages} - {len(page_cases)}건 추가")
                else:
                    print(f"  페이지 {pg} 이동 실패")
                    break
            else:
                print(f"  페이지 {pg} 버튼 없음 - 종료")
                break

    # 1페이지로 복귀
    navigate_to_page(page, 1)

    for i, c in enumerate(all_cases):
        name = c['case_name'] or ""
        print(f"  [{i}] {c['court']} | {c['case_no']} | {c['party1']} vs {c['party2']}")
    print(f"  총 {len(all_cases)}건 (서버 표시: {total}건)")
    return all_cases


def dismiss_modals(page):
    """모달 팝업이 있으면 닫기 (로그아웃 팝업, 프로그램 설치, 프로그레스바 포함)"""
    try:
        # 프로그레스바 모달 대기 (___processbar2 등)
        for _ in range(30):
            processbar = page.evaluate("""() => {
                const pb = document.querySelector('[id*="processbar"]');
                return pb && pb.offsetParent !== null;
            }""")
            if processbar:
                time.sleep(1)
            else:
                break

        # _modal 오버레이 강제 제거 (모든 _modal/w2modal_popup 처리)
        page.evaluate("""() => {
            // #_modal 및 w2modal_popup 클래스 모두 처리
            document.querySelectorAll('#_modal, .w2modal_popup').forEach(m => {
                m.style.setProperty('display', 'none', 'important');
                m.style.setProperty('pointer-events', 'none', 'important');
                m.style.setProperty('visibility', 'hidden', 'important');
            });
        }""")

        # 세션 시간연장 팝업: "연장" 버튼 클릭 (취소하면 세션 만료)
        extend_btn = page.evaluate("""() => {
            // PSPLOGP02 팝업 내 '연장' 버튼 찾기
            const popup = document.querySelector('[id*="PSPLOGP02"]');
            if (!popup || popup.offsetParent === null) return null;
            for (const btn of popup.querySelectorAll('button, input[type=button]')) {
                const txt = (btn.value || btn.innerText || '').trim();
                if (txt === '연장' || txt === '시간연장' || txt.includes('연장')) {
                    btn.click();
                    return txt;
                }
            }
            return null;
        }""")
        if extend_btn:
            print(f"  [모달] 세션 연장 버튼 클릭: {extend_btn}")
            time.sleep(2)

        modal = page.query_selector("#_modal")
        if modal and modal.is_visible():
            page.keyboard.press("Escape")
            time.sleep(1)

        # 프로그램 설치 팝업만 닫기 (사건메뉴 PSP221P02는 닫지 않음)
        page.evaluate("""() => {
            for (const win of document.querySelectorAll('.w2window, .w2popup_window')) {
                const title = win.querySelector('[class*="header_title"]');
                if (title && title.textContent.includes('프로그램 설치')) {
                    const closeBtn = win.querySelector('[id*="_close"], button');
                    if (closeBtn) closeBtn.click();
                    else win.style.display = 'none';
                    return true;
                }
            }
            return false;
        }""")
        time.sleep(1)
    except Exception:
        pass


def open_records_tab(page, row_index):
    """사건 메뉴 → 사건기록열람 (새 탭으로 열림)"""
    print(f"\n[사건기록열람] 행 {row_index}")

    # 먼저 모달이 떠 있으면 닫기
    dismiss_modals(page)

    menu_cell = page.query_selector(f"#mf_pfwork_grd_csAll_cell_{row_index}_11")
    btn = menu_cell.query_selector("button") if menu_cell else None
    if btn:
        for retry in range(3):
            try:
                dismiss_modals(page)
                btn.click(timeout=10000)
                break
            except Exception as e:
                print(f"  메뉴 버튼 클릭 재시도 {retry+1}/3: {e}")
                dismiss_modals(page)
                time.sleep(2)
                if retry == 2:
                    return None
    time.sleep(2)

    # 사건기록열람 버튼 찾기 (메뉴 팝업 내) - dismiss_modals는 호출하지 않음 (팝업이 닫힘)
    record_btn = None
    for attempt in range(5):
        record_btn = page.query_selector("#mf_pfwork_PSP221P02_wframe_btn_browseCsRcrd")
        if record_btn:
            break
        # 대체 셀렉터: input[value='사건기록열람'] 또는 button
        record_btn = page.query_selector("input[value='사건기록열람'], button:has-text('사건기록열람')")
        if record_btn:
            break
        time.sleep(2)
        record_btn = None

    if record_btn:
        # Playwright click (force=True로 visibility 체크 우회) - JS click은 window.open을 못 트리거함
        try:
            record_btn.click(timeout=15000, force=True)
        except Exception as e:
            print(f"  사건기록열람 클릭 실패: {e}")
            try:
                record_btn.click(timeout=15000)
            except Exception:
                # 마지막 시도: dispatchEvent로 mouse click
                try:
                    page.evaluate("""(el) => {
                        const ev = new MouseEvent('click', {bubbles: true, cancelable: true, view: window});
                        el.dispatchEvent(ev);
                    }""", record_btn)
                except Exception:
                    page.keyboard.press("Escape")
                    return None
    else:
        print("  사건기록열람 버튼 없음")
        ss(page, f"no_record_btn_{row_index}")
        # 팝업 닫기
        close_btn = page.query_selector("#mf_pfwork_PSP221P02_close")
        if close_btn:
            close_btn.click()
        page.keyboard.press("Escape")
        time.sleep(1)
        return None

    time.sleep(5)

    # 사건기록열람은 sgvo URL의 새 탭에서 열림 (최대 15초 대기)
    view_page = None
    for _ in range(15):
        for p in page.context.pages:
            if 'sgvo' in p.url:
                view_page = p
                break
        if view_page:
            break
        time.sleep(1)

    if view_page:
        time.sleep(3)
        ss(view_page, f"records_{row_index}")
        return view_page

    # 폴백: 메인 페이지(PSP221M01)가 아닌 새 탭만 사용 (메인 닫으면 브라우저 종료됨)
    for p in page.context.pages:
        if p is page:
            continue
        if 'PSP221M01' in p.url or 'index.on' in p.url:
            continue
        if p.url in ('about:blank', ''):
            continue
        time.sleep(3)
        ss(p, f"records_{row_index}")
        return p
    # 적절한 기록열람 탭 없음 - 사건메뉴 팝업 닫고 실패 처리
    print("  사건기록열람 탭 안 열림 (기록열람 불가 사건)")
    try:
        page.evaluate("""() => {
            const closeBtn = document.querySelector('#mf_pfwork_PSP221P02_close, [id*="PSP221P02_close"]');
            if (closeBtn && closeBtn.offsetParent !== null) closeBtn.click();
            document.querySelectorAll('#_modal, .w2modal_popup').forEach(m => {
                m.style.setProperty('display', 'none', 'important');
                m.style.setProperty('pointer-events', 'none', 'important');
            });
        }""")
    except Exception:
        pass
    return None


def select_all_on_current_page(page):
    """현재 페이지의 모든 체크박스 선택"""
    chks = page.query_selector_all("input[type='checkbox']")
    header_clicked = False
    # 1차: 헤더 전용 체크박스
    for chk in chks:
        chk_id = chk.get_attribute("id") or ""
        if "girokDownload" in chk_id and ("header" in chk_id or "chkAll" in chk_id) and chk.is_visible():
            chk.click()
            print(f"    전체선택(헤더): {chk_id}")
            header_clicked = True
            break
    # 2차: th 안의 체크박스
    if not header_clicked:
        th_chk = page.query_selector("th input[type='checkbox']")
        if th_chk and th_chk.is_visible():
            th_chk.click()
            print("    전체선택(th)")
            header_clicked = True
    # 3차: 개별 전체 클릭
    if not header_clicked:
        count = 0
        for chk in chks:
            chk_id = chk.get_attribute("id") or ""
            if "girokDownload" in chk_id and "checkbox" in chk_id and chk.is_visible():
                if not chk.is_checked():
                    chk.click()
                    time.sleep(0.2)
                count += 1
        print(f"    개별선택: {count}개")


def trigger_download(page):
    """기록다운로드 팝업 → 전체선택(모든 페이지) → 다운로드 버튼"""
    print("  [기록다운로드 트리거]")

    page.click("#mf_btn_girokDownload")
    time.sleep(3)

    # 1페이지 전체선택
    select_all_on_current_page(page)

    # 기록다운로드 팝업 내 페이지네이션 확인 (문서 100개 이상 시 2페이지 존재)
    for pg in range(2, 11):
        pg_btn = page.query_selector(f"[id*='girokDownload'] [id*='page_{pg}']")
        if not pg_btn:
            # 대체 셀렉터 시도
            pg_btn = page.query_selector(f"[id*='girokDownload'] a:has-text('{pg}')")
        if pg_btn and pg_btn.is_visible():
            print(f"    기록 {pg}페이지 이동")
            pg_btn.click()
            time.sleep(2)
            select_all_on_current_page(page)
        else:
            break

    time.sleep(1)
    ss(page, "selected")

    # dialog 자동 수락 - context 레벨에서 처리하여 TargetClosedError 방지
    def _safe_accept(d):
        try:
            d.accept()
        except Exception:
            pass
    page.context.on("dialog", _safe_accept)

    # 다운로드 버튼 클릭
    page.click("#mf_girokDownload_wframe_btn_dwld")
    print("    다운로드 트리거 완료")
    time.sleep(3)


def close_records_tab(view_page):
    """기록열람 탭 닫기 + 메인 페이지의 사건 메뉴 팝업도 닫기"""
    try:
        # 메인 페이지 참조 가져오기 (view_page를 닫기 전)
        main_page = None
        try:
            for p in view_page.context.pages:
                if 'PSP221M01' in p.url:
                    main_page = p
                    break
        except Exception:
            pass

        # 안전장치: view_page가 메인 페이지면 절대 닫지 않음 (브라우저 종료 방지)
        try:
            vp_url = view_page.url
        except Exception:
            vp_url = ''
        if 'PSP221M01' in vp_url or 'index.on' in vp_url:
            print("  [경고] view_page가 메인 페이지 - 닫기 스킵, 메뉴 팝업만 정리")
            if main_page:
                try:
                    main_page.evaluate("""() => {
                        const closeBtn = document.querySelector('#mf_pfwork_PSP221P02_close, [id*="PSP221P02_close"]');
                        if (closeBtn && closeBtn.offsetParent !== null) closeBtn.click();
                        document.querySelectorAll('[id*="PSP221P02"]').forEach(el => {
                            if (el.id === 'mf_pfwork_PSP221P02' || el.id.endsWith('_PSP221P02')) el.style.display = 'none';
                        });
                        document.querySelectorAll('#_modal, .w2modal_popup').forEach(m => {
                            m.style.setProperty('display', 'none', 'important');
                            m.style.setProperty('pointer-events', 'none', 'important');
                        });
                    }""")
                except Exception:
                    pass
            return

        view_page.close()
        print("  기록열람 탭 닫기")

        # 메인 페이지의 사건 메뉴 팝업(PSP221P02) 닫기
        if main_page:
            try:
                main_page.evaluate("""() => {
                    // 닫기 버튼 클릭
                    const closeBtn = document.querySelector('#mf_pfwork_PSP221P02_close, [id*="PSP221P02_close"]');
                    if (closeBtn && closeBtn.offsetParent !== null) closeBtn.click();
                    // 팝업 자체 숨기기 (백업)
                    document.querySelectorAll('[id*="PSP221P02"]').forEach(el => {
                        if (el.id === 'mf_pfwork_PSP221P02' || el.id.endsWith('_PSP221P02')) {
                            el.style.display = 'none';
                        }
                    });
                    // 모달 오버레이 강제 제거
                    document.querySelectorAll('#_modal, .w2modal_popup').forEach(m => {
                        m.style.setProperty('display', 'none', 'important');
                        m.style.setProperty('pointer-events', 'none', 'important');
                    });
                }""")
            except Exception:
                pass
    except Exception:
        pass


def sanitize_name(name):
    """파일/폴더명에 사용할 수 없는 문자 제거"""
    import re
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name.strip().rstrip('.')


def make_folder_name(case_info):
    """사건 정보로 폴더명 생성: {법원}_{사건번호}_{사건명}_{당사자}_{당사자}"""
    parts = [
        case_info.get("court", ""),
        case_info.get("case_no", ""),
        case_info.get("case_name", ""),
        case_info.get("party1", ""),
        case_info.get("party2", ""),
    ]
    parts = [sanitize_name(p) for p in parts if p]
    return "_".join(parts)


def find_case_files(downloads_dir, case_no):
    """Downloads 폴더에서 사건번호가 포함된 파일들 찾기"""
    dl = Path(downloads_dir)
    if not dl.exists():
        return []
    # 사건번호로 파일 매칭 (예: *_2026카단6047_*)
    matched = []
    for f in dl.iterdir():
        if f.is_file() and case_no in f.name and f.suffix not in ('.tmp', '.crdownload'):
            matched.append(f)
    return matched


DOWNLOADS_DIR = Path.home() / "Downloads"
CASE_OUTPUT_DIR = Path(os.getenv("ECOURT_CASES_DIR", str(PROJECT_DIR / "cases")))


def download_case(page, row_index, case_no, case_info=None):
    """한 사건의 기록 다운로드 전체 흐름"""
    print(f"\n{'='*50}")
    print(f"사건 다운로드: [{row_index}] {case_no}")
    print(f"{'='*50}")

    try:
        # 이미 다운로드된 폴더가 있으면 건너뛰기
        if case_info:
            folder_name = make_folder_name(case_info)
            dest_dir = CASE_OUTPUT_DIR / folder_name
            if dest_dir.exists() and any(dest_dir.iterdir()):
                print(f"  [{case_no}] 이미 다운로드됨 - 건너뜀")
                return True

        # 1) 사건기록열람 탭 열기
        view_page = open_records_tab(page, row_index)
        if not view_page:
            print(f"  [{case_no}] 기록열람 실패 - 건너뜀")
            return False

        # 2) 다운로더 스레드 시작
        dl_thread = threading.Thread(target=handle_downloader, daemon=True)
        dl_thread.start()

        # 3) 다운로드 트리거
        trigger_download(view_page)

        # 4) 다운로더 완료 대기
        dl_thread.join(timeout=300)

        # 5) 기록열람 탭 닫기
        close_records_tab(view_page)
        time.sleep(2)

        # 6) 다운로드 파일 안정화 대기
        time.sleep(5)

        # 7) 사건번호로 매칭하여 파일 이동
        if case_info:
            dest_dir = CASE_OUTPUT_DIR / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)

            case_files = find_case_files(DOWNLOADS_DIR, case_no)
            if case_files:
                moved = 0
                for f in case_files:
                    dest = dest_dir / f.name
                    if not dest.exists():
                        shutil.move(str(f), str(dest))
                        moved += 1
                print(f"  파일 이동: {moved}개 → {folder_name}/")
            else:
                print(f"  경고: 사건번호 '{case_no}' 매칭 파일 없음")

        print(f"  [{case_no}] 완료!")
        return True

    except Exception as e:
        print(f"  [{case_no}] 오류 발생: {e}")
        # 열린 탭 정리
        for p in page.context.pages[1:]:
            try:
                p.close()
            except Exception:
                pass
        dismiss_modals(page)
        return False


# ─── 메인 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="전자소송 사건기록 다운로드")
    parser.add_argument("--case", type=int, nargs="*",
                        help="다운로드할 사건 인덱스 (미지정시 전체)")
    parser.add_argument("--start", type=int, default=0,
                        help="시작 인덱스 (이전 실행에서 이어서)")
    parser.add_argument("--list", action="store_true",
                        help="사건 목록만 조회 (다운로드 안 함)")
    parser.add_argument("--cached-list", action="store_true",
                        help="저장된 case_list.json 사용 (페이지 순회 생략)")
    args = parser.parse_args()

    print("=" * 60)
    print("  전자소송 사건기록 다운로드 자동화")
    print("=" * 60)

    CASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = prepare_edge_profile()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel="msedge",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            slow_mo=200,
            accept_downloads=True,
            locale="ko-KR",
        )
        page = context.new_page()

        try:
            login(page)

            if args.cached_list:
                import json
                list_file = PROJECT_DIR / "case_list.json"
                cases = json.loads(list_file.read_text(encoding="utf-8"))
                print(f"\n[캐시된 목록 사용] {len(cases)}건")
                # 진행중사건 페이지로만 이동 (페이지 순회 없이)
                menu = page.query_selector("#mf_pfheader_depth1_menu5")
                if menu:
                    menu.hover()
                    time.sleep(1)
                page.click("#mf_pfheader_anc_menuid_150201")
                time.sleep(5)
                page.click("#mf_pfwork_btn_search")
                time.sleep(5)
            else:
                cases = get_case_list(page)

            if not cases:
                print("사건 없음")
                return

            # --list 모드: 목록만 출력하고 종료
            if args.list:
                import json
                list_file = PROJECT_DIR / "case_list.json"
                with open(list_file, "w", encoding="utf-8") as f:
                    json.dump(cases, f, ensure_ascii=False, indent=2)
                print(f"\n사건 목록 저장: {list_file}")
                return

            # 다운로드할 사건 결정
            if args.case is not None:
                indices = [i for i in args.case if i < len(cases)]
            else:
                indices = list(range(args.start, len(cases)))

            print(f"\n다운로드 대상: {len(indices)}건")
            print(f"저장 경로: {CASE_OUTPUT_DIR}")

            success = 0
            last_page = None
            for idx in indices:
                case = cases[idx]
                target_page = case.get("page", 1)
                # 매번 페이지 명시적으로 이동 (탭 닫기 후 상태 복구)
                navigate_to_page(page, target_page)
                time.sleep(1)
                last_page = target_page
                ok = download_case(page, case["index"], case["case_no"], case_info=case)
                if ok:
                    success += 1

            print(f"\n{'='*60}")
            print(f"  완료: {success}/{len(indices)}건 다운로드")
            print(f"  저장 경로: {CASE_OUTPUT_DIR}")
            print(f"{'='*60}")

        finally:
            context.close()


if __name__ == "__main__":
    main()
