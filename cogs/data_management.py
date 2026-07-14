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
    backup_text_messages,
    backup_admin_logs,
    backup_admin_roles,
    restore_birthdays_from_backup,
    restore_reminders_from_backup,
    restore_text_messages_from_backup,
    restore_admin_logs_from_backup,
    restore_admin_roles_from_backup,
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

    @app_commands.command(name='backup_all', description='Backup aller Daten (Geburtstage, Reminders, Texte, Logs, Admin-Rollen)')
    @app_commands.default_permissions(administrator=True)
    async def backup_all_command(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            backup_birthdays()
            backup_reminders()
            backup_text_messages()
            backup_admin_logs()
            backup_admin_roles()
            await interaction.followup.send(
                '✅ Alle Daten erfolgreich gebackupt!\n'
                '📂 Dateien speichern unter: `backups/`',
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f'❌ Fehler beim Backup: {e}',
                ephemeral=True,
            )

    @app_commands.command(name='backup_einzeln', description='Backup einzelner Systeme auswählen')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(system='Wähle das System zum Backupen')
    async def backup_einzeln_command(
        self,
        interaction: discord.Interaction,
        system: str,
    ) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if system.lower() == 'geburtstage':
                backup_birthdays()
                await interaction.followup.send('✅ Geburtstage gebackupt!', ephemeral=True)
            elif system.lower() == 'reminders':
                backup_reminders()
                await interaction.followup.send('✅ Reminders gebackupt!', ephemeral=True)
            elif system.lower() == 'texte':
                backup_text_messages()
                await interaction.followup.send('✅ Text-Nachrichten gebackupt!', ephemeral=True)
            elif system.lower() == 'logs':
                backup_admin_logs()
                await interaction.followup.send('✅ Admin-Logs gebackupt!', ephemeral=True)
            elif system.lower() == 'admin-rollen':
                backup_admin_roles()
                await interaction.followup.send('✅ Admin-Rollen gebackupt!', ephemeral=True)
            else:
                await interaction.followup.send(
                    '❌ Unbekanntes System! Wähle: geburtstage, reminders, texte, logs, admin-rollen',
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(f'❌ Fehler beim Backup: {e}', ephemeral=True)

    @app_commands.command(name='restore_all', description='Restore aller Daten aus Backups')
    @app_commands.default_permissions(administrator=True)
    async def restore_all_command(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        results = []
        
        if restore_birthdays_from_backup():
            results.append('✅ Geburtstage wiederhergestellt')
            birthdays_cog = self.bot.get_cog('Birthdays')
            if birthdays_cog:
                for guild in self.bot.guilds:
                    await birthdays_cog.refresh_birthday_list(guild)
        else:
            results.append('⚠️ Geburtstage: Keine Sicherung gefunden')

        if restore_reminders_from_backup():
            results.append('✅ Reminders wiederhergestellt')
        else:
            results.append('⚠️ Reminders: Keine Sicherung gefunden')

        if restore_text_messages_from_backup():
            results.append('✅ Text-Nachrichten wiederhergestellt')
        else:
            results.append('⚠️ Text-Nachrichten: Keine Sicherung gefunden')

        if restore_admin_logs_from_backup():
            results.append('✅ Admin-Logs wiederhergestellt')
        else:
            results.append('⚠️ Admin-Logs: Keine Sicherung gefunden')

        if restore_admin_roles_from_backup():
            results.append('✅ Admin-Rollen wiederhergestellt')
        else:
            results.append('⚠️ Admin-Rollen: Keine Sicherung gefunden')

        await interaction.followup.send('\n'.join(results), ephemeral=True)

    @app_commands.command(name='restore_einzeln', description='Restore einzelner Systeme auswählen')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(system='Wähle das System zum Restoren')
    async def restore_einzeln_command(
        self,
        interaction: discord.Interaction,
        system: str,
    ) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if system.lower() == 'geburtstage':
                success = restore_birthdays_from_backup()
                if success:
                    birthdays_cog = self.bot.get_cog('Birthdays')
                    if birthdays_cog:
                        for guild in self.bot.guilds:
                            await birthdays_cog.refresh_birthday_list(guild)
                    await interaction.followup.send('✅ Geburtstage wiederhergestellt!', ephemeral=True)
                else:
                    await interaction.followup.send('⚠️ Keine Sicherung gefunden!', ephemeral=True)
            elif system.lower() == 'reminders':
                success = restore_reminders_from_backup()
                if success:
                    await interaction.followup.send('✅ Reminders wiederhergestellt!', ephemeral=True)
                else:
                    await interaction.followup.send('⚠️ Keine Sicherung gefunden!', ephemeral=True)
            elif system.lower() == 'texte':
                success = restore_text_messages_from_backup()
                if success:
                    await interaction.followup.send('✅ Text-Nachrichten wiederhergestellt!', ephemeral=True)
                else:
                    await interaction.followup.send('⚠️ Keine Sicherung gefunden!', ephemeral=True)
            elif system.lower() == 'logs':
                success = restore_admin_logs_from_backup()
                if success:
                    await interaction.followup.send('✅ Admin-Logs wiederhergestellt!', ephemeral=True)
                else:
                    await interaction.followup.send('⚠️ Keine Sicherung gefunden!', ephemeral=True)
            elif system.lower() == 'admin-rollen':
                success = restore_admin_roles_from_backup()
                if success:
                    await interaction.followup.send('✅ Admin-Rollen wiederhergestellt!', ephemeral=True)
                else:
                    await interaction.followup.send('⚠️ Keine Sicherung gefunden!', ephemeral=True)
            else:
                await interaction.followup.send(
                    '❌ Unbekanntes System! Wähle: geburtstage, reminders, texte, logs, admin-rollen',
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(f'❌ Fehler beim Restore: {e}', ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DataManagement(bot))
