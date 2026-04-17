import os
import sqlite3
from datetime import datetime

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

from database import DB_FILE

DEFAULT_TIMEZONE = 'Europe/Berlin'


class Birthdays(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.timezone = pytz.timezone(os.getenv('BIRTHDAY_TIMEZONE', DEFAULT_TIMEZONE))
        self.channel_id = int(os.getenv('BIRTHDAY_CHANNEL_ID', '0') or 0)

    def cog_unload(self) -> None:
        if self.check_birthdays.is_running():
            self.check_birthdays.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.check_birthdays.is_running():
            self.check_birthdays.start()

    @app_commands.command(name='birthday_set', description='Speichere deinen Geburtstag')
    @app_commands.describe(month='Monat (1-12)', day='Tag (1-31)')
    async def birthday_set(self, interaction: discord.Interaction, month: int, day: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        try:
            datetime(2000, month, day)
        except ValueError:
            await interaction.response.send_message('❌ Ungültiges Datum.', ephemeral=True)
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO birthdays (guild_id, user_id, month, day, last_congratulated_year)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                month=excluded.month,
                day=excluded.day,
                last_congratulated_year=NULL
            ''',
            (interaction.guild.id, interaction.user.id, month, day),
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message('✅ Geburtstag gespeichert!', ephemeral=True)

    @app_commands.command(name='birthday_remove', description='Entferne deinen gespeicherten Geburtstag')
    async def birthday_remove(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?',
            (interaction.guild.id, interaction.user.id),
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted:
            await interaction.response.send_message('✅ Geburtstag entfernt.', ephemeral=True)
        else:
            await interaction.response.send_message('ℹ️ Kein gespeicherter Geburtstag gefunden.', ephemeral=True)

    @tasks.loop(minutes=1)
    async def check_birthdays(self) -> None:
        now = datetime.now(self.timezone)
        if now.hour != 0 or now.minute != 0:
            return

        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT guild_id, user_id
            FROM birthdays
            WHERE month = ? AND day = ? AND (last_congratulated_year IS NULL OR last_congratulated_year < ?)
            ''',
            (now.month, now.day, now.year),
        )
        birthday_rows = cursor.fetchall()

        for row in birthday_rows:
            guild = self.bot.get_guild(row['guild_id'])
            if guild is None:
                continue

            member = guild.get_member(row['user_id'])
            if member is None:
                continue

            channel = None
            if self.channel_id:
                fetched_channel = guild.get_channel(self.channel_id)
                if isinstance(fetched_channel, discord.TextChannel):
                    channel = fetched_channel

            if channel is None and isinstance(guild.system_channel, discord.TextChannel):
                channel = guild.system_channel

            if channel is None:
                continue

            message = f'🎉 Das gesamte UL Team wünscht {member.mention} alles Gute zum Geburtstag! 🎂🎈'
            try:
                await channel.send(message)
            except (discord.Forbidden, discord.HTTPException):
                continue

            cursor.execute(
                '''
                UPDATE birthdays
                SET last_congratulated_year = ?
                WHERE guild_id = ? AND user_id = ?
                ''',
                (now.year, row['guild_id'], row['user_id']),
            )

        conn.commit()
        conn.close()

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Birthdays(bot))
