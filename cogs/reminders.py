import asyncio
from datetime import datetime, timedelta
import logging
import sqlite3

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

from database import DB_FILE

LOGGER = logging.getLogger(__name__)
MAX_STATE_UPDATE_RETRIES = 2


class ReminderModal(discord.ui.Modal, title='24h Reminder konfigurieren'):
    def __init__(
        self,
        cog: 'Reminders',
        reminder_title: str,
        channel_id: int,
        action: str = 'create',
        initial_hour: int | None = None,
        initial_minute: int | None = None,
        initial_message: str | None = None,
    ) -> None:
        super().__init__()
        self.cog = cog
        self.reminder_title = reminder_title
        self.channel_id = channel_id
        self.action = action
        self.hour_input = discord.ui.TextInput(
            label='Stunde (0-23)',
            placeholder='13',
            default='' if initial_hour is None else str(initial_hour),
            max_length=2,
        )
        self.minute_input = discord.ui.TextInput(
            label='Minute (0-59)',
            placeholder='30',
            default='' if initial_minute is None else str(initial_minute),
            max_length=2,
        )
        self.message_input = discord.ui.TextInput(
            label='Nachricht (alle 24h)',
            placeholder='Diese Nachricht wird täglich gesendet.',
            style=discord.TextStyle.paragraph,
            default=initial_message or '',
            max_length=2000,
        )
        self.add_item(self.hour_input)
        self.add_item(self.minute_input)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        try:
            hour = int(str(self.hour_input.value).strip())
            minute = int(str(self.minute_input.value).strip())
        except (TypeError, ValueError):
            await interaction.response.send_message('❌ Stunde/Minute müssen Zahlen sein.', ephemeral=True)
            return

        if hour < 0 or hour > 23:
            await interaction.response.send_message('❌ Stunde muss zwischen 0 und 23 liegen.', ephemeral=True)
            return
        if minute < 0 or minute > 59:
            await interaction.response.send_message('❌ Minute muss zwischen 0 und 59 liegen.', ephemeral=True)
            return

        message = str(self.message_input.value).strip()
        if not message:
            await interaction.response.send_message('❌ Nachricht darf nicht leer sein.', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            if self.action == 'create':
                row = conn.execute(
                    '''
                    SELECT 1
                    FROM reminders
                    WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                    LIMIT 1
                    ''',
                    (interaction.guild.id, self.reminder_title),
                ).fetchone()
                if row is not None:
                    await interaction.response.send_message(
                        f'❌ Reminder "{self.reminder_title}" existiert bereits.',
                        ephemeral=True,
                    )
                    return

                conn.execute(
                    '''
                    INSERT INTO reminders (guild_id, channel_id, title, hour, minute, message, last_sent_date, last_message_id)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                    ''',
                    (interaction.guild.id, self.channel_id, self.reminder_title, hour, minute, message),
                )
                conn.commit()
                await interaction.response.send_message(
                    f'✅ Reminder "{self.reminder_title}" gespeichert für täglich {hour:02d}:{minute:02d}.',
                    ephemeral=True,
                )
                return

            row = conn.execute(
                '''
                SELECT id, hour, minute, last_sent_date, last_message_id
                FROM reminders
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (interaction.guild.id, self.reminder_title),
            ).fetchone()
            if row is None:
                await interaction.response.send_message(
                    f'❌ Reminder "{self.reminder_title}" wurde nicht gefunden.',
                    ephemeral=True,
                )
                return

            last_sent_date: str | None = None
            if int(row['hour']) == hour and int(row['minute']) == minute:
                last_sent_date = None if row['last_sent_date'] is None else str(row['last_sent_date'])
            last_message_id: int | None = int(row['last_message_id']) if row['last_message_id'] is not None else None

            conn.execute(
                '''
                UPDATE reminders
                SET hour = ?, minute = ?, message = ?, last_sent_date = ?, last_message_id = ?
                WHERE id = ?
                ''',
                (hour, minute, message, last_sent_date, last_message_id, int(row['id'])),
            )
            conn.commit()

        await interaction.response.send_message(
            f'✅ Reminder "{self.reminder_title}" wurde aktualisiert ({hour:02d}:{minute:02d}).',
            ephemeral=True,
        )


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def cog_unload(self) -> None:
        if self.daily_reminder_scheduler.is_running():
            self.daily_reminder_scheduler.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.daily_reminder_scheduler.is_running():
            self.daily_reminder_scheduler.start()

    async def _title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT title
                FROM reminders
                WHERE guild_id = ? AND title LIKE ? COLLATE NOCASE
                ORDER BY title COLLATE NOCASE ASC
                LIMIT 25
                ''',
                (interaction.guild.id, f'%{current.strip()}%'),
            ).fetchall()
        return [app_commands.Choice(name=str(row['title']), value=str(row['title'])) for row in rows]

    @app_commands.command(name='reminder', description='Erstelle einen täglichen 24h Reminder')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Name des Reminders', channel='Channel für den Reminder')
    async def reminder_command(
        self,
        interaction: discord.Interaction,
        title: str,
        channel: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        clean_title = title.strip()
        if not clean_title:
            await interaction.response.send_message('❌ Titel darf nicht leer sein.', ephemeral=True)
            return

        await interaction.response.send_modal(
            ReminderModal(cog=self, reminder_title=clean_title, channel_id=channel.id)
        )

    @app_commands.command(name='reminder_edit', description='Bearbeite einen bestehenden täglichen Reminder')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel des Reminders')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def reminder_edit_command(self, interaction: discord.Interaction, title: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        clean_title = title.strip()
        if not clean_title:
            await interaction.response.send_message('❌ Titel darf nicht leer sein.', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                '''
                SELECT channel_id, hour, minute, message
                FROM reminders
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (interaction.guild.id, clean_title),
            ).fetchone()

        if row is None:
            await interaction.response.send_message(f'❌ Reminder "{clean_title}" wurde nicht gefunden.', ephemeral=True)
            return

        await interaction.response.send_modal(
            ReminderModal(
                cog=self,
                reminder_title=clean_title,
                channel_id=int(row['channel_id']),
                action='edit',
                initial_hour=int(row['hour']),
                initial_minute=int(row['minute']),
                initial_message=str(row['message']),
            )
        )

    @app_commands.command(name='reminder_remove', description='Lösche einen bestehenden täglichen Reminder')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel des Reminders')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def reminder_remove_command(self, interaction: discord.Interaction, title: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        clean_title = title.strip()
        if not clean_title:
            await interaction.response.send_message('❌ Titel darf nicht leer sein.', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                '''
                SELECT id, title
                FROM reminders
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (interaction.guild.id, clean_title),
            ).fetchone()
            if row is None:
                await interaction.response.send_message(f'❌ Reminder "{clean_title}" wurde nicht gefunden.', ephemeral=True)
                return

            conn.execute('DELETE FROM reminders WHERE id = ?', (int(row['id']),))
            conn.commit()

        await interaction.response.send_message(f'✅ Reminder "{row["title"]}" wurde gelöscht.', ephemeral=True)

    @tasks.loop(seconds=30)
    async def daily_reminder_scheduler(self) -> None:
        now = datetime.now(tz=pytz.timezone('Europe/Berlin'))
        check_window_start = now - timedelta(seconds=60)
        day_key = now.strftime('%Y-%m-%d')
        # The loop runs every 30s and checks the previous 60s window to tolerate delayed
        # executions and prevent missed reminders at minute boundaries.
        # Slot values are stored as "minutes since midnight" for simple SQL matching.
        now_slot = now.hour * 60 + now.minute
        start_slot = check_window_start.hour * 60 + check_window_start.minute
        candidate_slots = sorted({start_slot, now_slot})

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            if len(candidate_slots) == 1:
                rows = conn.execute(
                    '''
                    SELECT id, guild_id, channel_id, hour, minute, message, last_sent_date, last_message_id
                    FROM reminders
                    WHERE (hour * 60 + minute) = ?
                    ''',
                    (candidate_slots[0],),
                ).fetchall()
            else:
                rows = conn.execute(
                    '''
                    SELECT id, guild_id, channel_id, hour, minute, message, last_sent_date, last_message_id
                    FROM reminders
                    WHERE (hour * 60 + minute) IN (?, ?)
                    ''',
                    (candidate_slots[0], candidate_slots[1]),
                ).fetchall()

        for row in rows:
            try:
                hour = int(row['hour'])
                minute = int(row['minute'])
            except (TypeError, ValueError):
                continue

            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If the slot time is in the future for today, it belongs to the previous day
            # (e.g. window crosses midnight and includes 23:59 while now is 00:00).
            if due_at > now:
                due_at -= timedelta(days=1)
            if due_at < check_window_start or due_at > now:
                continue
            if row['last_sent_date'] == day_key:
                continue

            guild = self.bot.get_guild(int(row['guild_id']))
            if guild is None:
                continue
            channel = guild.get_channel(int(row['channel_id']))
            if not isinstance(channel, discord.TextChannel):
                continue

            previous_message_id = row['last_message_id']
            if previous_message_id is not None:
                try:
                    previous_message = await channel.fetch_message(int(previous_message_id))
                    await previous_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                    pass

            try:
                sent_message = await channel.send(str(row['message']))
            except (discord.Forbidden, discord.HTTPException):
                continue

            state_updated = False
            last_error: sqlite3.Error | None = None
            for attempt in range(MAX_STATE_UPDATE_RETRIES):
                try:
                    with sqlite3.connect(DB_FILE) as conn:
                        conn.execute(
                            'UPDATE reminders SET last_sent_date = ?, last_message_id = ? WHERE id = ?',
                            (day_key, int(sent_message.id), int(row['id'])),
                        )
                        conn.commit()
                    state_updated = True
                    break
                except sqlite3.Error as exc:
                    last_error = exc
                    if attempt + 1 < MAX_STATE_UPDATE_RETRIES:
                        await asyncio.sleep(0.1)

            if not state_updated:
                LOGGER.warning('Failed to update reminder send state for reminder id %s: %s', row['id'], last_error)
                try:
                    await sent_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                continue


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
