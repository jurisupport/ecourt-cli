"""전자소송 자동 sync 데몬 (사용자 로그인 세션 내 실행).

시작 프로그램(Startup 폴더)에 등록되어 로그인 시 자동 실행되며,
매일 지정 시각에 sync를 실행하고 텔레그램으로 알림.

작업 스케줄러와 달리 사용자의 데스크톱 세션 내에서 실행되므로
pywinauto GUI 자동화가 정상 작동함.

환경변수(.env):
  SYNC_TIME  실행 시각 HH:MM (기본 18:03)
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).parent


def _parse_sync_time() -> tuple[int, int]:
    raw = os.getenv("SYNC_TIME", "18:03")
    try:
        h, m = raw.split(":")
        return int(h), int(m)
    except Exception:
        return 18, 3


RUN_TIME = _parse_sync_time()  # 매일 실행 시각 (HH, MM)
CHECK_INTERVAL = 30  # 30초마다 시간 체크
HEARTBEAT_FILE = PROJECT_DIR / "logs" / "daemon_heartbeat.log"


def log_heartbeat(msg: str):
    """pythonw.exe는 stdout이 없으므로 파일에 직접 기록"""
    HEARTBEAT_FILE.parent.mkdir(exist_ok=True)
    with open(HEARTBEAT_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def next_run_time() -> datetime:
    """다음 실행 시간 계산 (오늘 실행 시각 지났으면 내일)"""
    now = datetime.now()
    run = now.replace(hour=RUN_TIME[0], minute=RUN_TIME[1], second=0, microsecond=0)
    if now >= run:
        run += timedelta(days=1)
    return run


def run_sync():
    """sync_scheduled.py 실행"""
    script = PROJECT_DIR / "sync_scheduled.py"
    log_file = PROJECT_DIR / "logs" / f"daemon_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file.parent.mkdir(exist_ok=True)

    with open(log_file, 'wb') as f:
        subprocess.run(
            [sys.executable, '-u', str(script)],
            stdout=f, stderr=subprocess.STDOUT,
            cwd=str(PROJECT_DIR),
        )


def main():
    print(f"[{datetime.now()}] daily_sync_daemon 시작")
    print(f"  매일 {RUN_TIME[0]:02d}:{RUN_TIME[1]:02d}에 실행")
    print(f"  다음 실행: {next_run_time()}")

    # --test 플래그: 시작 즉시 sync 한번 실행 (데몬 세션 내 GUI 자동화 검증용)
    if '--test' in sys.argv:
        print(f"[{datetime.now()}] TEST MODE: 즉시 sync 실행")
        try:
            run_sync()
        except Exception as e:
            print(f"오류: {e}")
        print(f"[{datetime.now()}] TEST 완료, 데몬 종료")
        return

    log_heartbeat(f"daemon 시작, 다음 실행: {next_run_time()}")
    last_heartbeat = datetime.now()

    while True:
        try:
            target = next_run_time()
            now = datetime.now()
            wait_sec = (target - now).total_seconds()

            # 10분마다 heartbeat
            if (now - last_heartbeat).total_seconds() >= 600:
                log_heartbeat(f"생존 중, 다음 실행까지 {int(wait_sec)}초")
                last_heartbeat = now

            if wait_sec <= 0:
                log_heartbeat("sync 실행 시작")
                try:
                    run_sync()
                    log_heartbeat("sync 실행 종료")
                except Exception as e:
                    log_heartbeat(f"sync 오류: {e}")
                # sync 종료 후 1분 더 자서 같은 분에 재실행 방지
                time.sleep(60)
            elif wait_sec < CHECK_INTERVAL:
                # 목표 시간까지 정확히 대기 후 즉시 sync 실행
                log_heartbeat(f"목표 근접, {int(wait_sec)}초 대기 후 sync 실행")
                time.sleep(wait_sec + 1)  # 1초 여유로 목표 시간 확실히 통과
                log_heartbeat("sync 실행 시작 (목표시간 도달)")
                try:
                    run_sync()
                    log_heartbeat("sync 실행 종료")
                except Exception as e:
                    log_heartbeat(f"sync 오류: {e}")
                time.sleep(60)
            else:
                time.sleep(CHECK_INTERVAL)
        except Exception as e:
            log_heartbeat(f"루프 오류: {e}")
            time.sleep(60)


if __name__ == '__main__':
    main()
