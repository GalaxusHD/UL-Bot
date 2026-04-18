from datetime import datetime, timezone
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import DB_FILE


class ReminderModal(discord.ui.Modal, title='24h Reminder konfigurieren'):
    def __init__(self, cog: 'Reminders', reminder_title: str, channel_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.reminder_title = reminder_title
        self.channel_id = channel_id
        self.hour_input = discord.ui.TextInput(label='Stunde (0-23)', placeholder='13', max_length=2)
        self.minute_input = discord.ui.TextInput(label='Minute (0-59)', placeholder='30', max_length=2)
        self.message_input = discord.ui.TextInput(
            label='Nachricht (alle 24h)',
            placeholder='Diese Nachricht wird täglich gesendet.',
            style=discord.TextStyle.paragraph,
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
                INSERT INTO reminders (guild_id, channel_id, title, hour, minute, message)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (interaction.guild.id, self.channel_id, self.reminder_title, hour, minute, message),
            )
            conn.commit()

        await interaction.response.send_message(
            f'✅ Reminder "{self.reminder_title}" gespeichert für täglich {hour:02d}:{minute:02d}.',
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

    @tasks.loop(minutes=1)
    async def daily_reminder_scheduler(self) -> None:
        now = datetime.now(timezone.utc)
        day_key = now.strftime('%Y-%m-%d')

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT id, guild_id, channel_id, hour, minute, message, last_sent_date
                FROM reminders
                WHERE hour = ? AND minute = ?
                ''',
                (now.hour, now.minute),
            ).fetchall()

        for row in rows:
            if row['last_sent_date'] == day_key:
                continue

            guild = self.bot.get_guild(int(row['guild_id']))
            if guild is None:
                continue
            channel = guild.get_channel(int(row['channel_id']))
            if not isinstance(channel, discord.TextChannel):
                continue

            try:
                await channel.send(str(row['message']))
            except (discord.Forbidden, discord.HTTPException):
                continue

            with sqlite3.connect(DB_FILE) as conn:
                conn.execute(
                    'UPDATE reminders SET last_sent_date = ? WHERE id = ?',
                    (day_key, int(row['id'])),
                )
                conn.commit()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
