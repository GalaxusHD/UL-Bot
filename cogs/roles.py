import re
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

CUSTOM_EMOJI_PATTERN = re.compile(r'^<(a?):([a-zA-Z0-9_]+):(\d+)>$')
ROLE_MENTION_PATTERN = re.compile(r'^<@&(\d+)>$')


def normalise_emoji(emoji_value: str) -> tuple[str, str]:
    emoji_value = emoji_value.strip()
    custom_match = CUSTOM_EMOJI_PATTERN.fullmatch(emoji_value)
    if custom_match:
        _, name, emoji_id = custom_match.groups()
        return f'{name}:{emoji_id}', emoji_value
    return emoji_value, emoji_value


def payload_emoji_key(payload_emoji: discord.PartialEmoji) -> str:
    if payload_emoji.id is not None and payload_emoji.name:
        return f'{payload_emoji.name}:{payload_emoji.id}'
    return str(payload_emoji.name)


class RoleSetupModal(discord.ui.Modal):
    def __init__(self, title: str, channel: discord.TextChannel):
        super().__init__(title='Rollen-Auswahl erstellen')
        self.selector_title = title
        self.channel = channel
        self.role_lines = discord.ui.TextInput(
            label='Rollen + Emoji (1-10 Zeilen)',
            style=discord.TextStyle.paragraph,
            required=True,
            placeholder='🎮 @Gamer\n📢 @News\n🔥 @Events',
            max_length=1800,
        )
        self.add_item(self.role_lines)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        parsed_entries = []
        seen_roles = set()
        seen_emojis = set()

        for raw_line in str(self.role_lines.value).splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parts = [part.strip() for part in line.split('|', 1)] if '|' in line else line.split(maxsplit=1)
            if len(parts) != 2:
                await interaction.response.send_message(
                    f'❌ Ungültige Zeile: `{line}`. Format: `Emoji @Rolle` oder `Emoji | @Rolle`',
                    ephemeral=True,
                )
                return

            emoji_input, role_input = parts
            emoji_key, display_emoji = normalise_emoji(emoji_input)

            role_match = ROLE_MENTION_PATTERN.fullmatch(role_input)
            role = None
            if role_match:
                role = interaction.guild.get_role(int(role_match.group(1)))
            elif role_input.isdigit():
                role = interaction.guild.get_role(int(role_input))
            else:
                role = discord.utils.get(interaction.guild.roles, name=role_input)

            if role is None:
                await interaction.response.send_message(f'❌ Rolle nicht gefunden: `{role_input}`', ephemeral=True)
                return

            if role.id in seen_roles:
                await interaction.response.send_message(f'❌ Rolle doppelt angegeben: {role.mention}', ephemeral=True)
                return

            if emoji_key in seen_emojis:
                await interaction.response.send_message(f'❌ Emoji doppelt angegeben: {display_emoji}', ephemeral=True)
                return

            seen_roles.add(role.id)
            seen_emojis.add(emoji_key)
            parsed_entries.append((role, emoji_key, display_emoji))

        if not parsed_entries:
            await interaction.response.send_message('❌ Bitte mindestens eine Rolle angeben.', ephemeral=True)
            return

        if len(parsed_entries) > 10:
            await interaction.response.send_message('❌ Maximal 10 Rollen sind erlaubt.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title=self.selector_title,
            description='\n'.join(f'{display_emoji} • {role.mention}' for role, _, display_emoji in parsed_entries),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text='Reagiere, um Rollen zu erhalten oder zu entfernen.')

        try:
            selector_message = await self.channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send('❌ Nachricht konnte im Ziel-Channel nicht gesendet werden.', ephemeral=True)
            return

        for _, _, display_emoji in parsed_entries:
            try:
                await selector_message.add_reaction(display_emoji)
            except (discord.HTTPException, discord.Forbidden):
                await interaction.followup.send(
                    f'❌ Reaktion `{display_emoji}` konnte nicht hinzugefügt werden.',
                    ephemeral=True,
                )
                return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO role_messages (guild_id, title, channel_id, message_id) VALUES (?, ?, ?, ?)',
            (interaction.guild.id, self.selector_title, self.channel.id, selector_message.id),
        )
        role_message_id = cursor.lastrowid

        for position, (role, emoji_key, display_emoji) in enumerate(parsed_entries, start=1):
            cursor.execute(
                '''
                INSERT INTO role_message_roles (role_message_id, role_id, emoji, display_emoji, position)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (role_message_id, role.id, emoji_key, display_emoji, position),
            )

        conn.commit()
        conn.close()

        await interaction.followup.send(
            f'✅ Rollen-Auswahl in {self.channel.mention} erstellt!',
            ephemeral=True,
        )


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    role_group = app_commands.Group(name='role', description='Rollen-System')

    @role_group.command(name='create', description='Erstelle eine Rollen-Auswahl per Reaktionen')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel der Rollen-Nachricht', channel='Channel für die Rollen-Nachricht')
    async def create_role_selector(
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

        await interaction.response.send_modal(RoleSetupModal(title, channel))

    async def _toggle_role(self, payload: discord.RawReactionActionEvent, add_role: bool) -> None:
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        emoji_key = payload_emoji_key(payload.emoji)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT rmr.role_id
            FROM role_messages rm
            JOIN role_message_roles rmr ON rmr.role_message_id = rm.id
            WHERE rm.guild_id = ? AND rm.message_id = ? AND rmr.emoji = ?
            LIMIT 1
            ''',
            (payload.guild_id, payload.message_id, emoji_key),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return

        role = guild.get_role(row[0])
        if role is None:
            return

        try:
            if add_role:
                await member.add_roles(role, reason='Role selector reaction')
            else:
                await member.remove_roles(role, reason='Role selector reaction removal')
        except (discord.Forbidden, discord.HTTPException):
            return

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._toggle_role(payload, add_role=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._toggle_role(payload, add_role=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roles(bot))
