from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

TEXT_XP_PER_MESSAGE = 1
VOICE_XP_PER_MINUTE = 1
TEXT_XP_COOLDOWN_SECONDS = 30
TOP_LIMIT = 10
LOG_EMBED_MAX_LINES = 60

MAGIC_8_BALL_ANSWERS = [
    'Ja, definitiv.',
    'Ja, ohne Zweifel.',
    'Sieht sehr gut aus.',
    'Die Chancen stehen gut.',
    'Eher ja.',
    'Frag später nochmal.',
    'Gerade unklar.',
    'Konzentriere dich und frag erneut.',
    'Vielleicht.',
    'Eher nicht.',
    'Ich glaube nicht.',
    'Nein.',
    'Auf keinen Fall.',
]

PUBLIC_COMMAND_EXPLANATIONS_DEFAULTS = [
    ('/geburtstag', 'Trage einen Geburtstag ein'),
    ('/würfel [seiten]', 'Würfle einen Würfel mit der angegebenen Anzahl von Seiten'),
    ('/8ball', 'Stelle eine Frage und erhalte eine mystische deutsche Antwort'),
    ('/top', 'Zeige die Top 10 der aktivsten Nutzer in Text- und Sprachchat an'),
]

ADMIN_COMMAND_EXPLANATIONS_DEFAULTS = [
    ('/geburtstag_entfernen', 'Entferne einen Geburtstag aus der Liste'),
    ('/geburtstagsliste', 'Zeige die Geburtstagsliste an und erstelle/aktualisiere sie im aktuellen Channel'),
    ('/geburtstagsrolle', 'Setze die Rolle, die Geburtstagskinder erhalten'),
    ('/geburtstag_check', 'Prüfe manuell, ob heute Geburtstage anstehen'),
    ('/reminder', 'Erstelle einen Reminder, der täglich zur angegebenen Zeit gesendet wird'),
    ('/reminder_edit', 'Bearbeite einen bestehenden Reminder'),
    ('/reminder_remove', 'Lösche einen bestehenden Reminder'),
    ('/role', 'Erstelle ein neues Rollenauswahlpanel'),
    ('/role_edit', 'Bearbeite ein bestehendes Rollenauswahlpanel'),
    ('/role_remove', 'Lösche ein bestehendes Rollenauswahlpanel'),
    ('/welcome', 'Erstelle ein Welcome-Setup für neue Servermitglieder'),
    ('/welcome_edit', 'Bearbeite ein bestehendes Welcome-Setup'),
    ('/welcome_remove', 'Lösche ein Welcome-Setup'),
    ('/moveall', 'Verschiebe alle User aus deinem aktuellen Voice-Channel in einen anderen'),
    ('/reload', 'Lade Cogs neu, synchronisiere Befehle und starte Birthday-Tasks neu'),
    ('/erklärung_edit', 'Bearbeite die Beschreibung eines öffentlichen Befehls'),
    ('/erklärung_remove', 'Lösche einen öffentlichen Befehl aus der Liste'),
    ('/erklärungadmin', 'Zeige die Erklärung für einen Admin-Befehl an'),
    ('/erklärungadmin_liste', 'Zeige die komplette Liste aller Admin-Befehle an'),
    ('/erklärungadmin_edit', 'Bearbeite die Beschreibung eines Admin-Befehls'),
    ('/erklärungadmin_remove', 'Lösche einen Admin-Befehl aus der Liste'),
    ('/log', 'Füge einen manuellen Eintrag zum Admin-Log hinzu'),
    ('/log_liste', 'Zeige alle Log-Einträge an'),
    ('/log_edit', 'Bearbeite einen Log-Eintrag'),
    ('/log_remove', 'Lösche einen Log-Eintrag'),
]

AUTOCOMPLETE_LIMIT = 25
EMBED_DESCRIPTION_LIMIT = 4000

LOGGER = logging.getLogger(__name__)


