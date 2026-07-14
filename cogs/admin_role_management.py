"""
Admin role management cog.
Allows server admins to configure which roles have admin access.
"""

import discord
from discord import app_commands
from discord.ext import commands

from admin_roles import add_admin_role, remove_admin_role, get_admin_roles


class AdminRoleManagement(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name='admin', description='Verwalte Admin-Rollen für den Server')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(action='add oder remove', role='Die Rolle zum Hinzufügen/Entfernen')
    async def admin_command(
        self,
        interaction: discord.Interaction,
        action: str,
        role: discord.Role,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        action = action.strip().lower()
        if action not in ('add', 'remove'):
            await interaction.response.send_message('❌ Action muss "add" oder "remove" sein.', ephemeral=True)
            return

        if action == 'add':
            if add_admin_role(interaction.guild.id, role.id):
                await interaction.response.send_message(
                    f'✅ Die Rolle {role.mention} wurde als Admin-Rolle hinzugefügt.',
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f'❌ Fehler beim Hinzufügen der Rolle {role.mention}.',
                    ephemeral=True,
                )
        elif action == 'remove':
            if remove_admin_role(interaction.guild.id, role.id):
                await interaction.response.send_message(
                    f'✅ Die Rolle {role.mention} wurde aus den Admin-Rollen entfernt.',
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f'❌ Fehler beim Entfernen der Rolle {role.mention}.',
                    ephemeral=True,
                )

    @app_commands.command(name='admin_liste', description='Zeige alle Admin-Rollen des Servers')
    @app_commands.default_permissions(administrator=True)
    async def admin_liste_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        admin_role_ids = get_admin_roles(interaction.guild.id)

        if not admin_role_ids:
            await interaction.response.send_message(
                '❌ Keine Admin-Rollen für diesen Server konfiguriert.',
                ephemeral=True,
            )
            return

        roles_list = []
        for role_id in admin_role_ids:
            role = interaction.guild.get_role(role_id)
            if role:
                roles_list.append(f'• {role.mention}')

        if not roles_list:
            await interaction.response.send_message(
                '❌ Keine gültigen Admin-Rollen gefunden.',
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title='🔐 Admin-Rollen',
            description='\n'.join(roles_list),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminRoleManagement(bot))
