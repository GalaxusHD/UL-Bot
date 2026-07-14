"""
Backup and restore functionality for birthdays, reminders, text messages, logs, and admin roles.
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
TEXT_MESSAGES_BACKUP = BACKUP_DIR / 'text_messages_backup.json'
ADMIN_LOGS_BACKUP = BACKUP_DIR / 'admin_logs_backup.json'
ADMIN_ROLES_BACKUP = BACKUP_DIR / 'admin_roles_backup.json'


def backup_all() -> None:
    """Create backup files for all data (birthdays, reminders, text messages, logs, and admin roles)."""
    backup_birthdays()
    backup_reminders()
    backup_text_messages()
    backup_admin_logs()
    backup_admin_roles()


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


def backup_text_messages() -> None:
    """Backup all text messages to JSON file."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        text_messages = cursor.execute(
            '''
            SELECT id, guild_id, title, channel_id, message_id, message_content, created_at
            FROM text_messages
            ORDER BY guild_id, title
            '''
        ).fetchall()

        conn.close()

        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'text_messages': [dict(row) for row in text_messages],
        }

        with open(TEXT_MESSAGES_BACKUP, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        print(f'✅ Text messages backup created: {TEXT_MESSAGES_BACKUP}')
    except Exception as e:
        print(f'❌ Failed to backup text messages: {e}')


def backup_admin_logs() -> None:
    """Backup all admin logs to JSON file."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        admin_logs = cursor.execute(
            '''
            SELECT id, guild_id, author_id, person, description, created_at
            FROM admin_logs
            ORDER BY guild_id, id
            '''
        ).fetchall()

        conn.close()

        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'admin_logs': [dict(row) for row in admin_logs],
        }

        with open(ADMIN_LOGS_BACKUP, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        print(f'✅ Admin logs backup created: {ADMIN_LOGS_BACKUP}')
    except Exception as e:
        print(f'❌ Failed to backup admin logs: {e}')


def backup_admin_roles() -> None:
    """Backup all admin roles to JSON file."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        admin_roles = cursor.execute(
            '''
            SELECT guild_id, role_id
            FROM admin_roles
            ORDER BY guild_id, role_id
            '''
        ).fetchall()

        conn.close()

        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'admin_roles': [dict(row) for row in admin_roles],
        }

        with open(ADMIN_ROLES_BACKUP, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        print(f'✅ Admin roles backup created: {ADMIN_ROLES_BACKUP}')
    except Exception as e:
        print(f'❌ Failed to backup admin roles: {e}')


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


def restore_text_messages_from_backup() -> bool:
    """Restore text messages from JSON backup file."""
    if not TEXT_MESSAGES_BACKUP.exists():
        print('⚠️ No text messages backup file found.')
        return False

    try:
        with open(TEXT_MESSAGES_BACKUP, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Clear existing data
        cursor.execute('DELETE FROM text_messages')

        # Restore text messages
        for text_msg in backup_data.get('text_messages', []):
            cursor.execute(
                '''
                INSERT INTO text_messages (guild_id, title, channel_id, message_id, message_content)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (
                    text_msg['guild_id'],
                    text_msg['title'],
                    text_msg['channel_id'],
                    text_msg['message_id'],
                    text_msg['message_content'],
                ),
            )

        conn.commit()
        conn.close()

        count = len(backup_data.get('text_messages', []))
        print(f'✅ Restored {count} text messages from backup')
        return True
    except Exception as e:
        print(f'❌ Failed to restore text messages: {e}')
        return False


def restore_admin_logs_from_backup() -> bool:
    """Restore admin logs from JSON backup file."""
    if not ADMIN_LOGS_BACKUP.exists():
        print('⚠️ No admin logs backup file found.')
        return False

    try:
        with open(ADMIN_LOGS_BACKUP, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Clear existing data
        cursor.execute('DELETE FROM admin_logs')

        # Restore admin logs
        for log in backup_data.get('admin_logs', []):
            cursor.execute(
                '''
                INSERT INTO admin_logs (guild_id, author_id, person, description)
                VALUES (?, ?, ?, ?)
                ''',
                (
                    log['guild_id'],
                    log['author_id'],
                    log['person'],
                    log['description'],
                ),
            )

        conn.commit()
        conn.close()

        count = len(backup_data.get('admin_logs', []))
        print(f'✅ Restored {count} admin logs from backup')
        return True
    except Exception as e:
        print(f'❌ Failed to restore admin logs: {e}')
        return False


def restore_admin_roles_from_backup() -> bool:
    """Restore admin roles from JSON backup file."""
    if not ADMIN_ROLES_BACKUP.exists():
        print('⚠️ No admin roles backup file found.')
        return False

    try:
        with open(ADMIN_ROLES_BACKUP, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Clear existing data
        cursor.execute('DELETE FROM admin_roles')

        # Restore admin roles
        for role in backup_data.get('admin_roles', []):
            cursor.execute(
                '''
                INSERT INTO admin_roles (guild_id, role_id)
                VALUES (?, ?)
                ''',
                (
                    role['guild_id'],
                    role['role_id'],
                ),
            )

        conn.commit()
        conn.close()

        count = len(backup_data.get('admin_roles', []))
        print(f'✅ Restored {count} admin roles from backup')
        return True
    except Exception as e:
        print(f'❌ Failed to restore admin roles: {e}')
        return False
