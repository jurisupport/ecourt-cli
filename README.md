# ecourt-cli

전자소송(ecfs) **진행중사건 기록 자동 다운로드/동기화** 도구.
Korea Electronic Court (ecfs.scourt.go.kr) case-record auto-downloader & sync tool.

> **쥬리서포트 주식회사(JuriSupport Inc.)** 가 제공하는 오픈소스 도구입니다.
> Provided as open source by **JuriSupport Inc. (쥬리서포트 주식회사)**.

매일 정해진 시각에 전자소송에 로그인하여, 내 진행중사건의 새 문서만 골라
로컬 사건 폴더로 내려받고(클라우드 동기화 폴더 사용 시 자동 백업) 결과를
텔레그램으로 보고합니다.

> ⚠️ **비공식(Unofficial) 도구입니다.** 대한민국 법원 전자소송 시스템과 무관하며,
> 화면 자동화(브라우저 + 데스크톱 앱 제어)에 의존하므로 사이트 구조가 바뀌면
> 동작하지 않을 수 있습니다. 사용 전 전자소송 이용약관을 확인하고 **본인 책임**
> 하에 사용하세요. (면책 조항은 하단 참고)

---

## 동작 원리 / How it works

```
┌─────────────┐   Playwright(Edge)    ┌──────────────────────┐
│ 매일 18:03  │ ───────────────────► │ ecfs 로그인 (공동인증서) │
│ 데몬 트리거 │                       └──────────┬───────────┘
└─────────────┘                                  │
                                                 ▼
                                   ┌──────────────────────────┐
                                   │ 진행중사건 목록 조회       │
                                   └──────────┬───────────────┘
                                              ▼
          사건 폴더 vs ecfs 비교 → 신규 사건/신규 문서만 선별
                                              │
                                              ▼
                          기록열람 → 기록다운로드 팝업 → 날짜 기준 선택
                                              │
                       SgvDownloader.exe (pywinauto + pyautogui로 제어)
                          "다운로드" → "암호없이 계속진행" → 저장
                                              │
                                              ▼
                  Downloads → 사건 폴더(법원명_사건번호)로 이동
                                              │
                                              ▼
                            텔레그램으로 결과 요약 + 로그 전송
```

1. **로그인** — Playwright가 Edge 영속 프로필로 전자소송에 접속, 공동인증서(하드디스크)로 로그인.
2. **목록 조회** — 진행중사건 전체 페이지를 순회하여 사건 목록 수집.
3. **비교/선별** — 로컬 사건 폴더의 파일명(날짜)과 비교해 *신규 사건*과 *기존 사건의 신규 문서*만 추림. `skip_list.json` 에 등록된 사건은 제외.
4. **다운로드** — 사건기록열람 → 기록다운로드 팝업에서 기준일 이후 문서만 체크 → 다운로드. 실제 PDF 저장은 법원이 띄우는 데스크톱 앱 `SgvDownloader.exe` 가 수행하며, 이를 pywinauto/pyautogui로 자동 클릭.
5. **정리** — 받은 PDF를 `법원명_사건번호` 폴더로 이동.
6. **알림** — 텔레그램 봇으로 요약과 로그 파일 전송.

---

## 기술 스택 / Tech stack

