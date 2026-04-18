import asyncio
import re
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

MAX_MENTION_NAME_LENGTH = 32
MEMBER_QUERY_LIMIT = 10
EMBED_DESCRIPTION_MAX_LENGTH = 4096
MENTION_PATTERN = re.compile(
    rf'<@!?(?P<id>\d+)>|(?<![\w.])@(?P<name>[A-Za-z0-9_.-]{{2,{MAX_MENTION_NAME_LENGTH}}})\b'
)


class TextMessageModal(discord.ui.Modal):
    def __init__(
        self,
        cog: 'TextMessages',
        action: str,
        message_title: str,
        channel_id: int | None = None,
        embed: bool = False,
        colour: str | None = None,
        initial_message: str | None = None
    ):
        super().__init__(title='Text-Nachricht eingeben')
        self.cog = cog
        self.action = action
        self.message_title = message_title
        self.channel_id = channel_id
        self.embed = embed
        self.colour = colour
        self.message_input = discord.ui.TextInput(
            label='Nachricht',
            style=discord.TextStyle.paragraph,
            required=True,
            default=initial_message or ''
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            message = str(self.message_input.value).strip()
            if not message:
                await interaction.followup.send('❌ Nachricht darf nicht leer sein.', ephemeral=True)
                return
            formatted_message = await self.cog._convert_mentions_to_display(interaction.guild, message)

            if self.action == 'create':
                if self.channel_id is None:
                    await interaction.followup.send('❌ Kein gültiger Channel für "create" übergeben.', ephemeral=True)
                    return

                cursor.execute(
                    '''
                    SELECT 1
                    FROM text_messages
                    WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                    LIMIT 1
                    ''',
                    (interaction.guild.id, self.message_title)
                )
                if cursor.fetchone() is not None:
                    await interaction.followup.send(
                        f'❌ Nachricht "{self.message_title}" existiert bereits!',
                        ephemeral=True
                    )
                    return

                target_channel = await self.cog._resolve_text_channel(interaction.guild, self.channel_id)
                if target_channel is None:
                    await interaction.followup.send('❌ Channel nicht gefunden oder nicht zugreifbar.', ephemeral=True)
                    return

                if self.embed:
                    embed_message = discord.Embed(
                        description=formatted_message,
                        color=self.cog._parse_colour(self.colour)
                    )
                    posted_message = await target_channel.send(embed=embed_message)
                else:
                    posted_message = await target_channel.send(formatted_message)

                cursor.execute(
                    '''
                    INSERT INTO text_messages (guild_id, title, channel_id, message_id, message_content)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (interaction.guild.id, self.message_title, target_channel.id, posted_message.id, formatted_message)
                )
                conn.commit()
                await interaction.followup.send(
                    f'✅ Nachricht "{self.message_title}" erstellt in {target_channel.mention}!',
                    ephemeral=True
                )
                return

            if self.action == 'edit':
                cursor.execute(
                    '''
                    SELECT id, channel_id, message_id
                    FROM text_messages
                    WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                    LIMIT 1
                    ''',
                    (interaction.guild.id, self.message_title)
                )
                record = cursor.fetchone()

                if record is None:
                    await interaction.followup.send(f'❌ Nachricht "{self.message_title}" nicht gefunden!', ephemeral=True)
                    return

                if record['message_id'] is None:
                    await interaction.followup.send(
                        f'❌ Nachricht "{self.message_title}" hat keine gespeicherte Message-ID. Bitte neu erstellen.',
                        ephemeral=True
                    )
                    return

                target_channel = await self.cog._resolve_text_channel(interaction.guild, record['channel_id'])
                if target_channel is None:
                    await interaction.followup.send('❌ Ursprungs-Channel nicht gefunden oder nicht mehr zugreifbar.', ephemeral=True)
                    return

                try:
                    discord_message = await asyncio.wait_for(
                        target_channel.fetch_message(record['message_id']),
                        timeout=10
                    )
                except asyncio.TimeoutError:
                    await interaction.followup.send('❌ Zeitüberschreitung beim Laden der Discord-Nachricht.', ephemeral=True)
                    return
                except discord.NotFound:
                    await interaction.followup.send('❌ Discord-Nachricht wurde bereits gelöscht.', ephemeral=True)
                    return
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.followup.send('❌ Discord-Nachricht konnte nicht geladen werden.', ephemeral=True)
                    return

                try:
                    if discord_message.embeds:
                        existing_embed = discord_message.embeds[0].copy()
                        existing_embed.title = None
                        existing_embed.description = formatted_message
                        await asyncio.wait_for(discord_message.edit(embed=existing_embed), timeout=10)
                    else:
                        await asyncio.wait_for(discord_message.edit(content=formatted_message), timeout=10)
                except asyncio.TimeoutError:
                    await interaction.followup.send('❌ Zeitüberschreitung beim Bearbeiten der Discord-Nachricht.', ephemeral=True)
                    return
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.followup.send('❌ Discord-Nachricht konnte nicht bearbeitet werden.', ephemeral=True)
                    return

                cursor.execute(
                    'UPDATE text_messages SET message_content = ? WHERE id = ?',
                    (formatted_message, record['id'])
                )
                conn.commit()
                await interaction.followup.send(f'✅ Nachricht "{self.message_title}" bearbeitet!', ephemeral=True)
        finally:
            conn.close()


class TextMessages(commands.Cog):
    text = app_commands.Group(name='text', description='Verwalte Text-Nachrichten')

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    async def _resolve_text_channel(guild: discord.Guild, channel_id: int) -> discord.TextChannel | None:
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel

        try:
            fetched_channel = await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

        if isinstance(fetched_channel, discord.TextChannel):
            return fetched_channel
        return None

    @staticmethod
    def _parse_colour(colour: str | None) -> discord.Colour:
        colour_map = {
            'red': discord.Colour.red(),
            'blue': discord.Colour.blue(),
            'green': discord.Colour.green(),
            'gold': discord.Colour.gold(),
            'purple': discord.Colour.purple(),
            'orange': discord.Colour.orange(),
        }
        normalized_colour = (colour or '').strip()
        if re.fullmatch(r'#[0-9A-Fa-f]{6}', normalized_colour):
            return discord.Colour(int(normalized_colour[1:], 16))
        return colour_map.get(normalized_colour.lower(), discord.Colour.red())

    @staticmethod
    def _member_matches_name(member: discord.Member, lowered_name: str) -> bool:
        return (
            member.name.lower() == lowered_name
            or member.display_name.lower() == lowered_name
            or (member.global_name and member.global_name.lower() == lowered_name)
        )

    @staticmethod
    async def _resolve_member_by_id(guild: discord.Guild, user_id: int) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    @staticmethod
    async def _resolve_member_by_name(guild: discord.Guild, raw_name: str) -> discord.Member | None:
        lowered_name = raw_name.lower()
        cached_member = guild.get_member_named(raw_name)
        if cached_member is not None and TextMessages._member_matches_name(cached_member, lowered_name):
            return cached_member

        try:
            query_result = await guild.query_members(query=raw_name, limit=MEMBER_QUERY_LIMIT)
        except (discord.Forbidden, discord.HTTPException):
            query_result = []
        for member in query_result:
            if TextMessages._member_matches_name(member, lowered_name):
                return member

        for member in guild.members:
            if TextMessages._member_matches_name(member, lowered_name):
                return member
        return None

    @staticmethod
    async def _convert_mentions_to_display(guild: discord.Guild, message: str) -> str:
        converted_parts: list[str] = []
        current_position = 0
        members_by_id: dict[int, discord.Member | None] = {}
        members_by_name: dict[str, discord.Member | None] = {}

        for match in MENTION_PATTERN.finditer(message):
            converted_parts.append(message[current_position:match.start()])

            user_id = match.group('id')
            username = match.group('name')
            member: discord.Member | None = None

            if user_id is not None:
                parsed_user_id = int(user_id)
                if parsed_user_id not in members_by_id:
                    members_by_id[parsed_user_id] = await TextMessages._resolve_member_by_id(guild, parsed_user_id)
                member = members_by_id[parsed_user_id]
            elif username is not None:
                lowered_username = username.lower()
                if lowered_username not in members_by_name:
                    members_by_name[lowered_username] = await TextMessages._resolve_member_by_name(
                        guild, username
                    )
                member = members_by_name[lowered_username]

            if member is None:
                converted_parts.append(match.group(0))
            else:
                converted_parts.append(f'<@{member.id}>')

            current_position = match.end()

        converted_parts.append(message[current_position:])
        return ''.join(converted_parts)

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
                FROM text_messages
                WHERE guild_id = ? AND title LIKE ? COLLATE NOCASE
                ORDER BY title COLLATE NOCASE ASC
                LIMIT 25
                ''',
                (interaction.guild.id, f'%{current.strip()}%'),
            ).fetchall()
        return [app_commands.Choice(name=str(row['title']), value=str(row['title'])) for row in rows]

    @text.command(name='create', description='Erstelle eine gespeicherte Text-Nachricht')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        title='Name/Identifier der Nachricht',
        channel='Der Ziel-Channel',
        embed='Nachricht als Embed posten',
        colour='Embed-Farbe (red, blue, green, gold, purple, orange oder #RRGGBB)'
    )
    async def create_text(
        self,
        interaction: discord.Interaction,
        title: str,
        channel: discord.TextChannel,
        embed: bool = False,
        colour: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        normalized_title = title.strip()
        if not normalized_title:
            await interaction.response.send_message('❌ Für "create" brauchst du einen Titel!', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute(
                '''
                SELECT 1
                FROM text_messages
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (interaction.guild.id, normalized_title),
            ).fetchone()
        if row is not None:
            await interaction.response.send_message(f'❌ Nachricht "{normalized_title}" existiert bereits!', ephemeral=True)
            return

        await interaction.response.send_modal(
            TextMessageModal(
                cog=self,
                action='create',
                message_title=normalized_title,
                channel_id=channel.id,
                embed=embed,
                colour=colour,
            )
        )

    @text.command(name='edit', description='Bearbeite eine gespeicherte Text-Nachricht')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Name/Identifier der Nachricht')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def edit_text(self, interaction: discord.Interaction, title: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        normalized_title = title.strip()
        if not normalized_title:
            await interaction.response.send_message('❌ Für "edit" brauchst du einen Titel!', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            record = conn.execute(
                '''
                SELECT message_id, message_content
                FROM text_messages
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (interaction.guild.id, normalized_title),
            ).fetchone()

        if record is None:
            await interaction.response.send_message(f'❌ Nachricht "{normalized_title}" nicht gefunden!', ephemeral=True)
            return
        if record['message_id'] is None:
            await interaction.response.send_message(
                f'❌ Nachricht "{normalized_title}" hat keine gespeicherte Message-ID. Bitte neu erstellen.',
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            TextMessageModal(
                cog=self,
                action='edit',
                message_title=normalized_title,
                initial_message=str(record['message_content']),
            )
        )

    @text.command(name='delete', description='Lösche eine gespeicherte Text-Nachricht')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Name/Identifier der Nachricht')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def delete_text(self, interaction: discord.Interaction, title: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        normalized_title = title.strip()
        if not normalized_title:
            await interaction.response.send_message('❌ Für "delete" brauchst du einen Titel!', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            record = conn.execute(
                '''
                SELECT id, channel_id, message_id
                FROM text_messages
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (interaction.guild.id, normalized_title),
            ).fetchone()

            if record is None:
                await interaction.response.send_message(f'❌ Nachricht "{normalized_title}" nicht gefunden!', ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            delete_note = ''

            if record['message_id'] is None:
                delete_note = ' (Discord-Nachricht war nicht gespeichert)'
            else:
                target_channel = await self._resolve_text_channel(interaction.guild, record['channel_id'])
                if target_channel is None:
                    delete_note = ' (Discord-Channel nicht gefunden/zugreifbar)'
                else:
                    try:
                        discord_message = await asyncio.wait_for(
                            target_channel.fetch_message(record['message_id']),
                            timeout=10
                        )
                        await asyncio.wait_for(discord_message.delete(), timeout=10)
                    except asyncio.TimeoutError:
                        delete_note = ' (Timeout beim Löschen der Discord-Nachricht)'
                    except discord.NotFound:
                        delete_note = ' (Discord-Nachricht war bereits gelöscht)'
                    except (discord.Forbidden, discord.HTTPException):
                        delete_note = ' (Discord-Nachricht konnte nicht gelöscht werden)'

            conn.execute('DELETE FROM text_messages WHERE id = ?', (record['id'],))
            conn.commit()

        await interaction.followup.send(f'✅ Nachricht "{normalized_title}" gelöscht!{delete_note}', ephemeral=True)

    @text.command(name='list', description='Liste alle gespeicherten Text-Nachrichten')
    @app_commands.default_permissions(administrator=True)
    async def list_text(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''
                SELECT title
                FROM text_messages
                WHERE guild_id = ?
                ORDER BY title COLLATE NOCASE ASC
                ''',
                (interaction.guild.id,),
            ).fetchall()

        if not rows:
            await interaction.response.send_message('ℹ️ Keine gespeicherten Text-Nachrichten gefunden.', ephemeral=True)
            return

        max_description_length = EMBED_DESCRIPTION_MAX_LENGTH
        lines = [f'• `{row["title"]}`' for row in rows]
        description = '\n'.join(lines)
        if len(description) > max_description_length:
            fitting_lines = []
            for line_index, line in enumerate(lines):
                remaining_after_line = len(lines) - (line_index + 1)
                suffix = f'\n… und {remaining_after_line} weitere' if remaining_after_line > 0 else ''
                candidate_lines = fitting_lines + [line]
                candidate_description = '\n'.join(candidate_lines) + suffix
                if len(candidate_description) > max_description_length:
                    break
                fitting_lines.append(line)
            remaining = len(lines) - len(fitting_lines)
            suffix = f'\n… und {remaining} weitere' if remaining > 0 else ''
            description = '\n'.join(fitting_lines) + suffix

        embed = discord.Embed(
            title='📝 Gespeicherte Nachrichten',
            description=description,
            color=discord.Color.red()
        )
        embed.set_footer(text='Titel = Name/Identifier der Nachricht')
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TextMessages(bot))
