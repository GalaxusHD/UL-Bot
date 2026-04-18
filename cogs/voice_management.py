import discord
from discord import app_commands
from discord.ext import commands


class VoiceManagement(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name='moveall', description='Move all users from current voice channel to target')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel='Target voice channel')
    async def moveall(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel | discord.StageChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ This command can only be used in a server.', ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ You need administrator permissions!', ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message('❌ Could not verify your voice state.', ephemeral=True)
            return

        from_channel = interaction.user.voice.channel if interaction.user.voice else None
        if not isinstance(from_channel, (discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message('❌ You must be in a voice channel.', ephemeral=True)
            return

        if from_channel.id == channel.id:
            await interaction.response.send_message('❌ Source and target channels are the same.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        moved = 0
        failed = 0
        for member in list(from_channel.members):
            try:
                await member.move_to(channel, reason=f'/moveall used by {interaction.user}')
                moved += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        await interaction.followup.send(
            f'✅ Moved {moved} user(s) from {from_channel.mention} to {channel.mention}.'
            + (f' ⚠️ Failed to move {failed} user(s).' if failed else ''),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceManagement(bot))
