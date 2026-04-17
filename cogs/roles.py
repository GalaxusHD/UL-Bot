import re
import sqlite3
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_FILE

CUSTOM_EMOJI_PATTERN = re.compile(r'^<(a?):([a-zA-Z0-9_]+):(\d+)>$')

STANDARD_EMOJIS = [
    '😀', '😁', '😂', '🤣', '😃', '😄', '😅', '😆', '😉', '😊', '😋', '😎', '😍', '😘',
    '🥰', '😗', '😙', '😚', '🙂', '🤗', '🤔', '😐', '😶', '🙄', '😏', '😣', '😥', '😮',
    '🤐', '😯', '😪', '😫', '🥱', '😴', '😌', '🤓', '🧐', '😛', '😜', '🤪', '🤨', '🫠',
    '🫡', '🤩', '🥳', '😇', '🤠', '🥸', '😈', '👻', '💀', '🤖', '👋', '👌', '👍', '👎',
    '👏', '🙏', '💪', '🫶', '🔥', '⭐', '✨', '💫', '🌈', '🎉', '🎊', '🎯', '🏆', '🥇',
    '🥈', '🥉', '🎮', '🎵', '🎶', '📚', '💼', '🔧', '🧠', '💡', '📢', '✅', '❌', '❓',
    '⚠️', '🔒', '🔓', '📌', '🧪', '🛠️', '🚀', '🌍', '🇨🇭', '💬', '🟢', '🟡', '🔵', '🟣',
    '🔴', '⚫', '⚪', '🟤', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣',
]

ROLE_COLORS = [
    ('blurple', 'Blurple', discord.Color.blurple),
    ('red', 'Red', discord.Color.red),
    ('green', 'Green', discord.Color.green),
    ('blue', 'Blue', discord.Color.blue),
    ('gold', 'Gold', discord.Color.gold),
    ('purple', 'Purple', discord.Color.purple),
    ('orange', 'Orange', discord.Color.orange),
    ('greyple', 'Greyple', discord.Color.greyple),
    ('pink', 'Pink', lambda: discord.Color.from_rgb(255, 105, 180)),
    ('teal', 'Teal', discord.Color.teal),
]
ROLE_COLOR_LABELS = {key: label for key, label, _ in ROLE_COLORS}
ROLE_COLOR_RESOLVERS = {key: resolver for key, _, resolver in ROLE_COLORS}


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


@dataclass(slots=True)
class DraftRoleEntry:
    role_id: int
    emoji_key: str
    display_emoji: str
    color_key: str = 'blurple'


@dataclass(slots=True)
class RolePanelDraft:
    guild_id: int
    title: str
    channel_id: int
    message_id: int | None = None
    role_message_id: int | None = None
    entries: list[DraftRoleEntry] = field(default_factory=list)


class RoleEntryEmojiSelect(discord.ui.Select['RoleEntryPickerView']):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder='Emoji auswählen', min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.selected_emoji = self.values[0]
        await interaction.response.defer()


