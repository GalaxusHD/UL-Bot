import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RolePanel:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    title: str
    multi_role: bool


@dataclass(slots=True)
class RolePanelEntry:
    panel_id: int
    role_id: int
    emoji: str


class Database:
    def __init__(self, path: str = "ul_bot.db") -> None:
        self.path = Path(path)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_tables(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS role_panels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    multi_role INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS role_panel_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    FOREIGN KEY(panel_id) REFERENCES role_panels(id) ON DELETE CASCADE
                )
                """
            )
            connection.commit()

    def create_role_panel(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        title: str,
        multi_role: bool,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO role_panels(guild_id, channel_id, message_id, title, multi_role)
                VALUES(?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, message_id, title, int(multi_role)),
            )
            connection.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create role panel row.")
            return int(cursor.lastrowid)

    def add_role_panel_entry(self, panel_id: int, role_id: int, emoji: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO role_panel_entries(panel_id, role_id, emoji)
                VALUES(?, ?, ?)
                """,
                (panel_id, role_id, emoji),
            )
            connection.commit()

    def get_role_panel_by_message_id(self, message_id: int) -> tuple[RolePanel, list[RolePanelEntry]] | None:
        with self._connect() as connection:
            panel_row = connection.execute(
                "SELECT * FROM role_panels WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if panel_row is None:
                return None
            entries = connection.execute(
                "SELECT panel_id, role_id, emoji FROM role_panel_entries WHERE panel_id = ?",
                (int(panel_row["id"]),),
            ).fetchall()
        panel = RolePanel(
            id=int(panel_row["id"]),
            guild_id=int(panel_row["guild_id"]),
            channel_id=int(panel_row["channel_id"]),
            message_id=int(panel_row["message_id"]),
            title=str(panel_row["title"]),
            multi_role=bool(panel_row["multi_role"]),
        )
        mapped_entries = [
            RolePanelEntry(
                panel_id=int(entry["panel_id"]),
                role_id=int(entry["role_id"]),
                emoji=str(entry["emoji"]),
            )
            for entry in entries
        ]
        return panel, mapped_entries

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
