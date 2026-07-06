"""
Backup and restore functionality for birthdays and reminders.
Saves JSON backups to prevent data loss during crashes.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from database import DB_FILE

BACKUP_DIR = Path('backups')
BACKUP_DIR.mkdir(exist_ok=True)

BIRTHDAYS_BACKUP = BACKUP_DIR / 'birthdays_backup.json'
REMINDERS_BACKUP = BACKUP_DIR / 'reminders_backup.json'


def backup_all() -> None:
    """Create backup files for all data (birthdays and reminders)."""
    backup_birthdays()
    backup_reminders()


def backup_birthdays() -> None:
    """Backup all birthdays to JSON file."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        birthdays = cursor.execute(
            '''
            SELECT guild_id, user_id, username, real_name, day, month, year
            FROM birthdays
            ORDER BY guild_id, month, day
            '''
        ).fetchall()

        birthday_settings = cursor.execute(
            '''
            SELECT guild_id, role_id, current_message_id, current_message_channel_id,
                   list_channel_id, list_message_id, last_announce_date, last_cleanup_date
            FROM birthday_settings
            '''
        ).fetchall()

        conn.close()

        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'birthdays': [dict(row) for row in birthdays],
            'settings': [dict(row) for row in birthday_settings],
        }

        with open(BIRTHDAYS_BACKUP, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        print(f'✅ Birthdays backup created: {BIRTHDAYS_BACKUP}')
    except Exception as e:
        print(f'❌ Failed to backup birthdays: {e}')


def backup_reminders() -> None:
    """Backup all reminders to JSON file."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        reminders = cursor.execute(
            '''
            SELECT id, guild_id, channel_id, title, hour, minute, message,
                   last_sent_date, last_message_id, last_pin_date,
                   start_date, end_date, created_at
            FROM reminders
            ORDER BY guild_id, title
            '''
        ).fetchall()

        conn.close()

        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'reminders': [dict(row) for row in reminders],
        }

        with open(REMINDERS_BACKUP, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        print(f'✅ Reminders backup created: {REMINDERS_BACKUP}')
    except Exception as e:
        print(f'❌ Failed to backup reminders: {e}')


def restore_birthdays_from_backup() -> bool:
    """Restore birthdays from JSON backup file."""
    if not BIRTHDAYS_BACKUP.exists():
        print('⚠️ No birthdays backup file found.')
        return False

    try:
        with open(BIRTHDAYS_BACKUP, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Clear existing data
        cursor.execute('DELETE FROM birthdays')
        cursor.execute('DELETE FROM birthday_settings')

        # Restore birthdays
        for birthday in backup_data.get('birthdays', []):
            cursor.execute(
                '''
                INSERT INTO birthdays (guild_id, user_id, username, real_name, day, month, year)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    birthday['guild_id'],
                    birthday['user_id'],
                    birthday['username'],
                    birthday['real_name'],
                    birthday['day'],
                    birthday['month'],
                    birthday['year'],
                ),
            )

        # Restore settings
        for setting in backup_data.get('settings', []):
            cursor.execute(
                '''
                INSERT INTO birthday_settings (guild_id, role_id, current_message_id,
                    current_message_channel_id, list_channel_id, list_message_id,
                    last_announce_date, last_cleanup_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    setting['guild_id'],
                    setting['role_id'],
                    setting['current_message_id'],
                    setting['current_message_channel_id'],
                    setting['list_channel_id'],
                    setting['list_message_id'],
                    setting['last_announce_date'],
                    setting['last_cleanup_date'],
                ),
            )

        conn.commit()
        conn.close()

        count = len(backup_data.get('birthdays', []))
        print(f'✅ Restored {count} birthdays from backup')
        return True
    except Exception as e:
        print(f'❌ Failed to restore birthdays: {e}')
        return False


def restore_reminders_from_backup() -> bool:
    """Restore reminders from JSON backup file."""
    if not REMINDERS_BACKUP.exists():
        print('⚠️ No reminders backup file found.')
        return False

    try:
        with open(REMINDERS_BACKUP, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Clear existing data
        cursor.execute('DELETE FROM reminders')

        # Restore reminders
        for reminder in backup_data.get('reminders', []):
            cursor.execute(
                '''
                INSERT INTO reminders (guild_id, channel_id, title, hour, minute, message,
                    last_sent_date, last_message_id, last_pin_date,
                    start_date, end_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    reminder['guild_id'],
                    reminder['channel_id'],
                    reminder['title'],
                    reminder['hour'],
                    reminder['minute'],
                    reminder['message'],
                    reminder['last_sent_date'],
                    reminder['last_message_id'],
                    reminder['last_pin_date'],
                    reminder['start_date'],
                    reminder['end_date'],
                ),
            )

        conn.commit()
        conn.close()

        count = len(backup_data.get('reminders', []))
        print(f'✅ Restored {count} reminders from backup')
        return True
    except Exception as e:
        print(f'❌ Failed to restore reminders: {e}')
        return False
