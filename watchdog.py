from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
HEARTBEAT_FILE = ROOT_DIR / '.bot_heartbeat'
WATCHDOG_LOG = ROOT_DIR / 'watchdog.log'
CHECK_INTERVAL_SECONDS = 60
STALE_SECONDS = 30


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(WATCHDOG_LOG, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_timestamp(raw_value: object) -> float | None:
    if isinstance(raw_value, (float, int)):
        return float(raw_value)
    if isinstance(raw_value, str):
        try:
            return float(raw_value)
        except ValueError:
            try:
                normalized = raw_value.replace('Z', '+00:00')
                return datetime.fromisoformat(normalized).timestamp()
            except ValueError:
                return None
    return None


def read_heartbeat() -> tuple[int | None, float | None]:
    try:
        payload = json.loads(HEARTBEAT_FILE.read_text(encoding='utf-8'))
    except FileNotFoundError:
        logging.warning('Heartbeat file does not exist yet: %s', HEARTBEAT_FILE)
        return None, None
    except (OSError, json.JSONDecodeError) as exc:
        logging.error('Failed to read heartbeat file: %s', exc)
        return None, None

    pid = payload.get('pid')
    timestamp = parse_timestamp(payload.get('timestamp'))
    if not isinstance(pid, int):
        pid = None
    return pid, timestamp


def write_boot_heartbeat(pid: int) -> None:
    payload = {'timestamp': datetime.now(timezone.utc).timestamp(), 'pid': pid, 'status': 'starting'}
    temp_file = HEARTBEAT_FILE.with_suffix('.tmp')
    temp_file.write_text(json.dumps(payload), encoding='utf-8')
    temp_file.replace(HEARTBEAT_FILE)


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def force_kill(pid: int | None) -> None:
    if pid is None:
        return
    if not is_process_running(pid):
        logging.info('Process %s is already stopped.', pid)
        return

    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=False, capture_output=True, text=True)
        else:
            os.kill(pid, signal.SIGKILL)
        logging.warning('Force-killed bot process %s.', pid)
    except OSError as exc:
        logging.error('Failed to force-kill process %s: %s', pid, exc)


def start_bot_process() -> int | None:
    command = os.getenv('UL_BOT_COMMAND', f'{sys.executable} main.py')
    args = shlex.split(command)
    try:
        process = subprocess.Popen(args, cwd=ROOT_DIR)
        write_boot_heartbeat(process.pid)
        logging.info('Started bot process with PID %s using command: %s', process.pid, command)
        return process.pid
    except OSError as exc:
        logging.error('Failed to start bot process: %s', exc)
        return None


def restart_bot(dead_pid: int | None, reason: str) -> int | None:
    logging.warning('Restarting bot (%s).', reason)
    force_kill(dead_pid)
    for attempt in range(1, 4):
        new_pid = start_bot_process()
        if new_pid is None:
            sleep_seconds = min(5 * attempt, 30)
            logging.warning('Restart attempt %s failed. Retrying in %ss.', attempt, sleep_seconds)
            time.sleep(sleep_seconds)
            continue
        return new_pid

    logging.critical('Bot restart failed after multiple attempts.')
    return None


def main() -> None:
    configure_logging()
    logging.info('Watchdog started. Interval=%ss, stale threshold=%ss', CHECK_INTERVAL_SECONDS, STALE_SECONDS)

    while True:
        pid, timestamp = read_heartbeat()
        now = time.time()
        should_restart = False
        reason = ''

        if pid is None or timestamp is None:
            should_restart = True
            reason = 'missing/invalid heartbeat data'
        elif now - timestamp > STALE_SECONDS:
            should_restart = True
            reason = f'stale heartbeat ({now - timestamp:.1f}s old, pid={pid})'
        elif not is_process_running(pid):
            should_restart = True
            reason = f'bot process {pid} is not running'

        if should_restart:
            pid = restart_bot(pid, reason)
            if pid is not None:
                logging.info('Restart successful. New bot PID: %s', pid)
            else:
                logging.error('Restart failed. Will retry on next watchdog cycle.')

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
