# ecourt-cli

전자소송(ecfs) **진행중사건 기록 자동 다운로드/동기화** 도구.
Korea Electronic Court (ecfs.scourt.go.kr) case-record auto-downloader & sync tool.

> **쥬리서포트 주식회사(JuriSupport Co., Ltd.)** 가 제공하는 오픈소스 도구입니다.
> Provided as open source by **JuriSupport Co., Ltd. (쥬리서포트 주식회사)**.

매일 정해진 시각에 전자소송에 로그인하여, 내 진행중사건의 새 문서만 골라
로컬 사건 폴더로 내려받고(클라우드 동기화 폴더 사용 시 자동 백업) 결과를
텔레그램으로 보고합니다.

> ⚠️ **비공식(Unofficial) 도구입니다.** 대한민국 법원 전자소송 시스템과 무관하며,
> 화면 자동화(브라우저 + 데스크톱 앱 제어)에 의존하므로 사이트 구조가 바뀌면
> 동작하지 않을 수 있습니다. 사용 전 전자소송 이용약관을 확인하고 **본인 책임**
> 하에 사용하세요. (면책 조항은 하단 참고)

---

## 🚀 설치 / Installation (처음 사용자용)

> **Windows 10/11** 전용입니다. 아래 명령어는 모두 **PowerShell** 창에 입력합니다.
> 컴퓨터를 잘 모르셔도 순서대로 따라 하면 됩니다.

### ⚡ 한 줄 설치 (가장 간단, 권장)

**PowerShell**(아래 *0단계* 참고로 엶)에 다음 한 줄을 붙여넣고 Enter:

```powershell
irm https://raw.githubusercontent.com/jurisupport/ecourt-cli/main/install.ps1 | iex
```

Python(없으면 winget으로 자동 설치) → 소스 다운로드 → 가상환경 + 라이브러리 + Playwright(Edge)
설치까지 한 번에 진행하고, 이어서 환경설정(`.env`)도 안내합니다.
설치 폴더는 `사용자\ecourt-cli` 입니다.

> winget이 없는 구형 Windows거나 자동 설치가 막힌 환경이라면, 아래 **수동 설치** 단계를 따르세요.

<details>
<summary><b>수동 설치 (단계별)</b> — 펼치기</summary>

### 0단계 — PowerShell(파워쉘) 여는 법

1. 키보드의 **⊞ Windows 키**를 누릅니다.
2. `powershell` 이라고 입력합니다.
3. 목록에 나오는 **Windows PowerShell** 을 클릭합니다.
4. 파란색(또는 검은색) 창이 뜨면 준비 완료입니다.

> 또는 화면 왼쪽 아래 **시작 버튼을 마우스 우클릭 → "터미널" 또는 "Windows PowerShell"** 을 눌러도 됩니다.
> 앞으로 "PowerShell에 입력"이라고 하면 이 창에 명령어를 친 뒤 **Enter** 를 누르라는 뜻입니다.

### 1단계 — 필수 프로그램 설치 (최초 1회)

| 프로그램 | 받는 곳 | 비고 |
|---|---|---|
| **Python 3.10 이상** | https://www.python.org/downloads/ | 설치 화면에서 **"Add Python to PATH" 체크** 꼭! |
| **Microsoft Edge** | Windows 기본 설치 | 보통 이미 설치돼 있음 |
| **Git** (선택) | https://git-scm.com/download/win | 없으면 2단계의 *ZIP 다운로드* 방식 사용 |
| **전자소송 보안 프로그램** | 전자소송 최초 접속 시 자동 설치 | SgvDownloader 등 |

설치 후 PowerShell에서 확인:
```powershell
python --version
```
`Python 3.10.x` 이상이 나오면 정상입니다.

### 2단계 — 프로그램 내려받기

원하는 위치(예: **내 문서**)에 받습니다.

**방법 A) Git 사용 (권장)**
```powershell
cd $HOME\Documents
git clone https://github.com/jurisupport/ecourt-cli.git
cd ecourt-cli
```

**방법 B) ZIP 다운로드 (Git 없이)**
1. https://github.com/jurisupport/ecourt-cli 접속
2. 초록색 **`< > Code` ▾ → `Download ZIP`** 클릭
3. 받은 ZIP을 **내 문서** 등에 압축 해제 (폴더 이름은 `ecourt-cli`)
4. PowerShell에서 그 폴더로 이동:
```powershell
cd $HOME\Documents\ecourt-cli
```

### 3단계 — 설치 (가상환경 + 라이브러리)

