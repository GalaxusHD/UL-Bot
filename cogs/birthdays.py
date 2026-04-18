import os
import sqlite3
from hashlib import sha256
from datetime import date, datetime

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

from database import DB_FILE

DEFAULT_TIMEZONE = 'Europe/Berlin'
MIN_BIRTH_YEAR = 1900
ANNOUNCE_HOUR = 0
ANNOUNCE_MINUTE = 0
CLEANUP_HOUR = 23
CLEANUP_MINUTE = 59
MONTH_NAMES = {
    1: 'Januar',
    2: 'Februar',
    3: 'März',
    4: 'April',
    5: 'Mai',
    6: 'Juni',
    7: 'Juli',
    8: 'August',
    9: 'September',
    10: 'Oktober',
    11: 'November',
    12: 'Dezember',
}
MAX_STORAGE_ID_ATTEMPTS = 100


class BirthdayModal(discord.ui.Modal, title='Geburtstag eintragen'):
    def __init__(self, cog: 'Birthdays', target_user_id: int, target_username: str) -> None:
        super().__init__()
        self.cog = cog
        self.target_user_id = target_user_id
        self.target_username = target_username
        self.real_name = discord.ui.TextInput(
            label='Optional echter Name',
            required=False,
            placeholder='Max Mustermann',
            max_length=100,
        )
        self.day = discord.ui.TextInput(label='Tag (1-31)', placeholder='1', max_length=2)
        self.month = discord.ui.TextInput(label='Monat (1-12)', placeholder='1', max_length=2)
        self.year = discord.ui.TextInput(label='Jahr (optional)', required=False, placeholder='2000', max_length=4)
        self.add_item(self.real_name)
        self.add_item(self.day)
        self.add_item(self.month)
        self.add_item(self.year)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        real_name = str(self.real_name.value).strip() or None

        try:
            day = int(str(self.day.value).strip())
            month = int(str(self.month.value).strip())
            datetime(2000, month, day)
        except (TypeError, ValueError):
            await interaction.response.send_message('❌ Ungültiges Datum.', ephemeral=True)
            return

        year_text = str(self.year.value).strip()
        parsed_year: int | None = None
        if year_text:
            try:
                parsed_year = int(year_text)
                today = datetime.now(self.cog.timezone).date()
                current_year = today.year
                if parsed_year < MIN_BIRTH_YEAR or parsed_year > current_year:
                    raise ValueError
                parsed_date = datetime(parsed_year, month, day).date()
                if parsed_date > today:
                    raise ValueError
            except (TypeError, ValueError):
                await interaction.response.send_message('❌ Ungültiges Jahr.', ephemeral=True)
                return

        self.cog.upsert_birthday(
            guild_id=interaction.guild.id,
            user_id=self.target_user_id,
            username=self.target_username,
            real_name=real_name,
            day=day,
            month=month,
            year=parsed_year,
        )

        await self.cog.refresh_birthday_list(interaction.guild)
        await interaction.response.send_message('✅ Geburtstag wurde gespeichert und die Liste aktualisiert.', ephemeral=True)