class FunAndUtility(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.voice_sessions: dict[tuple[int, int], datetime] = {}

    async def cog_load(self) -> None:
        await asyncio.to_thread(self._seed_explanation_defaults)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _parse_timestamp(raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _format_log_line(position: int, person: str, description: str, created_at: str) -> str:
        timestamp = created_at
        try:
            parsed = datetime.fromisoformat(created_at.replace(' ', 'T'))
            timestamp = parsed.strftime('%d.%m.%Y %H:%M')
        except ValueError:
            pass
        return f'#{position} [{person}] - {description} [{timestamp}]'

    @staticmethod
    def _ensure_user_xp_row(conn: sqlite3.Connection, guild_id: int, user_id: int) -> None:
        conn.execute(
            '''
            INSERT INTO user_xp (guild_id, user_id, text_xp, voice_xp, last_text_xp_at)
            VALUES (?, ?, 0, 0, NULL)
            ON CONFLICT(guild_id, user_id) DO NOTHING
            ''',
            (guild_id, user_id),
        )

    async def _resolve_member_name(self, guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        return member.mention if member else f'<@{user_id}>'

    async def _award_voice_xp(self, guild_id: int, user_id: int, joined_at: datetime, left_at: datetime) -> int:
        elapsed_seconds = int((left_at - joined_at).total_seconds())
        if elapsed_seconds < 60:
            return 0
        gained = (elapsed_seconds // 60) * VOICE_XP_PER_MINUTE
        with sqlite3.connect(DB_FILE) as conn:
            self._ensure_user_xp_row(conn, guild_id, user_id)
            conn.execute(
                '''
                UPDATE user_xp
                SET voice_xp = voice_xp + ?
                WHERE guild_id = ? AND user_id = ?
                ''',
                (gained, guild_id, user_id),
            )
            conn.commit()
        return gained

    async def _build_top_lines(self, guild: discord.Guild, rows: list[sqlite3.Row], xp_column: str) -> str:
        if not rows:
            return 'Noch keine Daten.'
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            member_name = await self._resolve_member_name(guild, int(row['user_id']))
            lines.append(f'`#{index}` {member_name} — **{int(row[xp_column])} XP**')
        return '\n'.join(lines)

    @staticmethod
    def _rank_line(rank: int | None, xp: int) -> str:
        if rank is None:
            return f'Nicht gerankt — **{xp} XP**'
        return f'`#{rank}` — **{xp} XP**'

    @staticmethod
    def _normalize_command_name(command: str) -> str:
        normalized = command.strip().lower()
        if not normalized:
            return ''
        return normalized if normalized.startswith('/') else f'/{normalized}'

    def _seed_explanation_defaults(self) -> None:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                count_row = conn.execute(
                    '''
                    SELECT
                        (SELECT COUNT(*) FROM public_command_explanations) AS public_count,
                        (SELECT COUNT(*) FROM admin_command_explanations) AS admin_count
                    '''
                ).fetchone()
                if count_row is None:
                    LOGGER.warning(
                        'Konnte Erklärungstabellen nicht auslesen. '
                        'Der Bot läuft weiter ohne erneutes Default-Seeding.'
                    )
                    return
                public_count = int(count_row[0])
                admin_count = int(count_row[1])
                if public_count == 0:
                    conn.executemany(
                        '''
                        INSERT INTO public_command_explanations (command, description)
                        VALUES (?, ?)
                        ''',
                        PUBLIC_COMMAND_EXPLANATIONS_DEFAULTS,
                    )
                if admin_count == 0:
                    conn.executemany(
                        '''
                        INSERT INTO admin_command_explanations (command, description)
                        VALUES (?, ?)
                        ''',
                        ADMIN_COMMAND_EXPLANATIONS_DEFAULTS,
                    )
                conn.commit()
        except sqlite3.Error as exc:
            LOGGER.warning(
                'Konnte Standard-Erklärungen nicht initialisieren. '
                'Der Bot läuft weiter, aber /erklärung-Listen können unvollständig sein: %s',
                exc,
            )
            return

    @staticmethod
    async def _require_admin(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return False
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not member.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return False
        return True

    async def _command_autocomplete(
        self,
        table_name: str,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        query_by_table = {
            'public_command_explanations': '''
                SELECT command
                FROM public_command_explanations
                WHERE command LIKE ?
                ORDER BY command ASC
                LIMIT ?
            ''',
            'admin_command_explanations': '''
                SELECT command
                FROM admin_command_explanations
                WHERE command LIKE ?
                ORDER BY command ASC
                LIMIT ?
            ''',
        }
        query = query_by_table.get(table_name)
        if query is None:
            return []
        normalized = self._normalize_command_name(current) if current.strip() else ''
        like_pattern = f'{normalized}%' if normalized else '%'
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    query,
                    (like_pattern, AUTOCOMPLETE_LIMIT),
                ).fetchall()
            return [app_commands.Choice(name=str(row['command']), value=str(row['command'])) for row in rows]
        except sqlite3.Error:
            return []

    @staticmethod
    def _build_explanation_description(rows: list[sqlite3.Row]) -> str:
        if not rows:
            return 'Keine Einträge vorhanden.'
        lines = [f"**{str(row['command'])}** - {str(row['description'])}" for row in rows]
        description = '\n'.join(lines)
        if len(description) <= EMBED_DESCRIPTION_LIMIT:
            return description
        return f'{description[:EMBED_DESCRIPTION_LIMIT - 3]}...'

    async def _build_top_embed(self, interaction: discord.Interaction) -> discord.Embed:
        assert interaction.guild is not None
        requester_id = interaction.user.id
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            text_rows = conn.execute(
                '''
                SELECT user_id, text_xp
                FROM user_xp
                WHERE guild_id = ? AND text_xp > 0
                ORDER BY text_xp DESC, user_id ASC
                LIMIT ?
                ''',
                (interaction.guild.id, TOP_LIMIT),
            ).fetchall()
            voice_rows = conn.execute(
                '''
                SELECT user_id, voice_xp
                FROM user_xp
                WHERE guild_id = ? AND voice_xp > 0
                ORDER BY voice_xp DESC, user_id ASC
                LIMIT ?
                ''',
                (interaction.guild.id, TOP_LIMIT),
            ).fetchall()
            own_row = conn.execute(
                '''
                SELECT text_xp, voice_xp
                FROM user_xp
                WHERE guild_id = ? AND user_id = ?
                LIMIT 1
                ''',
                (interaction.guild.id, requester_id),
            ).fetchone()

            own_text_xp = int(own_row['text_xp']) if own_row is not None else 0
            own_voice_xp = int(own_row['voice_xp']) if own_row is not None else 0
            text_rank: int | None = None
            voice_rank: int | None = None

            if own_text_xp > 0:
                text_rank = int(
                    conn.execute(
                        '''
                        SELECT COUNT(*)
                        FROM user_xp
                        WHERE guild_id = ? AND text_xp > ?
                        ''',
                        (interaction.guild.id, own_text_xp),
                    ).fetchone()[0]
                ) + 1
            if own_voice_xp > 0:
                voice_rank = int(
                    conn.execute(
                        '''
                        SELECT COUNT(*)
                        FROM user_xp
                        WHERE guild_id = ? AND voice_xp > ?
                        ''',
                        (interaction.guild.id, own_voice_xp),
                    ).fetchone()[0]
                ) + 1

        embed = discord.Embed(
            title='🏆 XP Leaderboard',
            color=discord.Colour.orange(),
        )
        embed.add_field(
            name='💬 Top 10 Text Chat',
            value=await self._build_top_lines(interaction.guild, text_rows, 'text_xp'),
            inline=False,
        )
        embed.add_field(
            name='🎙️ Top 10 Voice Chat',
            value=await self._build_top_lines(interaction.guild, voice_rows, 'voice_xp'),
            inline=False,
        )
        embed.add_field(
            name='Dein Text-Rang',
            value=self._rank_line(text_rank, own_text_xp),
            inline=False,
        )
        embed.add_field(
            name='Dein Voice-Rang',
            value=self._rank_line(voice_rank, own_voice_xp),
            inline=False,
        )
        return embed

    async def _post_log_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT person, description, created_at
                FROM admin_logs
                WHERE guild_id = ?
                ORDER BY id ASC
                ''',
                (interaction.guild.id,),
            ).fetchall()

        if rows:
            lines = [
                self._format_log_line(
                    position=index,
                    person=str(row['person']),
                    description=str(row['description']),
                    created_at=str(row['created_at']),
                )
                for index, row in enumerate(rows, start=1)
            ]
            if len(lines) > LOG_EMBED_MAX_LINES:
                hidden = len(lines) - LOG_EMBED_MAX_LINES
                lines = lines[-LOG_EMBED_MAX_LINES:]
                lines.insert(0, f'… {hidden} ältere Einträge ausgeblendet …')
            description = '\n'.join(lines)
        else:
            description = 'Noch keine Admin-Logs vorhanden.'

        embed = discord.Embed(
            title='📕 Admin Log Liste',
            description=description,
            color=discord.Colour.red(),
        )
        await interaction.channel.send(embed=embed)

    @app_commands.command(name='würfel', description='Würfle einen Würfel mit einer bestimmten Seitenzahl')
    @app_commands.describe(seiten='Anzahl der Seiten des Würfels (z. B. 20)')
    async def dice_command(self, interaction: discord.Interaction, seiten: app_commands.Range[int, 2, 1000]) -> None:
        result = random.randint(1, seiten)
        embed = discord.Embed(
            title='🎲 Würfelwurf',
            description=f'Du hast einen **{seiten}-seitigen** Würfel geworfen!\n\n🎉 Ergebnis: **{result}**',
            color=discord.Colour.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='8ball', description='Stelle der magischen 8-Ball eine Frage')
    @app_commands.describe(frage='Deine Frage an die magische 8-Ball')
    async def eight_ball_command(self, interaction: discord.Interaction, frage: str) -> None:
        clean_question = frage.strip()
        if not clean_question:
            await interaction.response.send_message('❌ Bitte stelle eine Frage.', ephemeral=True)
            return

        answer = random.choice(MAGIC_8_BALL_ANSWERS)
        embed = discord.Embed(
            title='🎱 Magische 8-Ball',
            color=discord.Colour.blurple(),
        )
        embed.add_field(name='❓ Frage', value=clean_question, inline=False)
        embed.add_field(name='🔮 Antwort', value=answer, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='top', description='Zeigt die Top 10 Text- und Voice-XP')
    async def top_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        embed = await self._build_top_embed(interaction)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='erklärung', description='Zeige die Erklärung für einen öffentlichen Befehl')
    @app_commands.describe(befehl='Öffentlicher Befehl, z. B. /geburtstag')
    async def erklaerung_command(self, interaction: discord.Interaction, befehl: str) -> None:
        normalized_command = self._normalize_command_name(befehl)
        if not normalized_command:
            await interaction.response.send_message('❌ Bitte gib einen Befehl an.', ephemeral=True)
            return
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    '''
                    SELECT command, description
                    FROM public_command_explanations
                    WHERE command = ? OR command LIKE ?
                    ORDER BY command ASC
                    LIMIT 1
                    ''',
                    (normalized_command, f'{normalized_command} %'),
                ).fetchone()
            if row is None:
                await interaction.response.send_message(
                    '❌ Kein öffentlicher Befehl mit dieser Bezeichnung gefunden.',
                    ephemeral=True,
                )
                return
            embed = discord.Embed(
                title=f"🟢 Erklärung für {str(row['command'])}",
                description=str(row['description']),
                color=discord.Colour.green(),
            )
            await interaction.response.send_message(embed=embed)
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Laden der Erklärung.', ephemeral=True)

    @app_commands.command(name='erklärung_liste', description='Zeige alle öffentlichen Befehle mit Erklärung')
    async def erklaerung_liste_command(self, interaction: discord.Interaction) -> None:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    '''
                    SELECT command, description
                    FROM public_command_explanations
                    ORDER BY command ASC
                    '''
                ).fetchall()
            embed = discord.Embed(
                title='🟢 Öffentliche Befehle',
                description=self._build_explanation_description(rows),
                color=discord.Colour.green(),
            )
            await interaction.response.send_message(embed=embed)
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Laden der Liste.', ephemeral=True)

    @app_commands.command(name='erklärung_edit', description='Bearbeite die Beschreibung eines öffentlichen Befehls')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(befehl='Öffentlicher Befehl', beschreibung='Neue Beschreibung')
    async def erklaerung_edit_command(self, interaction: discord.Interaction, befehl: str, beschreibung: str) -> None:
        if not await self._require_admin(interaction):
            return
        normalized_command = self._normalize_command_name(befehl)
        clean_description = beschreibung.strip()
        if not normalized_command:
            await interaction.response.send_message('❌ Bitte gib einen Befehl an.', ephemeral=True)
            return
        if not clean_description:
            await interaction.response.send_message('❌ Beschreibung darf nicht leer sein.', ephemeral=True)
            return

        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.execute(
                    '''
                    UPDATE public_command_explanations
                    SET description = ?
                    WHERE command = ?
                    ''',
                    (clean_description, normalized_command),
                )
                conn.commit()
            if cursor.rowcount <= 0:
                await interaction.response.send_message('❌ Befehl nicht gefunden.', ephemeral=True)
                return
            await interaction.response.send_message(
                f'✅ Beschreibung für {normalized_command} wurde aktualisiert.',
                ephemeral=True,
            )
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Bearbeiten.', ephemeral=True)

    @app_commands.command(name='erklärung_remove', description='Lösche einen öffentlichen Befehl aus der Liste')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(befehl='Öffentlicher Befehl')
    async def erklaerung_remove_command(self, interaction: discord.Interaction, befehl: str) -> None:
        if not await self._require_admin(interaction):
            return
        normalized_command = self._normalize_command_name(befehl)
        if not normalized_command:
            await interaction.response.send_message('❌ Bitte gib einen Befehl an.', ephemeral=True)
            return
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.execute(
                    'DELETE FROM public_command_explanations WHERE command = ?',
                    (normalized_command,),
                )
                conn.commit()
            if cursor.rowcount <= 0:
                await interaction.response.send_message('❌ Befehl nicht gefunden.', ephemeral=True)
                return
            await interaction.response.send_message(
                f'✅ {normalized_command} wurde aus der öffentlichen Liste entfernt.',
                ephemeral=True,
            )
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Entfernen.', ephemeral=True)

    @app_commands.command(name='erklärungadmin', description='Zeige die Erklärung für einen Admin-Befehl')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(befehl='Admin-Befehl, z. B. /reload')
    async def erklaerung_admin_command(self, interaction: discord.Interaction, befehl: str) -> None:
        if not await self._require_admin(interaction):
            return
        normalized_command = self._normalize_command_name(befehl)
        if not normalized_command:
            await interaction.response.send_message('❌ Bitte gib einen Befehl an.', ephemeral=True)
            return
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    '''
                    SELECT command, description
                    FROM admin_command_explanations
                    WHERE command = ? OR command LIKE ?
                    ORDER BY command ASC
                    LIMIT 1
                    ''',
                    (normalized_command, f'{normalized_command} %'),
                ).fetchone()
            if row is None:
                await interaction.response.send_message('❌ Kein Admin-Befehl mit dieser Bezeichnung gefunden.', ephemeral=True)
                return
            embed = discord.Embed(
                title=f"🔴 Erklärung für {str(row['command'])}",
                description=str(row['description']),
                color=discord.Colour.red(),
            )
            await interaction.response.send_message(embed=embed)
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Laden der Erklärung.', ephemeral=True)

    @app_commands.command(name='erklärungadmin_liste', description='Zeige alle Admin-Befehle mit Erklärung')
    @app_commands.default_permissions(administrator=True)
    async def erklaerung_admin_liste_command(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    '''
                    SELECT command, description
                    FROM admin_command_explanations
                    ORDER BY command ASC
                    '''
                ).fetchall()
            embed = discord.Embed(
                title='🔴 Admin-Befehle',
                description=self._build_explanation_description(rows),
                color=discord.Colour.red(),
            )
            await interaction.response.send_message(embed=embed)
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Laden der Liste.', ephemeral=True)

    @app_commands.command(name='erklärungadmin_edit', description='Bearbeite die Beschreibung eines Admin-Befehls')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(befehl='Admin-Befehl', beschreibung='Neue Beschreibung')
    async def erklaerung_admin_edit_command(
        self,
        interaction: discord.Interaction,
        befehl: str,
        beschreibung: str,
    ) -> None:
        if not await self._require_admin(interaction):
            return
        normalized_command = self._normalize_command_name(befehl)
        clean_description = beschreibung.strip()
        if not normalized_command:
            await interaction.response.send_message('❌ Bitte gib einen Befehl an.', ephemeral=True)
            return
        if not clean_description:
            await interaction.response.send_message('❌ Beschreibung darf nicht leer sein.', ephemeral=True)
            return

        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.execute(
                    '''
                    UPDATE admin_command_explanations
                    SET description = ?
                    WHERE command = ?
                    ''',
                    (clean_description, normalized_command),
                )
                conn.commit()
            if cursor.rowcount <= 0:
                await interaction.response.send_message('❌ Befehl nicht gefunden.', ephemeral=True)
                return
            await interaction.response.send_message(
                f'✅ Beschreibung für {normalized_command} wurde aktualisiert.',
                ephemeral=True,
            )
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Bearbeiten.', ephemeral=True)

    @app_commands.command(name='erklärungadmin_remove', description='Lösche einen Admin-Befehl aus der Liste')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(befehl='Admin-Befehl')
    async def erklaerung_admin_remove_command(self, interaction: discord.Interaction, befehl: str) -> None:
        if not await self._require_admin(interaction):
            return
        normalized_command = self._normalize_command_name(befehl)
        if not normalized_command:
            await interaction.response.send_message('❌ Bitte gib einen Befehl an.', ephemeral=True)
            return
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.execute(
                    'DELETE FROM admin_command_explanations WHERE command = ?',
                    (normalized_command,),
                )
                conn.commit()
            if cursor.rowcount <= 0:
                await interaction.response.send_message('❌ Befehl nicht gefunden.', ephemeral=True)
                return
            await interaction.response.send_message(
                f'✅ {normalized_command} wurde aus der Admin-Liste entfernt.',
                ephemeral=True,
            )
        except sqlite3.Error:
            await interaction.response.send_message('❌ Datenbankfehler beim Entfernen.', ephemeral=True)

    @erklaerung_command.autocomplete('befehl')
    async def erklaerung_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._command_autocomplete('public_command_explanations', current)

    @erklaerung_edit_command.autocomplete('befehl')
    async def erklaerung_edit_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._command_autocomplete('public_command_explanations', current)

    @erklaerung_remove_command.autocomplete('befehl')
    async def erklaerung_remove_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._command_autocomplete('public_command_explanations', current)

    @erklaerung_admin_command.autocomplete('befehl')
    async def erklaerung_admin_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._command_autocomplete('admin_command_explanations', current)

    @erklaerung_admin_edit_command.autocomplete('befehl')
    async def erklaerung_admin_edit_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._command_autocomplete('admin_command_explanations', current)

    @erklaerung_admin_remove_command.autocomplete('befehl')
    async def erklaerung_admin_remove_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._command_autocomplete('admin_command_explanations', current)

    @app_commands.command(name='log_liste', description='Zeige die Admin-Log-Liste in diesem Channel')
    @app_commands.default_permissions(administrator=True)
    async def log_list_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return
        if interaction.channel is None:
            await interaction.response.send_message('❌ Channel konnte nicht ermittelt werden.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self._post_log_list(interaction)
        await interaction.followup.send('✅ Log-Liste wurde in diesem Channel gepostet.', ephemeral=True)

    @app_commands.command(name='log', description='Füge einen Admin-Logeintrag hinzu')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(person='Person/Name des Eintrags', beschreibung='Beschreibung des Logs')
    async def log_add_command(self, interaction: discord.Interaction, person: str, beschreibung: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return
        clean_person = person.strip()
        clean_description = beschreibung.strip()
        if not clean_person:
            await interaction.response.send_message('❌ Person darf nicht leer sein.', ephemeral=True)
            return
        if not clean_description:
            await interaction.response.send_message('❌ Beschreibung darf nicht leer sein.', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                '''
                INSERT INTO admin_logs (guild_id, author_id, person, description)
                VALUES (?, ?, ?, ?)
                ''',
                (interaction.guild.id, interaction.user.id, clean_person, clean_description),
            )
            conn.commit()
        await interaction.response.send_message('✅ Logeintrag wurde gespeichert.', ephemeral=True)

    @app_commands.command(name='log_edit', description='Bearbeite einen Admin-Logeintrag')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(eintrag_nummer='Nummer aus /log_liste', neue_beschreibung='Neue Beschreibung')
    async def log_edit_command(
        self,
        interaction: discord.Interaction,
        eintrag_nummer: app_commands.Range[int, 1, 99999],
        neue_beschreibung: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return
        clean_description = neue_beschreibung.strip()
        if not clean_description:
            await interaction.response.send_message('❌ Neue Beschreibung darf nicht leer sein.', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                '''
                SELECT id
                FROM admin_logs
                WHERE guild_id = ?
                ORDER BY id ASC
                LIMIT 1 OFFSET ?
                ''',
                (interaction.guild.id, eintrag_nummer - 1),
            ).fetchone()
            if row is None:
                await interaction.response.send_message('❌ Eintrag nicht gefunden.', ephemeral=True)
                return

            conn.execute(
                '''
                UPDATE admin_logs
                SET description = ?
                WHERE id = ?
                ''',
                (clean_description, row['id']),
            )
            conn.commit()

        await interaction.response.send_message(f'✅ Logeintrag #{eintrag_nummer} wurde aktualisiert.', ephemeral=True)

    @app_commands.command(name='log_remove', description='Entferne einen Admin-Logeintrag')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(eintrag_nummer='Nummer aus /log_liste')
    async def log_remove_command(
        self,
        interaction: discord.Interaction,
        eintrag_nummer: app_commands.Range[int, 1, 99999],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                '''
                SELECT id
                FROM admin_logs
                WHERE guild_id = ?
                ORDER BY id ASC
                LIMIT 1 OFFSET ?
                ''',
                (interaction.guild.id, eintrag_nummer - 1),
            ).fetchone()
            if row is None:
                await interaction.response.send_message('❌ Eintrag nicht gefunden.', ephemeral=True)
                return

            conn.execute('DELETE FROM admin_logs WHERE id = ?', (row['id'],))
            conn.commit()

        await interaction.response.send_message(f'✅ Logeintrag #{eintrag_nummer} wurde entfernt.', ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            for voice_channel in guild.voice_channels:
                for member in voice_channel.members:
                    if member.bot:
                        continue
                    self.voice_sessions[(guild.id, member.id)] = self._utc_now()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return

        now = self._utc_now()
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            self._ensure_user_xp_row(conn, message.guild.id, message.author.id)
            row = conn.execute(
                '''
                SELECT last_text_xp_at
                FROM user_xp
                WHERE guild_id = ? AND user_id = ?
                LIMIT 1
                ''',
                (message.guild.id, message.author.id),
            ).fetchone()
            raw_last_text_xp_at = None if row is None else row['last_text_xp_at']
            last_award_time = self._parse_timestamp(
                None if raw_last_text_xp_at is None else str(raw_last_text_xp_at)
            )
            can_award = (
                last_award_time is None
                or int((now - last_award_time).total_seconds()) >= TEXT_XP_COOLDOWN_SECONDS
            )
            if can_award:
                conn.execute(
                    '''
                    UPDATE user_xp
                    SET text_xp = text_xp + ?, last_text_xp_at = ?
                    WHERE guild_id = ? AND user_id = ?
                    ''',
                    (TEXT_XP_PER_MESSAGE, now.isoformat(), message.guild.id, message.author.id),
                )
                conn.commit()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        session_key = (member.guild.id, member.id)
        now = self._utc_now()

        if before.channel is None and after.channel is not None:
            self.voice_sessions[session_key] = now
            return

        if before.channel is not None and after.channel is None:
            joined_at = self.voice_sessions.pop(session_key, None)
            if joined_at is not None:
                await self._award_voice_xp(member.guild.id, member.id, joined_at, now)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunAndUtility(bot))
