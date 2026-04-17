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
