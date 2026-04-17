import re
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

COMMAND_NAME_PATTERN = re.compile(r'^[a-z0-9_]{1,32}$')


class TextMessages(commands.Cog):
    text = app_commands.Group(name='text', description='Text-Kommandos verwalten')

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._dynamic_commands: dict[tuple[int, str], app_commands.Command] = {}

    @staticmethod
    def _conn() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

    async def cog_load(self) -> None:
        await self._reload_dynamic_commands(sync=False)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self._reload_dynamic_commands(sync=True)

    def _is_valid_custom_command_name(self, name: str) -> bool:
        reserved = {'text', 'role', 'geburtstag', 'ping'}
        return bool(COMMAND_NAME_PATTERN.fullmatch(name)) and name not in reserved

    async def _reload_dynamic_commands(self, sync: bool) -> None:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    'SELECT DISTINCT guild_id, LOWER(title) AS name FROM text_messages ORDER BY guild_id, name'
                ).fetchall()
        except sqlite3.OperationalError:
            return

        target_keys = {(int(row['guild_id']), str(row['name'])) for row in rows}

        # Remove commands that no longer exist in DB
        for key in list(self._dynamic_commands.keys()):
            if key not in target_keys:
                guild_id, name = key
                self.bot.tree.remove_command(name, guild=discord.Object(id=guild_id))
                self._dynamic_commands.pop(key, None)
                if sync:
                    try:
                        await self.bot.tree.sync(guild=discord.Object(id=guild_id))
                    except discord.HTTPException:
                        pass

        # Register missing commands
        for guild_id, name in sorted(target_keys):
            if (guild_id, name) not in self._dynamic_commands and self._is_valid_custom_command_name(name):
                await self._register_dynamic_command(guild_id, name, sync=sync)

    async def _register_dynamic_command(self, guild_id: int, name: str, sync: bool) -> None:
        async def dynamic_callback(interaction: discord.Interaction, command_name: str = name, command_guild: int = guild_id) -> None:
            if interaction.guild is None or interaction.guild.id != command_guild:
                await interaction.response.send_message('❌ Dieser Befehl ist nur auf dem passenden Server verfügbar.', ephemeral=True)
                return

            with self._conn() as conn:
                row = conn.execute(
                    '''
                    SELECT message_content
                    FROM text_messages
                    WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                    LIMIT 1
                    ''',
                    (interaction.guild.id, command_name),
                ).fetchone()

            if row is None:
                await interaction.response.send_message('❌ Dieses Text-Kommando wurde entfernt.', ephemeral=True)
                return

            await interaction.response.send_message(str(row['message_content']))

        command = app_commands.Command(
            name=name,
            description=f'Text-Kommando: {name}',
            callback=dynamic_callback,
        )
        self.bot.tree.add_command(command, guild=discord.Object(id=guild_id), override=True)
        self._dynamic_commands[(guild_id, name)] = command

        if sync:
            try:
                await self.bot.tree.sync(guild=discord.Object(id=guild_id))
            except discord.HTTPException:
                pass

    async def _remove_dynamic_command(self, guild_id: int, name: str) -> None:
        self.bot.tree.remove_command(name, guild=discord.Object(id=guild_id))
        self._dynamic_commands.pop((guild_id, name), None)
        try:
            await self.bot.tree.sync(guild=discord.Object(id=guild_id))
        except discord.HTTPException:
            pass

    async def _name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                '''
                SELECT title
                FROM text_messages
                WHERE guild_id = ?
                ORDER BY title COLLATE NOCASE ASC
                ''',
                (interaction.guild.id,),
            ).fetchall()
        names = [str(row['title']) for row in rows if current.lower() in str(row['title']).lower()]
        return [app_commands.Choice(name=name, value=name) for name in names[:25]]

    @text.command(name='create', description='Erstelle ein Text-Kommando')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(name='Kommando-Name (z. B. text_hallo)', content='Inhalt des Kommandos')
    async def create_text_command(self, interaction: discord.Interaction, name: str, content: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        normalized_name = name.strip().lower()
        if not self._is_valid_custom_command_name(normalized_name):
            await interaction.response.send_message(
                '❌ Ungültiger Name. Erlaubt: `a-z`, `0-9`, `_` (1-32 Zeichen).',
                ephemeral=True,
            )
            return

        message_content = content.strip()
        if not message_content:
            await interaction.response.send_message('❌ Inhalt darf nicht leer sein.', ephemeral=True)
            return

        with self._conn() as conn:
            existing = conn.execute(
                'SELECT 1 FROM text_messages WHERE guild_id = ? AND LOWER(title) = LOWER(?) LIMIT 1',
                (interaction.guild.id, normalized_name),
            ).fetchone()
            if existing is not None:
                await interaction.response.send_message('❌ Dieses Text-Kommando existiert bereits.', ephemeral=True)
                return

            conn.execute(
                'INSERT INTO text_messages (guild_id, title, message_content) VALUES (?, ?, ?)',
                (interaction.guild.id, normalized_name, message_content),
            )
            conn.commit()

        await self._register_dynamic_command(interaction.guild.id, normalized_name, sync=True)
        await interaction.response.send_message(f'✅ Text-Kommando `/{normalized_name}` erstellt.', ephemeral=True)

    @text.command(name='edit', description='Bearbeite ein Text-Kommando')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(name='Kommando-Name', content='Neuer Inhalt')
    @app_commands.autocomplete(name=_name_autocomplete)
    async def edit_text_command(self, interaction: discord.Interaction, name: str, content: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        normalized_name = name.strip().lower()
        new_content = content.strip()
        if not new_content:
            await interaction.response.send_message('❌ Inhalt darf nicht leer sein.', ephemeral=True)
            return

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE text_messages
                SET message_content = ?
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                ''',
                (new_content, interaction.guild.id, normalized_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                await interaction.response.send_message('❌ Text-Kommando nicht gefunden.', ephemeral=True)
                return

        await interaction.response.send_message(f'✅ Text-Kommando `/{normalized_name}` bearbeitet.', ephemeral=True)

    @text.command(name='delete', description='Lösche ein Text-Kommando')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(name='Kommando-Name')
    @app_commands.autocomplete(name=_name_autocomplete)
    async def delete_text_command(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        normalized_name = name.strip().lower()

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM text_messages WHERE guild_id = ? AND LOWER(title) = LOWER(?)',
                (interaction.guild.id, normalized_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                await interaction.response.send_message('❌ Text-Kommando nicht gefunden.', ephemeral=True)
                return

        await self._remove_dynamic_command(interaction.guild.id, normalized_name)
        await interaction.response.send_message(f'✅ Text-Kommando `/{normalized_name}` gelöscht.', ephemeral=True)

    @text.command(name='list', description='Liste alle Text-Kommandos')
    @app_commands.default_permissions(administrator=True)
    async def list_text_commands(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        with self._conn() as conn:
            rows = conn.execute(
                'SELECT title FROM text_messages WHERE guild_id = ? ORDER BY title COLLATE NOCASE ASC',
                (interaction.guild.id,),
            ).fetchall()

        if not rows:
            await interaction.response.send_message('ℹ️ Keine Text-Kommandos gefunden.', ephemeral=True)
            return

        description = '\n'.join(f'• `/{row["title"]}`' for row in rows)
        embed = discord.Embed(title='📝 Text-Kommandos', description=description[:4096], color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TextMessages(bot))