아래 세 줄을 차례로 입력합니다. (몇 분 걸릴 수 있습니다)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install msedge
```

### 4단계 — 환경 설정 (`.env` 만들기)

대화형 셋업 도구를 실행하면 ID·인증서 비밀번호·저장 폴더 등을 차례로 묻고,
**이 PC에 저장된 공동인증서를 자동으로 찾아** 선택할 수 있습니다.
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_env.ps1
```
- 비밀번호·토큰은 입력해도 **화면에 보이지 않습니다.**
- Enter만 누르면 기존 값이 유지됩니다.
- 나중에 값 확인/수정:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\setup_env.ps1 -Show               # 현재 값 보기(비번 가림)
  powershell -ExecutionPolicy Bypass -File .\setup_env.ps1 -Set "SYNC_TIME=09:00"   # 특정 값만 수정
  powershell -ExecutionPolicy Bypass -File .\setup_env.ps1 -ListCerts          # 내 PC의 인증서 목록만 보기
  ```

→ 채워야 할 값은 아래 [환경 변수](#환경-변수--env) 표를 참고하세요.

### 5단계 — 첫 실행 (한 건만 받아보기)

```powershell
.\.venv\Scripts\python.exe ecourt_download.py --case 0
```
Edge 창이 떠서 자동 로그인 → **첫 번째 사건**의 기록을 저장 폴더로 내려받습니다.
정상 동작을 확인했으면 전체 동기화를 실행합니다:
```powershell
.\.venv\Scripts\python.exe sync_scheduled.py
```

> 💡 **항상 `.\.venv\Scripts\python.exe` 로 실행하세요.** 그냥 `python` 으로 실행하면
> 설치한 라이브러리를 못 찾아 오류가 납니다.
>
> ⚠️ 화면 자동화 도구라 **잠긴 화면·원격 데스크톱에서는 동작하지 않습니다.**
> 반드시 사용자가 로그인된 데스크톱 화면에서 실행하세요.

</details>

---

## 환경 변수 / .env

`setup_env.ps1` 로 채우는 값들입니다. (직접 편집하려면 `.env` 파일을 UTF-8로 저장)

| 변수 | 설명 |
|------|------|
| `ECFS_USER_ID` | 전자소송 사용자 ID |
| `ECFS_CERT_PW` | 공동인증서 비밀번호. `setup_env.ps1` 사용 시 **DPAPI로 암호화**되어 `ECFS_CERT_PW_ENC`로 저장됨(평문 저장 안 함) |
| `ECFS_CERT_NAME` | 인증서 목록에서 선택할 이름(본인 성명/법인명) |
| `ECFS_CERT_STORAGE` | 인증서 저장 위치 탭. `브라우저` / `하드디스크` / `이동식디스크` / `스마트인증` (전자소송 로그인 창의 라벨과 동일하게) |
| `ECFS_CERT_DIR` / `ECFS_CERT_SERIAL` | (자동 폴백용) 브라우저에 인증서가 없을 때 `인증서찾기`로 등록할 NPKI 위치. `setup_env.ps1` 의 인증서 검색으로 자동 기입됨 |
| `ECOURT_CASES_DIR` | 사건 폴더 저장 루트 (클라우드 동기화 폴더 권장) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 ([@BotFather](https://t.me/BotFather)로 발급, 알림 쓸 때만). DPAPI 암호화(`TELEGRAM_BOT_TOKEN_ENC`) |
| `TELEGRAM_CHAT_ID` | 알림 받을 채팅 ID |
| `SYNC_TIME` | 데몬 실행 시각 `HH:MM` (기본 `18:03`) |

> 🔐 **비밀번호·토큰 보호:** `setup_env.ps1` 로 입력한 인증서 비밀번호와 텔레그램 토큰은
> **Windows DPAPI** 로 암호화되어 `ECFS_CERT_PW_ENC` / `TELEGRAM_BOT_TOKEN_ENC` 형태로 저장됩니다.
> - DPAPI는 **현재 Windows 사용자 계정**에 묶여 복호화되므로, 마스터 비밀번호 입력 없이 무인 데몬에서도 동작합니다.
> - 같은 평문도 매번 다른 암호문이 됩니다. 디스크 도난·백업 유출·실수 커밋·같은 PC의 다른 사용자로부터 보호됩니다.
> - 단, **같은 Windows 계정으로 실행되는 악성코드**는 동일 키로 복호화할 수 있습니다(앱이 복호화해야 하므로 불가피한 한계).
>
> `.env`(+백업 `.env.*`), `edge_profile/`, `skip_list.json`, 다운로드된 `*.pdf` 등은
> `.gitignore`로 저장소에서 제외됩니다. **`.env`는 절대 커밋하지 마세요.**

### 🔑 인증서 로그인 방식

전자소송 공동인증서(NPKI)로 로그인합니다. `ECFS_CERT_STORAGE` 에 지정한 저장 위치 탭에서
`ECFS_CERT_NAME` 이 포함된 인증서를 선택합니다.

- **권장: `브라우저`** — 인증서를 브라우저에 한 번 저장해 두면 이후 자동 로그인이 안정적입니다.
- 브라우저 탭에 인증서가 없으면, 이 도구가 자동으로 **`인증서찾기` → `signCert.der`+`signPri.key`
  주입 → "브라우저에 저장"** 까지 수행한 뒤 로그인합니다(self-healing). 이때 인증서 파일은
  `ECFS_CERT_DIR`/`ECFS_CERT_SERIAL` 또는 전체 드라이브의 NPKI 폴더에서 자동 탐색합니다.
- `하드디스크` 탭은 일부 환경에서 `AppData\LocalLow\NPKI` 를 읽지 못해 목록이 비어 보일 수
  있습니다. 그럴 땐 `브라우저` 로 두면 자동 등록 폴백이 동작합니다.

---

## 사용법 / Usage

> 모든 명령은 `ecourt-cli` 폴더 안에서, venv 파이썬으로 실행합니다.

### 1) 수동 1회 실행 (텔레그램 보고 포함)
```powershell
.\.venv\Scripts\python.exe sync_scheduled.py
```

### 2) 감지/다운로드 직접 실행
```powershell
# ecfs 신규 사건 감지 + 기존 사건 업데이트 다운로드 (메인 모드)
.\.venv\Scripts\python.exe ecourt_update.py --sync

