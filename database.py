import sqlite3

DB_FILE = 'ul_bot.db'


def init_database() -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS birthdays (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            day INTEGER NOT NULL,
            last_congratulated_year INTEGER,
            PRIMARY KEY (guild_id, user_id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS text_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            message_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

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
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_text_messages_guild_title ON text_messages (guild_id, title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_role_messages_lookup ON role_messages (guild_id, message_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_role_message_roles_lookup ON role_message_roles (role_message_id, emoji)')

    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_database()