"""
Cog for data backup, restore, and export commands.
Allows admins to manually export/import data.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

from storage_backup import (
    backup_all,
    backup_birthdays,
    backup_reminders,
    restore_birthdays_from_backup,
    restore_reminders_from_backup,
)


class DataManagement(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.auto_backup_task.start()

    def cog_unload(self) -> None:
        if self.auto_backup_task.is_running():
            self.auto_backup_task.cancel()

    @tasks.loop(hours=1)
    async def auto_backup_task(self) -> None:
        """Automatically backup data every hour."""
        backup_all()

    @auto_backup_task.before_loop
    async def before_auto_backup(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name='backup_export', description='Exportiere alle Daten (Geburtstage und Reminder)')
    @app_commands.default_permissions(administrator=True)
    async def backup_export(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            backup_birthdays()
            backup_reminders()
            await interaction.followup.send(
                '✅ Daten erfolgreich exportiert!\n'
                '📂 Dateien speichern unter: `backups/birthdays_backup.json` und `backups/reminders_backup.json`',
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f'❌ Fehler beim Export: {e}',
                ephemeral=True,
            )

    @app_commands.command(name='backup_restore_birthdays', description='Stelle Geburtstage aus der Sicherung wieder her')
    @app_commands.default_permissions(administrator=True)
    async def backup_restore_birthdays(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success = restore_birthdays_from_backup()
        if success:
            # Refresh all birthday lists
            birthdays_cog = self.bot.get_cog('Birthdays')
            if birthdays_cog:
                for guild in self.bot.guilds:
                    await birthdays_cog.refresh_birthday_list(guild)

            await interaction.followup.send(
                '✅ Geburtstage wurden aus der Sicherung wiederhergestellt!',
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                '❌ Fehler beim Wiederherstellen der Geburtstage. Bitte prüfe ob eine Sicherungsdatei existiert.',
                ephemeral=True,
            )

    @app_commands.command(name='backup_restore_reminders', description='Stelle Reminder aus der Sicherung wieder her')
    @app_commands.default_permissions(administrator=True)
    async def backup_restore_reminders(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success = restore_reminders_from_backup()
        if success:
            await interaction.followup.send(
                '✅ Reminder wurden aus der Sicherung wiederhergestellt!',
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                '❌ Fehler beim Wiederherstellen der Reminder. Bitte prüfe ob eine Sicherungsdatei existiert.',
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DataManagement(bot))