| 영역 | 사용 기술 |
|------|-----------|
| 브라우저 자동화 | [Playwright](https://playwright.dev/) (Edge persistent context) |
| 데스크톱 앱 제어 | [pywinauto](https://pywinauto.readthedocs.io/) (UIA backend) + [pyautogui](https://pyautogui.readthedocs.io/) |
| 로그인 | 공동인증서(NPKI) — 하드디스크 저장 인증서, 비동기 목록 폴링 |
| 알림 | Telegram Bot API (sendMessage / sendDocument) |
| 스케줄 | 시작프로그램 등록 데몬 (Windows Startup) |
| PDF 추출(선택) | [PyMuPDF](https://pymupdf.readthedocs.io/) |

---

## 사전 요구사항 / Prerequisites

- **Windows 10/11** (데스크톱 앱 제어 때문에 Windows 전용)
- **Python 3.10+** (코드에 `X | None` 타입 표기 사용 — 3.10 이상 권장, 개발 환경은 3.13)
- **Microsoft Edge** 설치
- **전자소송 계정 + 공동인증서**(하드디스크에 저장되어 있어야 함)
- **전자소송 보안 프로그램**(SgvDownloader 등) 설치 — 전자소송 최초 이용 시 자동 설치됨
- **텔레그램 봇**(알림을 쓸 경우): [@BotFather](https://t.me/BotFather)로 봇 생성 후 토큰 발급

> ⚠️ GUI 자동화 특성상 **잠긴 화면/원격 세션에서는 동작하지 않습니다.** 반드시
> 사용자가 로그인된 데스크톱 세션에서 실행해야 하며, 그래서 작업 스케줄러 대신
> 시작프로그램 데몬 방식을 사용합니다.

---

## 설치 / Setup

```bash
git clone https://github.com/jurisupport/ecourt-cli.git
cd ecourt-cli

# 가상환경 (선택)
python -m venv .venv
.venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# Playwright용 Edge 드라이버
python -m playwright install msedge

# 환경변수 파일 작성
copy .env.example .env
#  → .env 를 열어 ID/인증서 비번/경로/텔레그램 토큰 등을 채웁니다.
```

`.env` 주요 항목:

| 변수 | 설명 |
|------|------|
| `ECFS_USER_ID` | 전자소송 사용자 ID |
| `ECFS_CERT_PW` | 공동인증서 비밀번호 |
| `ECFS_CERT_NAME` | 인증서 목록에서 선택할 이름(본인 성명/법인명) |
| `ECOURT_CASES_DIR` | 사건 폴더 저장 루트 (클라우드 동기화 폴더 권장) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 알림 받을 채팅 ID |
| `SYNC_TIME` | 데몬 실행 시각 `HH:MM` (기본 `18:03`) |

> 🔐 `.env`, `edge_profile/`, `skip_list.json`, 다운로드된 `*.pdf` 등은 `.gitignore`로
> 저장소에서 제외됩니다. **인증서 비밀번호가 평문으로 들어가므로 `.env`를 절대 커밋하지 마세요.**

---

## 사용법 / Usage

### 1) 수동 1회 실행 (텔레그램 보고 포함)
```bash
python sync_scheduled.py
```

### 2) 감지/다운로드 직접 실행
```bash
# ecfs 신규 사건 감지 + 기존 사건 업데이트 다운로드 (메인 모드)
python ecourt_update.py --sync

# 사건 폴더 날짜 기준으로 전체 재점검 다운로드
python ecourt_update.py --download-all

# 외부 사건관리 데이터(JSON)와 폴더 비교만
python ecourt_update.py --detect --data case_data.json
```

### 3) 전체 기록 일괄 다운로드 (최초 1회)
```bash
python ecourt_download.py            # 진행중사건 전체
python ecourt_download.py --case 0   # 첫 번째 사건만
python ecourt_download.py --list     # 목록만 저장(case_list.json)
```

### 4) 매일 자동 실행 (데몬)
`daily_sync_daemon.py` 를 **시작프로그램(Startup)** 폴더에 등록하면 로그인 시
자동 실행되어 매일 `SYNC_TIME` 에 sync를 돌립니다.

```bat
:: 예: start_daemon.bat 를 만들어 Startup 폴더(shell:startup)에 둠
start "ecourt_daemon" /MIN python.exe daily_sync_daemon.py
```
즉시 1회 검증 실행:
```bash
python daily_sync_daemon.py --test
```

### 5) PDF → Markdown 변환 (선택)
```bash
python pdf_to_md.py            # ECOURT_CASES_DIR 하위 모든 PDF 변환
```

---

## 파일 구성 / Files

| 파일 | 역할 |
|------|------|
| `ecourt_download.py` | ecfs 로그인, 진행중사건 목록 조회, 기록열람/다운로드 공통 함수 |
| `ecourt_update.py` | 폴더 비교, 신규 사건/문서 감지, 선택적 다운로드, `--sync`/`--download-all` |
| `sync_scheduled.py` | sync 실행 + 텔레그램 알림 래퍼 (단독 실행 가능) |
| `daily_sync_daemon.py` | 매일 지정 시각 자동 실행 데몬 |
| `delivery_to_telegram.py` | (실험적) 송달문서 PDF 다운로드 → 텔레그램 전송 |
| `pdf_to_md.py` | 사건기록 PDF → Markdown 변환 |
| `skip_list.example.json` | 제외 사건 목록 예시 (실제 파일은 `skip_list.json`) |

---

## 알려진 이슈 / 주의 / Known issues & caveats

- **🔴 송달문서 확인 시 송달 효력** — `delivery_to_telegram.py` 는 송달문서를 *여는*
  동작을 포함합니다. 전자소송에서 송달문서 확인은 **송달 효력 발생**으로 이어질 수
  있습니다. 법적 효과를 충분히 이해한 뒤에만 사용하세요. (실험적 기능, 일부 환경에서
  다운로드 트리거가 동작하지 않을 수 있음)
- **세션 타임아웃** — 장시간 작업 시 전자소송 세션 연장 팝업이 뜹니다. 코드가 "연장"을
  자동 클릭하지만, 환경에 따라 만료될 수 있습니다.
- **NFC/NFD 폴더명 충돌** — macOS(NFD)와 Windows(NFC)는 한글 폴더명 정규화가 달라,
  클라우드 동기화 시 같은 사건이 두 폴더로 갈라질 수 있습니다. 사건 폴더명은
  한 가지 정규화(권장: NFC)로 통일하세요.
- **클라우드 동기화는 별도** — 이 도구는 로컬 `ECOURT_CASES_DIR` 에 파일을 둘 뿐이며,
  클라우드 업로드는 OneDrive/Drive/Dropbox 등 **데스크톱 클라이언트**가 담당합니다.
  (rclone 등으로 바꾸려면 다운로드 이후 단계에 동기화 명령을 추가하면 됩니다.)
- **화면 자동화 의존** — 전자소송/보안 프로그램 UI가 바뀌면 셀렉터·창 제목 매칭이
  깨질 수 있습니다.

---

## 면책 / Disclaimer

이 소프트웨어는 학습·자동화 목적의 **비공식** 도구로, 어떠한 보증도 없이 "있는 그대로"
제공됩니다(MIT License). 대한민국 법원행정처 및 전자소송 시스템과 무관합니다.
사용으로 인해 발생하는 모든 결과(세션/계정 문제, 송달 효력, 데이터 손실 등)에 대한
책임은 전적으로 사용자에게 있습니다. 사용 전 반드시 전자소송 이용약관과 관련 법령을
확인하세요.

This is an **unofficial** automation tool provided "as is" without warranty
(MIT License). It is not affiliated with the Korean court system. You are solely
responsible for compliance with the ecfs terms of service and any consequences
of use.

---

## 제공 / Provided by

**쥬리서포트 주식회사 (JuriSupport Inc.)**
문의 / Contact: admin@jurisupport.com

© 2026 JuriSupport Inc. Released under the MIT License.
