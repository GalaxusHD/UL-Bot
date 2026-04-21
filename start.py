from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
HEARTBEAT_FILE = ROOT_DIR / '.bot_heartbeat'
WATCHDOG_PID_FILE = ROOT_DIR / '.bot_watchdog.pid'

shutdown_requested = False


def write_heartbeat(pid: int, status: str = 'starting') -> None:
    payload = {'timestamp': datetime.now(timezone.utc).timestamp(), 'pid': pid, 'status': status}
    temp_file = HEARTBEAT_FILE.with_suffix('.tmp')
    temp_file.write_text(json.dumps(payload), encoding='utf-8')
    temp_file.replace(HEARTBEAT_FILE)


def terminate_process(process: subprocess.Popen[bytes] | None, force_after: int = 10) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    deadline = time.time() + force_after
    while process.poll() is None and time.time() < deadline:
        time.sleep(0.25)

    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/PID', str(process.pid)], check=False, capture_output=True, text=True)
        else:
            process.kill()


def terminate_pid(pid: int | None, force_after: int = 10) -> None:
    if pid is None:
        return
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return

    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=False, capture_output=True, text=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return

    deadline = time.time() + force_after
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.25)
        except ProcessLookupError:
            return

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def get_heartbeat_pid() -> int | None:
    try:
        payload = json.loads(HEARTBEAT_FILE.read_text(encoding='utf-8'))
        pid = payload.get('pid')
        return pid if isinstance(pid, int) else None
    except (OSError, json.JSONDecodeError):
        return None


def handle_signal(_signum: int, _frame: object) -> None:
    global shutdown_requested
    shutdown_requested = True


def main() -> None:
    global shutdown_requested

    signal.signal(signal.SIGINT, handle_signal)
    sigterm = getattr(signal, 'SIGTERM', None)
    if sigterm is not None:
        signal.signal(sigterm, handle_signal)

    bot_command = [sys.executable, 'main.py']
    bot_process = subprocess.Popen(bot_command, cwd=ROOT_DIR)
    write_heartbeat(bot_process.pid)
    print(f'Started bot process with PID {bot_process.pid}')

    env = os.environ.copy()
    env['UL_BOT_COMMAND'] = f'{sys.executable} main.py'
    watchdog_process = subprocess.Popen([sys.executable, 'watchdog.py'], cwd=ROOT_DIR, env=env)
    WATCHDOG_PID_FILE.write_text(str(watchdog_process.pid), encoding='utf-8')
    print(f'Started watchdog process with PID {watchdog_process.pid}')

    try:
        while not shutdown_requested:
            if watchdog_process.poll() is not None:
                print('Watchdog exited unexpectedly. Restarting watchdog...')
                watchdog_process = subprocess.Popen([sys.executable, 'watchdog.py'], cwd=ROOT_DIR, env=env)
                WATCHDOG_PID_FILE.write_text(str(watchdog_process.pid), encoding='utf-8')
            time.sleep(1)
    finally:
        print('Shutting down bot and watchdog...')
        terminate_process(watchdog_process)
        terminate_process(bot_process)
        terminate_pid(get_heartbeat_pid())
        try:
            WATCHDOG_PID_FILE.unlink()
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
