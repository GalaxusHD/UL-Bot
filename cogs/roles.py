import re
import sqlite3
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

CUSTOM_EMOJI_PATTERN = re.compile(r'^<(a?):([a-zA-Z0-9_]+):(\d+)>$')
SYMBOL_EMOJIS = [
    '✅', '❌', '⭕', '⚫', '⚪', '📍', '✔️', '❎', '✖️', '⭐',
    '💫', '🔔', '🔕', '📢', '📣', '❓', '❔', '⚠️', '🆘', '💯',
]
COLOR_EMOJIS = [
    '🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '🟤', '⚫', '⚪',
    '🟥', '🟧', '🟨', '🟩', '🟦', '🟪', '🟫', '⬛', '⬜',
]
EMOJI_CATEGORIES = [
    ('Symbole', SYMBOL_EMOJIS),
    ('Farben', COLOR_EMOJIS),
]
NAMED_COLOURS: dict[str, discord.Colour] = {
    'blurple': discord.Colour.blurple(),
    'red': discord.Colour.red(),
    'blue': discord.Colour.blue(),
    'green': discord.Colour.green(),
    'gold': discord.Colour.gold(),
    'purple': discord.Colour.purple(),
    'orange': discord.Colour.orange(),
}


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


def parse_embed_colour(raw_value: str | None) -> tuple[str, discord.Colour] | None:
    normalised = (raw_value or '').strip()
    if not normalised:
        return 'blurple', discord.Colour.blurple()
    if re.fullmatch(r'#[0-9A-Fa-f]{6}', normalised):
        return normalised.upper(), discord.Colour(int(normalised[1:], 16))
    colour = NAMED_COLOURS.get(normalised.lower())
    if colour is None:
        return None
    return normalised.lower(), colour


@dataclass(slots=True)
class DraftRoleEntry:
    role_id: int
    emoji_key: str
    display_emoji: str


@dataclass(slots=True)
class RolePanelDraft:
    guild_id: int
    title: str
    channel_id: int
    description: str
    embed_colour: str = 'blurple'
    panel_id: int | None = None
    message_id: int | None = None
    entries: list[DraftRoleEntry] = field(default_factory=list)


class RoleSelector(discord.ui.RoleSelect['RolePanelSetupView']):
    def __init__(self, selected_role: discord.Role | None = None) -> None:
        super().__init__(placeholder='Rolle auswählen (durchsuchbar)', min_values=1, max_values=1, row=0)
        if selected_role is not None:
            self.default_values = [selected_role]

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values:
            self.view.selected_role = self.values[0]
            self.view.selected_role_id = self.values[0].id
        await interaction.response.defer()