class RoleEntryRoleSelect(discord.ui.RoleSelect['RoleEntryPickerView']):
    def __init__(self) -> None:
        super().__init__(placeholder='Rolle auswählen', min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values:
            self.view.selected_role = self.values[0]
        await interaction.response.defer()


class RoleEntryPickerView(discord.ui.View):
    def __init__(self, guild: discord.Guild, draft: RolePanelDraft, builder: 'RolePanelBuilderView') -> None:
        super().__init__(timeout=300)
        self.guild = guild
        self.draft = draft
        self.builder = builder
        self.selected_role: discord.Role | None = None
        self.selected_emoji: str | None = None
        self.selected_color: str = draft.entries[-1].color_key if draft.entries else 'blurple'
        self.source: str = 'standard'
        self.page: int = 0
        self._rebuild_components()

    @property
    def source_items(self) -> list[str]:
        if self.source == 'custom':
            return [str(emoji) for emoji in self.guild.emojis]
        return STANDARD_EMOJIS

    @property
    def page_count(self) -> int:
        items = self.source_items
        if not items:
            return 1
        return ((len(items) - 1) // 25) + 1

    def _rebuild_components(self) -> None:
        previous_role = self.selected_role
        self.clear_items()
        self.add_item(RoleEntryRoleSelect())

        items = self.source_items
        start = self.page * 25
        page_items = items[start:start + 25]
        if not page_items:
            options = [discord.SelectOption(label='Keine Emojis verfügbar', value='❌', emoji='❌')]
        else:
            options = [
                discord.SelectOption(label=f'{emoji} #{start + index + 1}', value=emoji, emoji=emoji)
                for index, emoji in enumerate(page_items)
            ]
        self.add_item(RoleEntryEmojiSelect(options=options))
        self.add_item(self.switch_source_button)
        self.add_item(self.color_button)
        self.add_item(self.prev_page_button)
        self.add_item(self.next_page_button)
        self.add_item(self.save_button)
        self.add_item(self.cancel_button)
        self.switch_source_button.label = f'Emoji-Quelle: {'Standard' if self.source == 'standard' else 'Server'}'
        self.color_button.label = f'Farbe: {ROLE_COLOR_LABELS.get(self.selected_color, "Blurple")}'

        if previous_role is not None:
            self.selected_role = previous_role

    @discord.ui.button(label='Emoji-Quelle: Standard', style=discord.ButtonStyle.secondary, row=2)
    async def switch_source_button(self, interaction: discord.Interaction, _: discord.ui.Button['RoleEntryPickerView']) -> None:
        self.source = 'custom' if self.source == 'standard' else 'standard'
        self.page = 0
        self._rebuild_components()
        await interaction.response.edit_message(
            content=f'Rolle + Emoji wählen (Seite {self.page + 1}/{self.page_count})',
            view=self,
        )

    @discord.ui.button(label='Farbe: Blurple', style=discord.ButtonStyle.secondary, row=2)
    async def color_button(self, interaction: discord.Interaction, _: discord.ui.Button['RoleEntryPickerView']) -> None:
        keys = [key for key, _, _ in ROLE_COLORS]
        try:
            next_index = (keys.index(self.selected_color) + 1) % len(keys)
        except ValueError:
            next_index = 0
        self.selected_color = keys[next_index]
        self._rebuild_components()
        await interaction.response.edit_message(
            content=f'Rolle + Emoji wählen (Seite {self.page + 1}/{self.page_count})',
            view=self,
        )

    @discord.ui.button(label='◀', style=discord.ButtonStyle.secondary, row=2)
    async def prev_page_button(self, interaction: discord.Interaction, _: discord.ui.Button['RoleEntryPickerView']) -> None:
        self.page = (self.page - 1) % self.page_count
        self._rebuild_components()
        await interaction.response.edit_message(
            content=f'Rolle + Emoji wählen (Seite {self.page + 1}/{self.page_count})',
            view=self,
        )

    @discord.ui.button(label='▶', style=discord.ButtonStyle.secondary, row=2)
    async def next_page_button(self, interaction: discord.Interaction, _: discord.ui.Button['RoleEntryPickerView']) -> None:
        self.page = (self.page + 1) % self.page_count
        self._rebuild_components()
        await interaction.response.edit_message(
            content=f'Rolle + Emoji wählen (Seite {self.page + 1}/{self.page_count})',
            view=self,
        )

    @discord.ui.button(label='Hinzufügen', style=discord.ButtonStyle.success, row=2)
    async def save_button(self, interaction: discord.Interaction, _: discord.ui.Button['RoleEntryPickerView']) -> None:
        if self.selected_role is None:
            await interaction.response.send_message('❌ Bitte zuerst eine Rolle auswählen.', ephemeral=True)
            return
        if not self.selected_emoji:
            await interaction.response.send_message('❌ Bitte zuerst ein Emoji auswählen.', ephemeral=True)
            return

        emoji_key, display_emoji = normalise_emoji(self.selected_emoji)
        if any(entry.emoji_key == emoji_key for entry in self.draft.entries):
            await interaction.response.send_message('❌ Dieses Emoji wird bereits verwendet.', ephemeral=True)
            return
        if any(entry.role_id == self.selected_role.id for entry in self.draft.entries):
            await interaction.response.send_message('❌ Diese Rolle wurde bereits hinzugefügt.', ephemeral=True)
            return

        self.draft.entries.append(
            DraftRoleEntry(
                role_id=self.selected_role.id,
                emoji_key=emoji_key,
                display_emoji=display_emoji,
                color_key=self.selected_color,
            )
        )
        await interaction.response.edit_message(content='✅ Eintrag hinzugefügt.', view=None)
        await self.builder.refresh()
        self.stop()

    @discord.ui.button(label='Abbrechen', style=discord.ButtonStyle.danger, row=2)
    async def cancel_button(self, interaction: discord.Interaction, _: discord.ui.Button['RoleEntryPickerView']) -> None:
        await interaction.response.edit_message(content='Abgebrochen.', view=None)
        self.stop()


class RolePanelBuilderView(discord.ui.View):
    def __init__(self, cog: 'Roles', draft: RolePanelDraft) -> None:
        super().__init__(timeout=1800)
        self.cog = cog
        self.draft = draft
        self.message: discord.InteractionMessage | None = None

    def _render_overview(self) -> str:
        lines = [
            f'**Titel:** {self.draft.title}',
            f'**Channel:** <#{self.draft.channel_id}>',
            '',
        ]
        if not self.draft.entries:
            lines.append('Noch keine Rollen hinzugefügt. Nutze **Rolle hinzufügen** (unbegrenzt).')
        else:
            lines.append('Aktuelle Rollen:')
            for entry in self.draft.entries:
                lines.append(
                    f'- {entry.display_emoji} <@&{entry.role_id}> '
                    f'({ROLE_COLOR_LABELS.get(entry.color_key, "Blurple")})'
                )
        return '\n'.join(lines)

    async def refresh(self) -> None:
        if self.message is not None:
            await self.message.edit(content=self._render_overview(), view=self)

    @discord.ui.button(label='Rolle hinzufügen', style=discord.ButtonStyle.primary)
    async def add_role_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelBuilderView']) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message('❌ Guild-Kontext fehlt.', ephemeral=True)
            return

        picker = RoleEntryPickerView(guild=guild, draft=self.draft, builder=self)
        await interaction.response.send_message(
            f'Rolle + Emoji wählen (Seite {picker.page + 1}/{picker.page_count})',
            view=picker,
            ephemeral=True,
        )

    @discord.ui.button(label='Letzte Rolle entfernen', style=discord.ButtonStyle.secondary)
    async def remove_last_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelBuilderView']) -> None:
        if not self.draft.entries:
            await interaction.response.send_message('❌ Es gibt keine Rollen zum Entfernen.', ephemeral=True)
            return
        removed = self.draft.entries.pop()
        await interaction.response.send_message(
            f'🗑️ Entfernt: {removed.display_emoji} <@&{removed.role_id}>',
            ephemeral=True,
        )
        await self.refresh()

    @discord.ui.button(label='Speichern', style=discord.ButtonStyle.success)
    async def publish_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelBuilderView']) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Guild-Kontext fehlt.', ephemeral=True)
            return
        if not self.draft.entries:
            await interaction.response.send_message('❌ Bitte mindestens eine Rolle hinzufügen.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if self.draft.role_message_id is None:
                message = await self.cog._create_panel_message(interaction.guild, self.draft)
                self.cog._insert_role_panel(self.draft, message.id)
                result_text = f'✅ Rollen-Auswahl erstellt: {message.jump_url}'
            else:
                message = await self.cog._update_panel_message(interaction.guild, self.draft)
                self.cog._update_role_panel_entries(self.draft)
                result_text = f'✅ Rollen-Auswahl aktualisiert: {message.jump_url}'

            for component in self.children:
                component.disabled = True
            await interaction.edit_original_response(content=f'{self._render_overview()}\n\n{result_text}', view=self)
            self.stop()
        except (discord.HTTPException, discord.Forbidden):
            await interaction.followup.send('❌ Discord-Nachricht konnte nicht gespeichert werden.', ephemeral=True)
        except sqlite3.DatabaseError:
            await interaction.followup.send('❌ Datenbankfehler beim Speichern der Rollen-Auswahl.', ephemeral=True)

    @discord.ui.button(label='Abbrechen', style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, _: discord.ui.Button['RolePanelBuilderView']) -> None:
        await interaction.response.edit_message(content='Rollen-Auswahl abgebrochen.', view=None)
        self.stop()


class Roles(commands.Cog):
    role = app_commands.Group(name='role', description='Rollen-System')

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _conn() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_panel_by_title(self, guild_id: int, title: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                '''
                SELECT id, guild_id, title, channel_id, message_id
                FROM role_messages
                WHERE guild_id = ? AND LOWER(title) = LOWER(?)
                LIMIT 1
                ''',
                (guild_id, title),
            ).fetchone()

    def _get_panel_entries(self, role_message_id: int) -> list[DraftRoleEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                '''
                SELECT role_id, emoji, display_emoji
                     , COALESCE(color, 'blurple') AS color
                FROM role_message_roles
                WHERE role_message_id = ?
                ORDER BY position ASC
                ''',
                (role_message_id,),
            ).fetchall()
        return [
            DraftRoleEntry(
                role_id=int(row['role_id']),
                emoji_key=str(row['emoji']),
                display_emoji=str(row['display_emoji']),
                color_key=str(row['color']),
            )
            for row in rows
        ]

    @staticmethod
    def _panel_embed(draft: RolePanelDraft) -> discord.Embed:
        embed = discord.Embed(
            title=draft.title,
            description='\n'.join(f'{entry.display_emoji} • <@&{entry.role_id}>' for entry in draft.entries),
            color=ROLE_COLOR_RESOLVERS.get(
                draft.entries[0].color_key if draft.entries else 'blurple',
                discord.Color.blurple,
            )(),
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

    async def _update_panel_message(self, guild: discord.Guild, draft: RolePanelDraft) -> discord.Message:
        channel = guild.get_channel(draft.channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise discord.NotFound(response=None, message='Channel not found')
        if draft.message_id is None:
            raise discord.NotFound(response=None, message='Message id missing')

        message = await channel.fetch_message(draft.message_id)
        await message.edit(embed=self._panel_embed(draft))
        try:
            await message.clear_reactions()
        except (discord.Forbidden, discord.HTTPException):
            pass
        for entry in draft.entries:
            await message.add_reaction(entry.display_emoji)
        return message

    def _insert_role_panel(self, draft: RolePanelDraft, message_id: int) -> None:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO role_messages (guild_id, title, channel_id, message_id) VALUES (?, ?, ?, ?)',
                (draft.guild_id, draft.title, draft.channel_id, message_id),
            )
            role_message_id = cursor.lastrowid
            for position, entry in enumerate(draft.entries, start=1):
                cursor.execute(
                    '''
                    INSERT INTO role_message_roles (role_message_id, role_id, emoji, display_emoji, color, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (role_message_id, entry.role_id, entry.emoji_key, entry.display_emoji, entry.color_key, position),
                )
            conn.commit()

    def _update_role_panel_entries(self, draft: RolePanelDraft) -> None:
        if draft.role_message_id is None or draft.message_id is None:
            return
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE role_messages SET channel_id = ?, message_id = ? WHERE id = ?',
                (draft.channel_id, draft.message_id, draft.role_message_id),
            )
            cursor.execute('DELETE FROM role_message_roles WHERE role_message_id = ?', (draft.role_message_id,))
            for position, entry in enumerate(draft.entries, start=1):
                cursor.execute(
                    '''
                    INSERT INTO role_message_roles (role_message_id, role_id, emoji, display_emoji, color, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        draft.role_message_id,
                        entry.role_id,
                        entry.emoji_key,
                        entry.display_emoji,
                        entry.color_key,
                        position,
                    ),
                )
            conn.commit()

    async def _title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        like_value = f'%{current.strip()}%'
        with self._conn() as conn:
            rows = conn.execute(
                '''
                SELECT title
                FROM role_messages
                WHERE guild_id = ? AND title LIKE ? COLLATE NOCASE
                ORDER BY title COLLATE NOCASE ASC
                LIMIT 25
                ''',
                (interaction.guild.id, like_value),
            ).fetchall()
        return [app_commands.Choice(name=str(row['title']), value=str(row['title'])) for row in rows]

    @role.command(name='setup', description='Erstelle eine Rollen-Auswahl')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel/Name der Rollen-Auswahl', channel='Channel für die Rollen-Auswahl')
    async def setup_role_selector(
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

        if self._get_panel_by_title(interaction.guild.id, title.strip()) is not None:
            await interaction.response.send_message('❌ Eine Rollen-Auswahl mit diesem Titel existiert bereits.', ephemeral=True)
            return

        draft = RolePanelDraft(guild_id=interaction.guild.id, title=title.strip(), channel_id=channel.id)
        view = RolePanelBuilderView(cog=self, draft=draft)
        await interaction.response.send_message(view._render_overview(), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @role.command(name='edit', description='Bearbeite eine bestehende Rollen-Auswahl')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel/Name der Rollen-Auswahl')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def edit_role_selector(self, interaction: discord.Interaction, title: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        panel = self._get_panel_by_title(interaction.guild.id, title.strip())
        if panel is None:
            await interaction.response.send_message('❌ Rollen-Auswahl nicht gefunden.', ephemeral=True)
            return

        entries = self._get_panel_entries(int(panel['id']))
        draft = RolePanelDraft(
            guild_id=interaction.guild.id,
            title=str(panel['title']),
            channel_id=int(panel['channel_id']),
            message_id=int(panel['message_id']),
            role_message_id=int(panel['id']),
            entries=entries,
        )

        view = RolePanelBuilderView(cog=self, draft=draft)
        await interaction.response.send_message(view._render_overview(), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @role.command(name='delete', description='Lösche eine Rollen-Auswahl')
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(title='Titel/Name der Rollen-Auswahl')
    @app_commands.autocomplete(title=_title_autocomplete)
    async def delete_role_selector(self, interaction: discord.Interaction, title: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
            return

        panel = self._get_panel_by_title(interaction.guild.id, title.strip())
        if panel is None:
            await interaction.response.send_message('❌ Rollen-Auswahl nicht gefunden.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(int(panel['channel_id']))
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(int(panel['message_id']))
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        with self._conn() as conn:
            conn.execute('DELETE FROM role_messages WHERE id = ?', (int(panel['id']),))
            conn.commit()

        await interaction.followup.send('✅ Rollen-Auswahl gelöscht.', ephemeral=True)

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
                SELECT rmr.role_id
                FROM role_messages rm
                JOIN role_message_roles rmr ON rmr.role_message_id = rm.id
                WHERE rm.guild_id = ? AND rm.message_id = ? AND rmr.emoji = ?
                LIMIT 1
                ''',
                (payload.guild_id, payload.message_id, emoji_key),
            ).fetchone()

        if row is None:
            return

        role = guild.get_role(int(row['role_id']))
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
