import re
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

HEX_COLOR_PATTERN = re.compile(r'^#[0-9A-Fa-f]{6}$')
ROLE_ID_PATTERN = re.compile(r'^\s*<@&(?P<id>\d+)>\s*$|^\s*(?P<id_plain>\d+)\s*$')


class WelcomeModal(discord.ui.Modal, title='Welcome konfigurieren'):
    def __init__(
        self,
        cog: 'Welcome',
        channel_id: int,
        action: str = 'create',
        initial_message: str = '',
        initial_embed: bool = False,
        initial_color: str | None = None,
        initial_role_id: int | None = None,
        initial_dm_flag: bool = False,
    ) -> None:
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.action = action

        self.message_input = discord.ui.TextInput(
            label='Welcome Nachricht',
            style=discord.TextStyle.paragraph,
            max_length=2000,
            default=initial_message,
        )
        self.embed_input = discord.ui.TextInput(
            label='Als Embed senden? (yes/no)',
            placeholder='yes oder no',
            max_length=3,
            default='yes' if initial_embed else 'no',
        )
        self.color_input = discord.ui.TextInput(
            label='Embed Farbe (#RRGGBB, nur bei yes)',
            required=False,
            max_length=7,
            default=initial_color or '',
        )
        self.role_input = discord.ui.TextInput(
            label='Optionale Rolle (Role-ID oder @Role)',
            required=False,
            max_length=32,
            default='' if initial_role_id is None else str(initial_role_id),
        )
        self.dm_input = discord.ui.TextInput(
            label='DM an neue Member senden? (yes/no, leer = no)',
            placeholder='yes oder no',
            required=False,
            max_length=3,
            default='yes' if initial_dm_flag else 'no',
        )

        self.add_item(self.message_input)
        self.add_item(self.embed_input)
        self.add_item(self.color_input)
        self.add_item(self.role_input)
        self.add_item(self.dm_input)

    @staticmethod
    def _parse_yes_no(value: str, field_name: str) -> bool:
        normalized = value.strip().lower()
        if normalized in {'yes', 'y', 'ja', 'true', '1'}:
            return True
        if normalized in {'no', 'n', 'nein', 'false', '0', ''}:
            return False
        raise ValueError(f'❌ {field_name} muss "yes" oder "no" sein.')

    @staticmethod
    def _parse_role_id(raw_value: str) -> int | None:
        normalized = raw_value.strip()
        if not normalized:
            return None
        match = ROLE_ID_PATTERN.match(normalized)
        if not match:
            raise ValueError('❌ Rolle muss eine Role-ID oder ein @Rollen-Mention sein.')
        role_id_value = match.group('id') or match.group('id_plain')
        if role_id_value is None:
            raise ValueError('❌ Rolle konnte nicht gelesen werden.')
        return int(role_id_value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        message = str(self.message_input.value).strip()
        if not message:
            await interaction.response.send_message('❌ Nachricht darf nicht leer sein.', ephemeral=True)
            return

        try:
            embed_flag = self._parse_yes_no(str(self.embed_input.value), 'Embed')
            dm_flag = self._parse_yes_no(str(self.dm_input.value), 'DM')
            role_id = self._parse_role_id(str(self.role_input.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        color_value = str(self.color_input.value).strip() if self.color_input.value else ''
        if embed_flag:
            if not color_value:
                await interaction.response.send_message(
                    '❌ Embed-Farbe ist erforderlich, wenn Embed auf yes gesetzt ist.',
                    ephemeral=True,
                )
                return
            if not HEX_COLOR_PATTERN.fullmatch(color_value):
                await interaction.response.send_message('❌ Embed-Farbe muss im Format #RRGGBB sein.', ephemeral=True)
                return
        else:
            color_value = ''

        if role_id is not None and interaction.guild.get_role(role_id) is None:
            await interaction.response.send_message('❌ Angegebene Rolle wurde nicht gefunden.', ephemeral=True)
            return

        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                existing = conn.execute(
                    '''
                    SELECT id
                    FROM welcome_messages
                    WHERE guild_id = ? AND channel_id = ?
                    LIMIT 1
                    ''',
                    (interaction.guild.id, self.channel_id),
                ).fetchone()

                if self.action == 'create':
                    if existing is not None:
                        await interaction.response.send_message(
                            '❌ Für diesen Channel existiert bereits ein Welcome-Setup. Nutze /welcome_edit.',
                            ephemeral=True,
                        )
                        return
                    conn.execute(
                        '''
                        INSERT INTO welcome_messages (guild_id, channel_id, message, embed_flag, color, role_id, dm_flag)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            interaction.guild.id,
                            self.channel_id,
                            message,
                            1 if embed_flag else 0,
                            color_value or None,
                            role_id,
                            1 if dm_flag else 0,
                        ),
                    )
                    conn.commit()
                    await interaction.response.send_message('✅ Welcome-Setup gespeichert.', ephemeral=True)
                    return

                if existing is None:
                    await interaction.response.send_message(
                        '❌ Kein Welcome-Setup für diesen Channel gefunden.',
                        ephemeral=True,
                    )
                    return

                conn.execute(
                    '''
                    UPDATE welcome_messages
                    SET message = ?, embed_flag = ?, color = ?, role_id = ?, dm_flag = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''',
                    (
                        message,
                        1 if embed_flag else 0,
                        color_value or None,
                        role_id,
                        1 if dm_flag else 0,
                        int(existing['id']),
                    ),
                )
                conn.commit()
        except sqlite3.DatabaseError:
            await interaction.response.send_message('❌ Datenbankfehler beim Speichern des Welcome-Setups.', ephemeral=True)
            return

        await interaction.response.send_message('✅ Welcome-Setup aktualisiert.', ephemeral=True)


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _render_message(template: str, member: discord.Member) -> str:
        return (
            template
            .replace('{member}', member.mention)
            .replace('{mention}', member.mention)
            .replace('{member_name}', member.display_name)
            .replace('{server}', member.guild.name)
        )

    @staticmethod
    def _embed_color(raw_color: str | None) -> discord.Colour:
        if raw_color and HEX_COLOR_PATTERN.fullmatch(raw_color):
            return discord.Colour(int(raw_color[1:], 16))
        return discord.Colour.blurple()

    @app_commands.command(name='welcome', description='Erstelle ein Welcome-Setup für neue Member')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel='Channel für die Welcome-Nachricht')
    async def welcome_command(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.send_modal(WelcomeModal(cog=self, channel_id=channel.id, action='create'))

    @app_commands.command(name='welcome_edit', description='Bearbeite ein bestehendes Welcome-Setup')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel='Channel des bestehenden Welcome-Setups')
    async def welcome_edit_command(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
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
                SELECT message, embed_flag, color, role_id, dm_flag
                FROM welcome_messages
                WHERE guild_id = ? AND channel_id = ?
                LIMIT 1
                ''',
                (interaction.guild.id, channel.id),
            ).fetchone()

        if row is None:
            await interaction.response.send_message('❌ Kein Welcome-Setup für diesen Channel gefunden.', ephemeral=True)
            return

        await interaction.response.send_modal(
            WelcomeModal(
                cog=self,
                channel_id=channel.id,
                action='edit',
                initial_message=str(row['message']),
                initial_embed=bool(row['embed_flag']),
                initial_color=None if row['color'] is None else str(row['color']),
                initial_role_id=None if row['role_id'] is None else int(row['role_id']),
                initial_dm_flag=bool(row['dm_flag']),
            )
        )

    @app_commands.command(name='welcome_remove', description='Lösche ein Welcome-Setup')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel='Channel des Welcome-Setups')
    async def welcome_remove_command(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute(
                '''
                SELECT id
                FROM welcome_messages
                WHERE guild_id = ? AND channel_id = ?
                LIMIT 1
                ''',
                (interaction.guild.id, channel.id),
            ).fetchone()
            if row is None:
                await interaction.response.send_message('❌ Kein Welcome-Setup für diesen Channel gefunden.', ephemeral=True)
                return

            conn.execute('DELETE FROM welcome_messages WHERE id = ?', (int(row[0]),))
            conn.commit()

        await interaction.response.send_message('✅ Welcome-Setup gelöscht.', ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT channel_id, message, embed_flag, color, role_id, dm_flag
                FROM welcome_messages
                WHERE guild_id = ?
                ORDER BY id ASC
                ''',
                (member.guild.id,),
            ).fetchall()

        if not rows:
            return

        dm_sent = False
        for row in rows:
            message_text = self._render_message(str(row['message']), member)
            use_embed = bool(row['embed_flag'])
            color_value = None if row['color'] is None else str(row['color'])
            role_id = None if row['role_id'] is None else int(row['role_id'])
            dm_enabled = bool(row['dm_flag'])

            target_channel = member.guild.get_channel(int(row['channel_id']))
            if isinstance(target_channel, discord.TextChannel):
                try:
                    if use_embed:
                        embed = discord.Embed(description=message_text, color=self._embed_color(color_value))
                        await target_channel.send(embed=embed)
                    else:
                        await target_channel.send(message_text)
                except (discord.Forbidden, discord.HTTPException):
                    pass

            if role_id is not None:
                role = member.guild.get_role(role_id)
                if role is not None:
                    try:
                        await member.add_roles(role, reason='Welcome-System automatische Rollenvergabe')
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            if dm_enabled and not dm_sent:
                try:
                    if use_embed:
                        dm_embed = discord.Embed(description=message_text, color=self._embed_color(color_value))
                        await member.send(embed=dm_embed)
                    else:
                        await member.send(message_text)
                    dm_sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