class EmojiSelector(discord.ui.Select['RolePanelSetupView']):
    def __init__(self, options: list[discord.SelectOption], category_name: str) -> None:
        super().__init__(placeholder=f'Emoji auswählen ({category_name})', min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.selected_emoji = self.values[0]
        await interaction.response.defer()


class EntryRemoveSelector(discord.ui.Select['RolePanelSetupView']):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder='Eintrag zum Entfernen auswählen', min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_raw = self.values[0]
        self.view.selected_remove_index = int(selected_raw)
        await interaction.response.defer()


class RolePanelSetupView(discord.ui.View):
    def __init__(self, cog: 'Roles', guild: discord.Guild, draft: RolePanelDraft) -> None:
        super().__init__(timeout=1800)
        self.cog = cog
        self.guild = guild
        self.draft = draft
        self.selected_role: discord.Role | None = None
        self.selected_role_id: int | None = None
        self.selected_emoji: str | None = None
        self.selected_remove_index: int | None = None
        self.page: int = 0
        self.message: discord.InteractionMessage | None = None
        self._rebuild_components()

    @property
    def source_items(self) -> list[str]:
        _, items = EMOJI_CATEGORIES[self.page]
        return items

    @property
    def page_count(self) -> int:
        return len(EMOJI_CATEGORIES)

    def _rebuild_components(self) -> None:
        self.clear_items()
        selected_role = self.guild.get_role(self.selected_role_id) if self.selected_role_id else None
        if selected_role is not None:
            self.selected_role = selected_role
        self.add_item(RoleSelector(selected_role=selected_role))

        items = self.source_items
        page_items = items[:25]
        category_name, _ = EMOJI_CATEGORIES[self.page]
        if not page_items:
            emoji_options = [discord.SelectOption(label='Keine Emojis verfügbar', value='❌', emoji='❌')]
        else:
            emoji_options = [
                discord.SelectOption(
                    label=f'{emoji} #{index + 1}',
                    value=emoji,
                    emoji=emoji,
                    default=self.selected_emoji == emoji,
                )
                for index, emoji in enumerate(page_items)
            ]
        self.add_item(EmojiSelector(options=emoji_options, category_name=category_name))

        remove_options = [
            discord.SelectOption(
                label=f'{entry.display_emoji} Rolle {position}: {entry.role_id}',
                value=str(position - 1),
                emoji=entry.display_emoji,
                default=self.selected_remove_index == (position - 1),
            )
            for position, entry in enumerate(self.draft.entries, start=1)
        ]
        if remove_options:
            self.add_item(EntryRemoveSelector(options=remove_options[:25]))

        self.add_item(self.prev_page_button)
        self.add_item(self.next_page_button)
        self.add_item(self.add_button)
        self.add_item(self.remove_button)
        self.add_item(self.save_button)
        self.add_item(self.cancel_button)

        self.remove_button.disabled = not self.draft.entries
        self.prev_page_button.disabled = self.page_count <= 1
        self.next_page_button.disabled = self.page_count <= 1
        self.prev_page_button.label = '◀ Symbole' if self.page == 1 else '◀'
        self.next_page_button.label = 'Farben ▶' if self.page == 0 else '▶'

    def _render_overview(self) -> str:
        mode_text = 'Bearbeiten' if self.draft.panel_id is not None else 'Erstellen'
        lines = [
            f'**Modus:** {mode_text}',
            f'**Titel:** {self.draft.title}',
            f'**Channel:** <#{self.draft.channel_id}>',
            f'**Beschreibung:** {self.draft.description or "-"}',
            f'**Embed-Farbe:** {self.draft.embed_colour}',
            '',
            '**Ausgewählte Rollen:**',
        ]
        if not self.draft.entries:
            lines.append('Noch keine Rollen hinzugefügt.')
        else:
            for position, entry in enumerate(self.draft.entries, start=1):
                lines.append(f'{position}. {entry.display_emoji} <@&{entry.role_id}>')
        return '\n'.join(lines)

    @discord.ui.button(label='◀', style=discord.ButtonStyle.secondary, row=3)
    async def prev_page_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelSetupView']) -> None:
        self.page = (self.page - 1) % self.page_count
        self._rebuild_components()
        await interaction.response.edit_message(content=self._render_overview(), view=self)

    @discord.ui.button(label='▶', style=discord.ButtonStyle.secondary, row=3)
    async def next_page_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelSetupView']) -> None:
        self.page = (self.page + 1) % self.page_count
        self._rebuild_components()
        await interaction.response.edit_message(content=self._render_overview(), view=self)

    @discord.ui.button(label='+ Hinzufügen', style=discord.ButtonStyle.success, row=4)
    async def add_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelSetupView']) -> None:
        selected_role = self.guild.get_role(self.selected_role_id) if self.selected_role_id else self.selected_role
        if selected_role is None:
            await interaction.response.send_message('❌ Bitte zuerst eine Rolle auswählen.', ephemeral=True)
            return
        if not self.selected_emoji:
            await interaction.response.send_message('❌ Bitte zuerst ein Emoji auswählen.', ephemeral=True)
            return

        emoji_key, display_emoji = normalise_emoji(self.selected_emoji)
        if any(entry.emoji_key == emoji_key for entry in self.draft.entries):
            await interaction.response.send_message('❌ Dieses Emoji wird bereits verwendet.', ephemeral=True)
            return
        if any(entry.role_id == selected_role.id for entry in self.draft.entries):
            await interaction.response.send_message('❌ Diese Rolle wurde bereits hinzugefügt.', ephemeral=True)
            return

        self.draft.entries.append(
            DraftRoleEntry(
                role_id=selected_role.id,
                emoji_key=emoji_key,
                display_emoji=display_emoji,
            )
        )
        self.selected_remove_index = len(self.draft.entries) - 1
        self._rebuild_components()
        await interaction.response.edit_message(content=self._render_overview(), view=self)

    @discord.ui.button(label='Entfernen', style=discord.ButtonStyle.secondary, row=4)
    async def remove_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelSetupView']) -> None:
        if not self.draft.entries:
            await interaction.response.send_message('❌ Es gibt keine Rollen zum Entfernen.', ephemeral=True)
            return
        if self.selected_remove_index is None:
            await interaction.response.send_message('❌ Bitte zuerst einen Eintrag im Entfernen-Dropdown wählen.', ephemeral=True)
            return
        if self.selected_remove_index < 0 or self.selected_remove_index >= len(self.draft.entries):
            await interaction.response.send_message('❌ Ungültiger Eintrag gewählt.', ephemeral=True)
            return

        self.draft.entries.pop(self.selected_remove_index)
        self.selected_remove_index = None
        self._rebuild_components()
        await interaction.response.edit_message(content=self._render_overview(), view=self)

    @discord.ui.button(label='Speichern', style=discord.ButtonStyle.primary, row=4)
    async def save_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelSetupView']) -> None:
        role_count = sum(1 for entry in self.draft.entries if entry.role_id is not None and entry.emoji_key != '')
        if role_count < 1:
            await interaction.response.send_message('❌ Bitte mindestens eine Rolle hinzufügen.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            if self.draft.panel_id is None:
                message = await self.cog._create_panel_message(self.guild, self.draft)
                self.cog._insert_role_panel(self.draft, message.id)
                success_text = '✅ Rollen-Auswahl erstellt'
            else:
                message = await self.cog._update_role_panel(self.guild, self.draft)
                success_text = '✅ Rollen-Auswahl aktualisiert'
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send('❌ Discord-Nachricht konnte nicht gespeichert werden.', ephemeral=True)
            return
        except sqlite3.DatabaseError:
            await interaction.followup.send('❌ Datenbankfehler beim Speichern der Rollen-Auswahl.', ephemeral=True)
            return

        for component in self.children:
            component.disabled = True
        await interaction.edit_original_response(
            content=f'{self._render_overview()}\n\n{success_text}: {message.jump_url}',
            view=self,
        )
        self.stop()

    @discord.ui.button(label='Abbrechen', style=discord.ButtonStyle.danger, row=4)
    async def cancel_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelSetupView']) -> None:
        await interaction.response.edit_message(content='Rollen-Auswahl abgebrochen.', view=None)
        self.stop()


class RoleSetupModal(discord.ui.Modal, title='Rollen-Setup'):
    def __init__(self, cog: 'Roles', guild: discord.Guild, draft: RolePanelDraft) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.draft = draft
        self.description = discord.ui.TextInput(
            label='Beschreibung',
            placeholder='Beschreibung für das Rollen-Panel',
            required=False,
            max_length=1000,
            style=discord.TextStyle.paragraph,
            default=draft.description,
        )
        self.embed_colour = discord.ui.TextInput(
            label='Embed-Farbe (Name oder #RRGGBB)',
            placeholder='blurple oder #FF5733',
            required=False,
            max_length=7,
            default=draft.embed_colour,
        )
        self.add_item(self.description)
        self.add_item(self.embed_colour)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed_colour = parse_embed_colour(str(self.embed_colour.value).strip())
        if parsed_colour is None:
            await interaction.response.send_message(
                '❌ Ungültige Farbe. Nutze z. B. "blurple" oder "#FF5733".',
                ephemeral=True,
            )
            return

        colour_key, _ = parsed_colour
        self.draft.description = str(self.description.value).strip()
        self.draft.embed_colour = colour_key

        draft = self.draft
        view = RolePanelSetupView(cog=self.cog, guild=self.guild, draft=draft)
        await interaction.response.send_message(view._render_overview(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _conn() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

    def _title_exists(self, guild_id: int, title: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                '''
                SELECT 1
                FROM role_messages
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (guild_id, title),
            ).fetchone()
        return row is not None

    async def _title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                '''
                SELECT title
                FROM role_messages
                WHERE guild_id = ? AND title LIKE ? COLLATE NOCASE
                ORDER BY title COLLATE NOCASE ASC
                LIMIT 25
                ''',
                (interaction.guild.id, f'%{current.strip()}%'),
            ).fetchall()
        return [app_commands.Choice(name=str(row['title']), value=str(row['title'])) for row in rows]

    def _load_panel_draft(self, guild_id: int, title: str) -> RolePanelDraft | None:
        with self._conn() as conn:
            panel_row = conn.execute(
                '''
                SELECT id, guild_id, title, channel_id, message_id, description, color
                FROM role_messages
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (guild_id, title),
            ).fetchone()
            if panel_row is None:
                return None

            role_rows = conn.execute(
                '''
                SELECT role_id, emoji, display_emoji
                FROM role_message_roles
                WHERE role_message_id = ?
                ORDER BY position ASC
                ''',
                (int(panel_row['id']),),
            ).fetchall()

        return RolePanelDraft(
            guild_id=int(panel_row['guild_id']),
            title=str(panel_row['title']),
            channel_id=int(panel_row['channel_id']),
            description=str(panel_row['description'] or ''),
            embed_colour=(parse_embed_colour(str(panel_row['color'] or 'blurple')) or ('blurple', discord.Color.blurple()))[0],
            panel_id=int(panel_row['id']),
            message_id=int(panel_row['message_id']),
            entries=[
                DraftRoleEntry(
                    role_id=int(row['role_id']),
                    emoji_key=str(row['emoji']),
                    display_emoji=str(row['display_emoji']),
                )
                for row in role_rows
            ],
        )

    def _panel_embed(self, draft: RolePanelDraft) -> discord.Embed:
        role_lines = '\n'.join(f'{entry.display_emoji} • <@&{entry.role_id}>' for entry in draft.entries)
        description_blocks = [draft.description.strip()] if draft.description.strip() else []
        description_blocks.append(role_lines)
        parsed_colour = parse_embed_colour(draft.embed_colour)
        embed_colour = parsed_colour[1] if parsed_colour is not None else discord.Color.blurple()
        embed = discord.Embed(
            title=draft.title,
            description='\n\n'.join(description_blocks),
            color=embed_colour,
        )
        embed.set_footer(text='Reagiere, um Rollen zu erhalten oder zu entfernen.')
        return embed

    async def _create_panel_message(self, guild: discord.Guild, draft: RolePanelDraft) -> discord.Message:
        channel = guild.get_channel(draft.channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise discord.NotFound(response=None, message='Channel not found')
        message = await channel.send(embed=self._panel_embed(draft))
        try:
            for entry in draft.entries:
                await message.add_reaction(entry.display_emoji)
        except (discord.Forbidden, discord.HTTPException):
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
            raise
        return message

    def _insert_role_panel(self, draft: RolePanelDraft, message_id: int) -> None:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO role_messages (guild_id, title, channel_id, message_id, description, color)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (draft.guild_id, draft.title, draft.channel_id, message_id, draft.description, draft.embed_colour),
            )
            role_message_id = cursor.lastrowid
            for position, entry in enumerate(draft.entries, start=1):
                cursor.execute(
                    '''
                    INSERT INTO role_message_roles (role_message_id, role_id, emoji, display_emoji, color, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (role_message_id, entry.role_id, entry.emoji_key, entry.display_emoji, draft.embed_colour, position),
                )
            conn.commit()

    async def _update_role_panel(self, guild: discord.Guild, draft: RolePanelDraft) -> discord.Message:
        if draft.panel_id is None:
            raise ValueError('panel_id is required for updates')

        channel = guild.get_channel(draft.channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise discord.NotFound(response=None, message='Channel not found')

        message: discord.Message | None = None
        if draft.message_id is not None:
            try:
                message = await channel.fetch_message(draft.message_id)
            except discord.NotFound:
                message = None

        if message is None:
            message = await channel.send(embed=self._panel_embed(draft))
        else:
            await message.edit(embed=self._panel_embed(draft))

        await message.clear_reactions()
        for entry in draft.entries:
            await message.add_reaction(entry.display_emoji)

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE role_messages
                SET channel_id = ?, message_id = ?, description = ?, color = ?
                WHERE id = ?
                ''',
                (draft.channel_id, message.id, draft.description, draft.embed_colour, draft.panel_id),
            )
            cursor.execute('DELETE FROM role_message_roles WHERE role_message_id = ?', (draft.panel_id,))
            for position, entry in enumerate(draft.entries, start=1):
                cursor.execute(
                    '''
                    INSERT INTO role_message_roles (role_message_id, role_id, emoji, display_emoji, color, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (draft.panel_id, entry.role_id, entry.emoji_key, entry.display_emoji, draft.embed_colour, position),
                )
            conn.commit()

        return message

    @app_commands.command(name='role', description='Erstelle eine Rollen-Auswahl')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel der Rollen-Auswahl', channel='Channel für die Rollen-Auswahl')
    async def role_command(self, interaction: discord.Interaction, title: str, channel: discord.TextChannel) -> None:
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
        if self._title_exists(interaction.guild.id, clean_title):
            await interaction.response.send_message('❌ Eine Rollen-Auswahl mit diesem Titel existiert bereits.', ephemeral=True)
            return

        draft = RolePanelDraft(
            guild_id=interaction.guild.id,
            title=clean_title,
            channel_id=channel.id,
            description='',
        )
        modal = RoleSetupModal(cog=self, guild=interaction.guild, draft=draft)
        await interaction.response.send_modal(modal)

    @app_commands.command(name='role_edit', description='Bearbeite eine bestehende Rollen-Auswahl')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel der Rollen-Auswahl')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def role_edit_command(self, interaction: discord.Interaction, title: str) -> None:
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

        draft = self._load_panel_draft(interaction.guild.id, clean_title)
        if draft is None:
            await interaction.response.send_message('❌ Rollen-Auswahl nicht gefunden.', ephemeral=True)
            return

        modal = RoleSetupModal(cog=self, guild=interaction.guild, draft=draft)
        await interaction.response.send_modal(modal)

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

        with self._conn() as conn:
            row = conn.execute(
                '''
                SELECT rm.id AS role_message_id, rm.channel_id, rmr.role_id
                FROM role_messages rm
                JOIN role_message_roles rmr ON rmr.role_message_id = rm.id
                WHERE rm.guild_id = ? AND rm.message_id = ? AND rmr.emoji = ?
                LIMIT 1
                ''',
                (payload.guild_id, payload.message_id, emoji_key),
            ).fetchone()
            if row is None:
                return

            panel_roles = conn.execute(
                '''
                SELECT role_id, emoji, display_emoji
                FROM role_message_roles
                WHERE role_message_id = ?
                ORDER BY position ASC
                ''',
                (int(row['role_message_id']),),
            ).fetchall()

        if not panel_roles:
            return

        role = guild.get_role(int(row['role_id']))
        if role is None:
            return

        try:
            if add_role:
                channel = guild.get_channel(int(row['channel_id']))
                if isinstance(channel, discord.TextChannel):
                    try:
                        message = await channel.fetch_message(payload.message_id)
                        for panel_role in panel_roles:
                            panel_emoji = str(panel_role['emoji'])
                            if panel_emoji == emoji_key:
                                continue
                            try:
                                await message.remove_reaction(str(panel_role['display_emoji']), member)
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                continue
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

                roles_to_remove: list[discord.Role] = []
                for panel_role in panel_roles:
                    panel_role_id = int(panel_role['role_id'])
                    if panel_role_id == role.id:
                        continue
                    maybe_role = guild.get_role(panel_role_id)
                    if maybe_role is not None and maybe_role in member.roles:
                        roles_to_remove.append(maybe_role)
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason='Role selector exclusive reaction')
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
