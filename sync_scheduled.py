"""자동 sync 스크립트 (텔레그램 알림 포함).

ecourt_update.py --sync 를 실행하고 결과를 텔레그램으로 보고한다.
스케줄러/데몬 없이 단독 실행도 가능.

환경변수(.env):
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰 (@BotFather 발급)
  TELEGRAM_CHAT_ID    알림 받을 채팅 ID
"""

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── 설정 ───────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LOG_DIR = PROJECT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


def load_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "환경변수 TELEGRAM_BOT_TOKEN 가 없습니다. .env 파일에 봇 토큰을 입력하세요."
        )
    return token


def send_telegram(token: str, chat_id: str, text: str):
    """텔레그램 봇 API로 메시지 전송"""
    if not chat_id:
        print("[텔레그램] TELEGRAM_CHAT_ID 미설정 - 전송 생략")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
    }).encode('utf-8')
    try:
        with urllib.request.urlopen(url, data=data, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[텔레그램 전송 실패] {e}")
        return False


def send_telegram_document(token: str, chat_id: str, file_path: Path, caption: str = ""):
    """텔레그램 봇 API로 파일 전송 (multipart/form-data)"""
    if not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    boundary = "----TGBoundary" + os.urandom(8).hex()
    body = []
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode('utf-8'))
    if caption:
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode('utf-8'))
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{file_path.name}\"\r\nContent-Type: text/plain\r\n\r\n".encode('utf-8'))
    body.append(file_path.read_bytes())
    body.append(f"\r\n--{boundary}--\r\n".encode('utf-8'))
    data = b"".join(body)
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[텔레그램 파일 전송 실패] {e}")
        return False


def clean_edge_profile():
    """Edge 프로필 잠금 파일 정리"""
    os.system('taskkill /F /IM msedge.exe >nul 2>&1')
    profile_dir = PROJECT_DIR / "edge_profile"
    for lock in ['SingletonLock', 'SingletonCookie', 'SingletonSocket']:
        p = profile_dir / lock
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass


def parse_sync_output(output_file: Path) -> dict:
    """sync 출력 파싱하여 요약 반환"""
    with open(output_file, 'rb') as f:
        data = f.read().decode('cp949', 'replace')
    lines = data.splitlines()

    result = {
        'ecfs_total': 0,
        'existing': 0,
        'skipped': 0,
        'new_cases': [],
        'updated_files': 0,
        'updated_cases': 0,
        'errors': 0,
        'new_case_downloads': 0,
    }

    for l in lines:
        m = re.search(r'ecfs 전체:\s*(\d+)', l)
        if m:
            result['ecfs_total'] = int(m.group(1))
        m = re.search(r'기존.*:\s*(\d+)', l)
        if m:
            result['existing'] = int(m.group(1))
        m = re.search(r'제외.*:\s*(\d+)', l)
        if m:
            result['skipped'] = int(m.group(1))
        m = re.search(r'신규:\s*(\d+)', l)
        if m:
            result['new_count'] = int(m.group(1))
        if '[오류]' in l:
            result['errors'] += 1

    # 신규 파일 집계
    files_moved = [l for l in lines if '신규 파일' in l and '이동 완료' in l]
    for l in files_moved:
        m = re.search(r'신규 파일 (\d+)개', l)
        if m:
            n = int(m.group(1))
            result['updated_files'] += n
            if n > 0:
                result['updated_cases'] += 1

    # 신규 사건 목록 (있으면)
    in_new_block = False
    for l in lines:
        if '[신규 사건]' in l:
            in_new_block = True
            continue
        if in_new_block:
            if l.startswith('신규') or not l.strip():
                break
            m = re.match(r'\s+(\S+)\s+(\S+)\s+(.+)', l)
            if m:
                result['new_cases'].append(l.strip())

    return result


def main():
    bot_token = load_bot_token()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = LOG_DIR / f"sync_{ts}.log"

    # 1) 시작 알림
    start_time = datetime.now()
    send_telegram(bot_token, CHAT_ID,
        f"[자동 sync 시작] {start_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"전자소송 사건기록 업데이트 시작합니다.")

    # 2) Edge 프로필 정리
    clean_edge_profile()

    # 3) sync 실행 (python.exe 명시 - pythonw에서는 GUI 접근 불가)
    script = PROJECT_DIR / "ecourt_update.py"
    python_exe = shutil.which('python') or 'python'
    try:
        with open(log_file, 'wb') as f:
            proc = subprocess.run(
                [python_exe, '-u', str(script), '--sync'],
                stdout=f, stderr=subprocess.STDOUT,
                cwd=str(PROJECT_DIR),
                timeout=43200,  # 12시간
            )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
        # 타임아웃 시 서브프로세스 강제 종료 (이미 kill된 상태지만 확실히)
        os.system('taskkill /F /IM msedge.exe >nul 2>&1')
        os.system('taskkill /F /IM SgvDownloader.exe >nul 2>&1')
        # 부분 결과라도 파싱 시도
        try:
            summary = parse_sync_output(log_file)
            elapsed = datetime.now() - start_time
            msg = f"[자동 sync 타임아웃] 12시간 초과, 부분 완료\n\n"
            msg += f"처리된 사건: 로그 참조\n"
            msg += f"다운로드 파일: {summary.get('updated_files', 0)}개 (부분)\n"
            msg += f"소요: {int(elapsed.total_seconds()/60)}분\n"
            msg += f"로그: {log_file.name}"
            send_telegram(bot_token, CHAT_ID, msg)
        except Exception:
            send_telegram(bot_token, CHAT_ID,
                f"[자동 sync 타임아웃] 12시간 초과. 로그: {log_file.name}")
        return

    # 4) 결과 파싱
    elapsed = datetime.now() - start_time
    elapsed_min = int(elapsed.total_seconds() / 60)

    try:
        summary = parse_sync_output(log_file)
    except Exception as e:
        send_telegram(bot_token, CHAT_ID,
            f"[자동 sync 완료] 소요 {elapsed_min}분\n"
            f"결과 파싱 실패: {e}\n로그: {log_file}")
        return

    # 5) 완료 알림
    msg = f"[자동 sync 완료] 소요 {elapsed_min}분\n\n"
    msg += f"ecfs 전체: {summary['ecfs_total']}건\n"
    msg += f"기존: {summary['existing']}건\n"
    msg += f"제외 (skip_list): {summary['skipped']}건\n"
    msg += f"신규: {summary.get('new_count', 0)}건\n\n"

    if summary['new_cases']:
        msg += "[신규 사건]\n"
        for c in summary['new_cases']:
            msg += f"  • {c}\n"
        msg += "\n"

    msg += f"업데이트 다운로드: {summary['updated_cases']}건에서 {summary['updated_files']}개 파일\n"

    if summary['errors']:
        msg += f"오류: {summary['errors']}건 (로그 확인 필요)\n"

    if exit_code != 0:
        msg += f"\n⚠ exit code {exit_code}"

    send_telegram(bot_token, CHAT_ID, msg)

    # 6) 로그 파일 첨부 전송
    if log_file.exists() and log_file.stat().st_size > 0:
        size_mb = log_file.stat().st_size / 1024 / 1024
        caption = f"sync 로그 ({size_mb:.1f}MB) - {start_time.strftime('%Y-%m-%d %H:%M')}"
        send_telegram_document(bot_token, CHAT_ID, log_file, caption=caption)


if __name__ == '__main__':
    main()
