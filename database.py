import sqlite3

DB_FILE = 'ul_bot.db'
ALLOWED_COLUMN_DEFINITIONS = {
    "TEXT NOT NULL DEFAULT '@unknown'",
    "TEXT NOT NULL DEFAULT ''",
    'TEXT',
    'INTEGER',
    'INTEGER NOT NULL DEFAULT 1',
    "TEXT NOT NULL DEFAULT 'blurple'",
}
TABLE_INFO_SQL = {
    'birthdays': 'PRAGMA table_info(birthdays)',
    'birthday_settings': 'PRAGMA table_info(birthday_settings)',
    'text_messages': 'PRAGMA table_info(text_messages)',
    'role_messages': 'PRAGMA table_info(role_messages)',
    'role_message_roles': 'PRAGMA table_info(role_message_roles)',
    'reminders': 'PRAGMA table_info(reminders)',
    'user_xp': 'PRAGMA table_info(user_xp)',
    'admin_logs': 'PRAGMA table_info(admin_logs)',
    'public_command_explanations': 'PRAGMA table_info(public_command_explanations)',
    'admin_command_explanations': 'PRAGMA table_info(admin_command_explanations)',
}
ALTER_COLUMN_SQL = {
    ('birthdays', 'username', "TEXT NOT NULL DEFAULT '@unknown'"):
        "ALTER TABLE birthdays ADD COLUMN username TEXT NOT NULL DEFAULT '@unknown'",
    ('birthdays', 'real_name', 'TEXT'):
        'ALTER TABLE birthdays ADD COLUMN real_name TEXT',
    ('birthdays', 'year', 'INTEGER'):
        'ALTER TABLE birthdays ADD COLUMN year INTEGER',
    ('birthdays', 'month', 'INTEGER NOT NULL DEFAULT 1'):
        'ALTER TABLE birthdays ADD COLUMN month INTEGER NOT NULL DEFAULT 1',
    ('birthdays', 'day', 'INTEGER NOT NULL DEFAULT 1'):
        'ALTER TABLE birthdays ADD COLUMN day INTEGER NOT NULL DEFAULT 1',
    ('birthday_settings', 'current_message_channel_id', 'INTEGER'):
        'ALTER TABLE birthday_settings ADD COLUMN current_message_channel_id INTEGER',
    ('text_messages', 'message_content', 'TEXT'):
        'ALTER TABLE text_messages ADD COLUMN message_content TEXT',
    ('text_messages', 'message_content', "TEXT NOT NULL DEFAULT ''"):
        "ALTER TABLE text_messages ADD COLUMN message_content TEXT NOT NULL DEFAULT ''",
    ('text_messages', 'channel_id', 'INTEGER'):
        'ALTER TABLE text_messages ADD COLUMN channel_id INTEGER',
    ('text_messages', 'message_id', 'INTEGER'):
        'ALTER TABLE text_messages ADD COLUMN message_id INTEGER',
    ('role_message_roles', 'color', "TEXT NOT NULL DEFAULT 'blurple'"):
        "ALTER TABLE role_message_roles ADD COLUMN color TEXT NOT NULL DEFAULT 'blurple'",
    ('role_messages', 'description', "TEXT NOT NULL DEFAULT ''"):
        "ALTER TABLE role_messages ADD COLUMN description TEXT NOT NULL DEFAULT ''",
    ('role_messages', 'color', "TEXT NOT NULL DEFAULT 'blurple'"):
        "ALTER TABLE role_messages ADD COLUMN color TEXT NOT NULL DEFAULT 'blurple'",
    ('reminders', 'last_message_id', 'INTEGER'):
        'ALTER TABLE reminders ADD COLUMN last_message_id INTEGER',
    ('reminders', 'last_pin_date', 'TEXT'):
        'ALTER TABLE reminders ADD COLUMN last_pin_date TEXT',
}


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    sql = TABLE_INFO_SQL.get(table)
    if sql is None:
        raise ValueError('Unsupported table name')
    cursor.execute(sql)
    return any(row[1] == column for row in cursor.fetchall())


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    if definition not in ALLOWED_COLUMN_DEFINITIONS:
        raise ValueError('Unsafe column definition')
    if not _column_exists(cursor, table, column):
        sql = ALTER_COLUMN_SQL.get((table, column, definition))
        if sql is None:
            raise ValueError('Unsupported column migration')
        cursor.execute(sql)


