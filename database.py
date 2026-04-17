import sqlite3

DB_FILE = 'ul_bot.db'


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f'PRAGMA table_info({table})')
    return any(row[1] == column for row in cursor.fetchall())


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    if not _column_exists(cursor, table, column):
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


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
    _ensure_column(cursor, 'birthdays', 'username', "TEXT NOT NULL DEFAULT ''")
    _ensure_column(cursor, 'birthdays', 'real_name', 'TEXT')
    _ensure_column(cursor, 'birthdays', 'year', 'INTEGER')
    if _column_exists(cursor, 'birthdays', 'day') and _column_exists(cursor, 'birthdays', 'month'):
        pass
    elif _column_exists(cursor, 'birthdays', 'month') and _column_exists(cursor, 'birthdays', 'day'):
        pass
    elif _column_exists(cursor, 'birthdays', 'day'):
        _ensure_column(cursor, 'birthdays', 'month', 'INTEGER NOT NULL DEFAULT 1')
    elif _column_exists(cursor, 'birthdays', 'month'):
        _ensure_column(cursor, 'birthdays', 'day', 'INTEGER NOT NULL DEFAULT 1')

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