# 사건 폴더 날짜 기준으로 전체 재점검 다운로드
.\.venv\Scripts\python.exe ecourt_update.py --download-all

# 외부 사건관리 데이터(JSON)와 폴더 비교만
.\.venv\Scripts\python.exe ecourt_update.py --detect --data case_data.json
```

### 3) 전체 기록 일괄 다운로드 (최초 1회)
```powershell
.\.venv\Scripts\python.exe ecourt_download.py            # 진행중사건 전체
.\.venv\Scripts\python.exe ecourt_download.py --case 0   # 첫 번째 사건만
.\.venv\Scripts\python.exe ecourt_download.py --list     # 목록만 저장(case_list.json)
```

### 4) 매일 자동 실행 (데몬)
`daily_sync_daemon.py` 를 **시작프로그램(Startup)** 폴더에 등록하면 로그인 시
자동 실행되어 매일 `SYNC_TIME` 에 sync를 돌립니다. (시작프로그램 폴더는 PowerShell에
`shell:startup` 입력 → Enter 로 열 수 있습니다)

```bat
:: 예: start_daemon.bat 를 만들어 Startup 폴더(shell:startup)에 둠
start "ecourt_daemon" /MIN python.exe daily_sync_daemon.py
```
즉시 1회 검증 실행:
```powershell
.\.venv\Scripts\python.exe daily_sync_daemon.py --test
```

### 5) PDF → Markdown 변환 (선택)
```powershell
.\.venv\Scripts\python.exe pdf_to_md.py            # ECOURT_CASES_DIR 하위 모든 PDF 변환
```

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

1. **로그인** — Playwright가 Edge 영속 프로필로 전자소송에 접속, 공동인증서로 로그인.
   저장 위치는 `ECFS_CERT_STORAGE` 로 지정하며, 브라우저에 인증서가 없으면 `인증서찾기`로 자동 등록.
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
| 로그인 | 공동인증서(NPKI) — 저장위치 설정(`ECFS_CERT_STORAGE`), 브라우저 미보유 시 `인증서찾기` 자동 등록 폴백 |
| 알림 | Telegram Bot API (sendMessage / sendDocument) |
| 스케줄 | 시작프로그램 등록 데몬 (Windows Startup) |
| PDF 추출(선택) | [PyMuPDF](https://pymupdf.readthedocs.io/) |

---

## 파일 구성 / Files

| 파일 | 역할 |
|------|------|
| `ecourt_download.py` | ecfs 로그인, 진행중사건 목록 조회, 기록열람/다운로드 공통 함수 |
| `ecourt_update.py` | 폴더 비교, 신규 사건/문서 감지, 선택적 다운로드, `--sync`/`--download-all` |
| `sync_scheduled.py` | sync 실행 + 텔레그램 알림 래퍼 (단독 실행 가능) |
| `daily_sync_daemon.py` | 매일 지정 시각 자동 실행 데몬 |
| `setup_env.ps1` | `.env` 입력/수정/조회 + 인증서 자동검색 PowerShell 도구 |
| `secret_store.py` | 비밀번호/토큰 DPAPI 암호화·복호화 헬퍼 (ctypes, 의존성 없음) |
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
- **PowerShell 스크립트 인코딩** — `setup_env.ps1` 은 한글 표시를 위해 **UTF-8(BOM 포함)**
  으로 저장돼 있습니다. 다른 에디터로 수정·저장할 때 같은 인코딩을 유지하세요.

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

**쥬리서포트 주식회사 (JuriSupport Co., Ltd.)**
문의 / Contact: admin@jurisupport.com

© 2026 JuriSupport Co., Ltd. Released under the MIT License.