class Birthdays(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.timezone = pytz.timezone(os.getenv('BIRTHDAY_TIMEZONE', DEFAULT_TIMEZONE))

    @staticmethod
    def _conn() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

    def cog_unload(self) -> None:
        if self.daily_scheduler.is_running():
            self.daily_scheduler.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.daily_scheduler.is_running():
            self.daily_scheduler.start()

    @app_commands.command(name='geburtstag', description='Trage einen Geburtstag ein')
    @app_commands.describe(user='Optional: Benutzer (nur Admins)')
    async def geburtstag(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        if user is not None and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        target_user = user or interaction.user
        target_username = f'@{target_user.name}'
        await interaction.response.send_modal(
            BirthdayModal(cog=self, target_user_id=target_user.id, target_username=target_username)
        )

    @app_commands.command(name='geburtstag_remove', description='Entferne einen Geburtstag aus der Liste')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user='Der Benutzer zum Entfernen')
    async def remove_birthday(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        with self._conn() as conn:
            cursor = conn.execute(
                'DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?',
                (interaction.guild.id, user.id),
            )
            conn.commit()

        if cursor.rowcount <= 0:
            await interaction.response.send_message('❌ Kein passender Geburtstag gefunden.', ephemeral=True)
            return

        await self.refresh_birthday_list(interaction.guild)
        await interaction.response.send_message(f'✅ Geburtstag für {user.mention} entfernt.', ephemeral=True)

    @app_commands.command(name='geburtstag_liste', description='Zeige die Geburtstagsliste')
    @app_commands.default_permissions(administrator=True)
    async def geburtstag_liste(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        embed = self.build_birthday_embed(interaction.guild)
        message = await interaction.channel.send(embed=embed) if interaction.channel else None

        with self._conn() as conn:
            conn.execute(
                '''
                INSERT INTO birthday_settings (guild_id, list_channel_id, list_message_id)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    list_channel_id = excluded.list_channel_id,
                    list_message_id = excluded.list_message_id
                ''',
                (
                    interaction.guild.id,
                    interaction.channel.id if interaction.channel else None,
                    message.id if message else None,
                ),
            )
            conn.commit()

        await interaction.response.send_message('✅ Geburtstagsliste wurde erstellt/aktualisiert.', ephemeral=True)

    @app_commands.command(name='geburtstag_rolle', description='Setze die Geburtstagsrolle')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(role='Rolle für Geburtstagskinder')
    async def geburtstag_rolle(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        with self._conn() as conn:
            conn.execute(
                '''
                INSERT INTO birthday_settings (guild_id, role_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET role_id = excluded.role_id
                ''',
                (interaction.guild.id, role.id),
            )
            conn.commit()

        await interaction.response.send_message(f'✅ Geburtstagsrolle gesetzt: {role.mention}', ephemeral=True)

    @app_commands.command(name='geburtstag_check', description='Prüfe manuell, ob heute Geburtstage anstehen')
    @app_commands.default_permissions(administrator=True)
    async def geburtstag_check(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        now = datetime.now(self.timezone)
        day_key = now.strftime('%Y-%m-%d')

        with self._conn() as conn:
            settings = conn.execute(
                '''
                SELECT role_id, list_channel_id, last_announce_date
                FROM birthday_settings
                WHERE guild_id = ?
                LIMIT 1
                ''',
                (interaction.guild.id,),
            ).fetchone()
            rows = conn.execute(
                'SELECT user_id FROM birthdays WHERE guild_id = ? AND day = ? AND month = ?',
                (interaction.guild.id, now.day, now.month),
            ).fetchall()

        if settings is None or settings['list_channel_id'] is None:
            await interaction.response.send_message(
                '❌ Keine Geburtstagsliste eingerichtet. Nutze zuerst /geburtstag_liste.',
                ephemeral=True,
            )
            return

        if not rows:
            await interaction.response.send_message('ℹ️ Heute hat niemand Geburtstag.', ephemeral=True)
            return

        if settings['last_announce_date'] == day_key:
            await interaction.response.send_message('ℹ️ Geburtstagsnachricht wurde heute bereits gesendet.', ephemeral=True)
            return

        role_id = int(settings['role_id']) if settings['role_id'] else None
        await interaction.response.defer(ephemeral=True)
        announced = await self._announce_birthdays(interaction.guild, role_id, settings, day_key)
        if announced:
            await interaction.followup.send('✅ Geburtstagscheck durchgeführt und Nachricht gesendet.', ephemeral=True)
        else:
            await interaction.followup.send(
                '❌ Es konnten keine Geburtstage angekündigt werden (Liste/Channel prüfen).',
                ephemeral=True,
            )

    def upsert_birthday(
        self,
        guild_id: int,
        user_id: int,
        username: str,
        real_name: str | None,
        day: int,
        month: int,
        year: int | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                '''
                INSERT INTO birthdays (guild_id, user_id, username, real_name, day, month, year)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    real_name = excluded.real_name,
                    day = excluded.day,
                    month = excluded.month,
                    year = excluded.year
                ''',
                (guild_id, user_id, username, real_name, day, month, year),
            )
            conn.commit()

    @staticmethod
    def _username_key(username: str) -> str:
        return username.strip().lstrip('@').casefold()

    def _find_user_id_by_username(self, guild_id: int, username: str) -> int | None:
        username_key = self._username_key(username)
        if not username_key:
            return None

        normalized_input = username.strip()
        with self._conn() as conn:
            row = conn.execute(
                '''
                SELECT user_id, username
                FROM birthdays
                WHERE guild_id = ? AND lower(ltrim(trim(username), "@")) = lower(ltrim(trim(?), "@"))
                LIMIT 1
                ''',
                (guild_id, normalized_input),
            ).fetchone()
        if row is None:
            return None
        if self._username_key(str(row['username'])) != username_key:
            return None
        return int(row['user_id'])

    def make_storage_user_id(self, guild_id: int, username: str) -> int:
        existing_user_id = self._find_user_id_by_username(guild_id=guild_id, username=username)
        if existing_user_id is not None:
            return existing_user_id

        username_key = self._username_key(username)
        with self._conn() as conn:
            for attempt in range(MAX_STORAGE_ID_ATTEMPTS):
                digest = sha256(f'{guild_id}:{username_key}:{attempt}'.encode('utf-8')).digest()
                # 62-bit mask keeps the synthetic ID safely within SQLite signed INTEGER range after negation.
                raw_value = int.from_bytes(digest[:8], byteorder='big', signed=False) & ((1 << 62) - 1)
                synthetic_user_id = -max(1, raw_value)
                row = conn.execute(
                    'SELECT user_id FROM birthdays WHERE guild_id = ? AND user_id = ? LIMIT 1',
                    (guild_id, synthetic_user_id),
                ).fetchone()
                if row is None:
                    return synthetic_user_id

        raise RuntimeError(
            f'Konnte keine eindeutige Storage-ID für den Benutzernamen {username} in Guild {guild_id} erzeugen.'
        )

    @staticmethod
    def _calculate_correct_age(birth_day: int, birth_month: int, birth_year: int, today: date) -> int:
        age = today.year - birth_year
        if (today.month, today.day) < (birth_month, birth_day):
            age -= 1
        return max(age, 0)

    def build_birthday_embed(self, guild: discord.Guild) -> discord.Embed:
        with self._conn() as conn:
            rows = conn.execute(
                '''
                SELECT user_id, username, real_name, day, month, year
                FROM birthdays
                WHERE guild_id = ?
                ORDER BY month ASC, day ASC, COALESCE(real_name, username) COLLATE NOCASE ASC
                ''',
                (guild.id,),
            ).fetchall()

        if not rows:
            description = 'Keine Geburtstage eingetragen.'
        else:
            lines = []
            today = datetime.now(self.timezone).date()
            month_entries: dict[int, list[str]] = {month: [] for month in range(1, 13)}
            for row in rows:
                username = str(row['username'])
                real_name = str(row['real_name']) if row['real_name'] else None
                day = int(row['day'])
                month = int(row['month'])
                year = int(row['year']) if row['year'] is not None else None
                display_name = username if username.startswith('@') else f'@{username}'

                date_text = f'{day:02d}.{month:02d}'
                if year is not None:
                    age = self._calculate_correct_age(day, month, year, today)
                    date_text = f'{date_text}.{year} (Alter: {age})'

                user_id = str(row['user_id']) if row['user_id'] is not None else ''
                user_mention = f'<@{user_id}>' if user_id.isdigit() else display_name
                if real_name:
                    line = f'• {user_mention} ({real_name}) — {date_text}'
                else:
                    line = f'• {user_mention} — {date_text}'
                month_entries[month].append(line)

            for month, month_name in MONTH_NAMES.items():
                entries = month_entries.get(month, [])
                if not entries:
                    continue
                lines.append(month_name)
                lines.extend(entries)
                lines.append('')
            if lines and lines[-1] == '':
                lines.pop()
            description = '\n'.join(lines)

        return discord.Embed(title='🎂 Geburtstagsliste', description=description, color=discord.Color.gold())

    async def refresh_birthday_list(self, guild: discord.Guild) -> None:
        with self._conn() as conn:
            settings = conn.execute(
                'SELECT list_channel_id, list_message_id FROM birthday_settings WHERE guild_id = ? LIMIT 1',
                (guild.id,),
            ).fetchone()

        if settings is None or settings['list_channel_id'] is None or settings['list_message_id'] is None:
            return

        channel = guild.get_channel(int(settings['list_channel_id']))
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(int(settings['list_message_id']))
            await message.edit(embed=self.build_birthday_embed(guild))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    @tasks.loop(minutes=1)
    async def daily_scheduler(self) -> None:
        now = datetime.now(self.timezone)
        day_key = now.strftime('%Y-%m-%d')

        for guild in self.bot.guilds:
            await self._run_scheduler_for_guild(guild, now, day_key)

    async def _run_scheduler_for_guild(self, guild: discord.Guild, now: datetime, day_key: str) -> None:
        with self._conn() as conn:
            settings = conn.execute(
                '''
                SELECT role_id, current_message_id, current_message_channel_id, list_channel_id,
                       last_announce_date, last_cleanup_date
                FROM birthday_settings
                WHERE guild_id = ?
                LIMIT 1
                ''',
                (guild.id,),
            ).fetchone()

        role_id = int(settings['role_id']) if settings and settings['role_id'] else None

        if now.hour == ANNOUNCE_HOUR and now.minute == ANNOUNCE_MINUTE:
            if settings and settings['last_announce_date'] == day_key:
                return
            await self._announce_birthdays(guild, role_id, settings, day_key)
        elif (
            now.hour != ANNOUNCE_HOUR
            and now.minute == ANNOUNCE_MINUTE
            and (settings is None or settings['last_announce_date'] != day_key)
        ):
            with self._conn() as conn:
                rows = conn.execute(
                    'SELECT user_id FROM birthdays WHERE guild_id = ? AND day = ? AND month = ?',
                    (guild.id, now.day, now.month),
                ).fetchall()

            if rows:
                await self._announce_birthdays(guild, role_id, settings, day_key)

        if now.hour == CLEANUP_HOUR and now.minute == CLEANUP_MINUTE:
            if settings and settings['last_cleanup_date'] == day_key:
                return
            await self._cleanup_birthdays(guild, role_id, settings, now, day_key)

    async def _announce_birthdays(
        self,
        guild: discord.Guild,
        role_id: int | None,
        settings: sqlite3.Row | None,
        day_key: str,
    ) -> bool:
        now = datetime.now(self.timezone)
        with self._conn() as conn:
            rows = conn.execute(
                'SELECT user_id FROM birthdays WHERE guild_id = ? AND day = ? AND month = ?',
                (guild.id, now.day, now.month),
            ).fetchall()

        birthday_members: list[discord.Member] = []
        for row in rows:
            member = guild.get_member(int(row['user_id']))
            if member is not None:
                birthday_members.append(member)

        if not birthday_members:
            return False

        target_channel: discord.TextChannel | None = None
        if settings and settings['list_channel_id'] is not None:
            maybe_channel = guild.get_channel(int(settings['list_channel_id']))
            if isinstance(maybe_channel, discord.TextChannel):
                target_channel = maybe_channel

        current_message_id: int | None = None
        current_message_channel_id: int | None = None

        if target_channel is None:
            return False

        if birthday_members:
            mentions = ', '.join(member.mention for member in birthday_members)
            text = f'Das gesamte UL Team wünscht {mentions} alles Gute zum Geburtstag!'
            try:
                sent_message = await target_channel.send(text)
                current_message_id = sent_message.id
                current_message_channel_id = target_channel.id
            except (discord.Forbidden, discord.HTTPException):
                return False

        if role_id is not None:
            role = guild.get_role(role_id)
            if role is not None:
                for member in birthday_members:
                    try:
                        await member.add_roles(role, reason='Geburtstagsrolle (00:00 CET)')
                    except (discord.Forbidden, discord.HTTPException):
                        continue

        with self._conn() as conn:
            conn.execute(
                '''
                INSERT INTO birthday_settings (guild_id, current_message_id, current_message_channel_id, last_announce_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    current_message_id = excluded.current_message_id,
                    current_message_channel_id = excluded.current_message_channel_id,
                    last_announce_date = excluded.last_announce_date
                ''',
                (guild.id, current_message_id, current_message_channel_id, day_key),
            )
            conn.commit()
        return True

    async def _cleanup_birthdays(
        self,
        guild: discord.Guild,
        role_id: int | None,
        settings: sqlite3.Row | None,
        now: datetime,
        day_key: str,
    ) -> None:
        current_message_id = int(settings['current_message_id']) if settings and settings['current_message_id'] else None
        current_message_channel_id = (
            int(settings['current_message_channel_id']) if settings and settings['current_message_channel_id'] else None
        )

        if current_message_id and current_message_channel_id:
            channel = guild.get_channel(current_message_channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(current_message_id)
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        if role_id is not None:
            role = guild.get_role(role_id)
            if role is not None:
                with self._conn() as conn:
                    rows = conn.execute(
                        'SELECT user_id FROM birthdays WHERE guild_id = ? AND day = ? AND month = ?',
                        (guild.id, now.day, now.month),
                    ).fetchall()
                for row in rows:
                    member = guild.get_member(int(row['user_id']))
                    if member is None:
                        continue
                    try:
                        await member.remove_roles(role, reason='Geburtstagsrolle entfernen (23:59 CET)')
                    except (discord.Forbidden, discord.HTTPException):
                        continue

        with self._conn() as conn:
            conn.execute(
                '''
                INSERT INTO birthday_settings (guild_id, current_message_id, current_message_channel_id, last_cleanup_date)
                VALUES (?, NULL, NULL, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    current_message_id = NULL,
                    current_message_channel_id = NULL,
                    last_cleanup_date = excluded.last_cleanup_date
                ''',
                (guild.id, day_key),
            )
            conn.commit()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Birthdays(bot))