def init_database() -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS birthdays (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            real_name TEXT,
            day INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER,
            PRIMARY KEY (guild_id, user_id)
        )
        '''
    )

    # Migration support for older birthday schema
    _ensure_column(cursor, 'birthdays', 'username', "TEXT NOT NULL DEFAULT '@unknown'")
    _ensure_column(cursor, 'birthdays', 'real_name', 'TEXT')
    _ensure_column(cursor, 'birthdays', 'year', 'INTEGER')
    _ensure_column(cursor, 'birthdays', 'day', 'INTEGER NOT NULL DEFAULT 1')
    _ensure_column(cursor, 'birthdays', 'month', 'INTEGER NOT NULL DEFAULT 1')

    cursor.execute(
        '''
        UPDATE birthdays
        SET username = CASE
            WHEN username IS NULL OR username = '' THEN '@unknown'
            ELSE username
        END
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS birthday_settings (
            guild_id INTEGER PRIMARY KEY,
            role_id INTEGER,
            current_message_id INTEGER,
            current_message_channel_id INTEGER,
            list_channel_id INTEGER,
            list_message_id INTEGER,
            last_announce_date TEXT,
            last_cleanup_date TEXT
        )
        '''
    )
    _ensure_column(cursor, 'birthday_settings', 'current_message_channel_id', 'INTEGER')

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS text_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            message_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, title)
        )
        '''
    )

    # Migration support for older text_messages schema
    _ensure_column(cursor, 'text_messages', 'message_content', "TEXT NOT NULL DEFAULT ''")
    _ensure_column(cursor, 'text_messages', 'channel_id', 'INTEGER')
    _ensure_column(cursor, 'text_messages', 'message_id', 'INTEGER')

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS role_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT 'blurple',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    _ensure_column(cursor, 'role_messages', 'description', "TEXT NOT NULL DEFAULT ''")
    _ensure_column(cursor, 'role_messages', 'color', "TEXT NOT NULL DEFAULT 'blurple'")

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS role_message_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_message_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            display_emoji TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'blurple',
            position INTEGER NOT NULL,
            FOREIGN KEY (role_message_id) REFERENCES role_messages(id) ON DELETE CASCADE,
            UNIQUE(role_message_id, emoji)
        )
        '''
    )
    _ensure_column(cursor, 'role_message_roles', 'color', "TEXT NOT NULL DEFAULT 'blurple'")

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            message TEXT NOT NULL,
            last_sent_date TEXT,
            last_message_id INTEGER,
            last_pin_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    _ensure_column(cursor, 'reminders', 'last_message_id', 'INTEGER')
    _ensure_column(cursor, 'reminders', 'last_pin_date', 'TEXT')
    _ensure_column(cursor, 'reminders', 'start_date', 'TEXT')
    _ensure_column(cursor, 'reminders', 'end_date', 'TEXT')

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS welcome_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            embed_flag INTEGER NOT NULL DEFAULT 0,
            color TEXT,
            role_id INTEGER,
            dm_flag INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS user_xp (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            text_xp INTEGER NOT NULL DEFAULT 0,
            voice_xp INTEGER NOT NULL DEFAULT 0,
            last_text_xp_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            person TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS public_command_explanations (
            command TEXT PRIMARY KEY COLLATE NOCASE,
            description TEXT NOT NULL
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS admin_command_explanations (
            command TEXT PRIMARY KEY COLLATE NOCASE,
            description TEXT NOT NULL
        )
        '''
    )

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_birthdays_date ON birthdays (month, day)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_birthdays_lookup ON birthdays (guild_id, user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_text_messages_guild_title ON text_messages (guild_id, title)')
    cursor.execute('DROP INDEX IF EXISTS idx_text_messages_unique_title')
    cursor.execute('DROP INDEX IF EXISTS idx_text_messages_unique_guild_title')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_text_messages_unique_guild_title ON text_messages (guild_id, title COLLATE NOCASE)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_role_messages_lookup ON role_messages (guild_id, message_id)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_role_messages_unique_title ON role_messages (guild_id, title COLLATE NOCASE)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_role_message_roles_lookup ON role_message_roles (role_message_id, emoji)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_unique_guild_title ON reminders (guild_id, title COLLATE NOCASE)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reminders_schedule_lookup ON reminders (hour, minute)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_welcome_unique_guild_channel ON welcome_messages (guild_id, channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_welcome_guild_lookup ON welcome_messages (guild_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_xp_guild_text ON user_xp (guild_id, text_xp DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_xp_guild_voice ON user_xp (guild_id, voice_xp DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_logs_guild_lookup ON admin_logs (guild_id, id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_command_explanations_command ON public_command_explanations (command)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_command_explanations_command ON admin_command_explanations (command)')

    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_database()
