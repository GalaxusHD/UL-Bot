import sqlite3

DB_FILE = 'ul_bot.db'
ALLOWED_COLUMN_DEFINITIONS = {
    "TEXT NOT NULL DEFAULT '@unknown'",
    "TEXT NOT NULL DEFAULT ''",
    'TEXT',
    'INTEGER',
    'INTEGER NOT NULL DEFAULT 1',
}
TABLE_INFO_SQL = {
    'birthdays': 'PRAGMA table_info(birthdays)',
    'birthday_settings': 'PRAGMA table_info(birthday_settings)',
    'text_messages': 'PRAGMA table_info(text_messages)',
    'role_messages': 'PRAGMA table_info(role_messages)',
    'role_message_roles': 'PRAGMA table_info(role_message_roles)',
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
            message_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    # Migration support for older text_messages schema
    _ensure_column(cursor, 'text_messages', 'message_content', "TEXT NOT NULL DEFAULT ''")

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS role_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS role_message_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_message_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            display_emoji TEXT NOT NULL,
            position INTEGER NOT NULL,
            FOREIGN KEY (role_message_id) REFERENCES role_messages(id) ON DELETE CASCADE,
            UNIQUE(role_message_id, emoji)
        )
        '''
    )

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_birthdays_date ON birthdays (month, day)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_birthdays_lookup ON birthdays (guild_id, user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_text_messages_guild_title ON text_messages (guild_id, title)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_text_messages_unique_title ON text_messages (guild_id, title COLLATE NOCASE)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_role_messages_lookup ON role_messages (guild_id, message_id)')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_role_messages_unique_title ON role_messages (guild_id, title COLLATE NOCASE)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_role_message_roles_lookup ON role_message_roles (role_message_id, emoji)')

    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_database()
