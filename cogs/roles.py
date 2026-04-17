from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import re
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import Database, RolePanelEntry


STANDARD_EMOJIS = [
    "😀", "😁", "😂", "🤣", "😃", "😄", "😅", "😆", "😉", "😊", "😋", "😎", "😍", "😘",
    "🥰", "😗", "😙", "😚", "🙂", "🤗", "🤔", "😐", "😶", "🙄", "😏", "😣", "😥", "😮",
    "🤐", "😯", "😪", "😫", "🥱", "😴", "😌", "🤓", "🧐", "😛", "😜", "🤪", "🤨", "🫠",
    "🫡", "🤩", "🥳", "😇", "🤠", "🥸", "😈", "👻", "💀", "🤖", "👋", "👌", "👍", "👎",
    "👏", "🙏", "💪", "🫶", "🔥", "⭐", "✨", "💫", "🌈", "🎉", "🎊", "🎯", "🏆", "🥇",
    "🥈", "🥉", "🎮", "🎵", "🎶", "📚", "💼", "🔧", "🧠", "💡", "📢", "✅", "❌", "❓",
    "⚠️", "🔒", "🔓", "📌", "🧪", "🛠️", "🚀", "🌍", "🇨🇭", "💬", "🟢", "🟡", "🔵", "🟣",
    "🔴", "⚫", "⚪", "🟤", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣",
]


def parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "on", "1"}:
        return True
    if normalized in {"false", "no", "n", "off", "0"}:
        return False
    return None


def emoji_matches(stored: str, raw: discord.PartialEmoji) -> bool:
    if raw.id is None:
        return stored == raw.name
    return stored.endswith(f":{raw.id}>")


@dataclass(slots=True)
class DraftRoleEntry:
    role_id: int
    emoji: str


@dataclass(slots=True)
class RolePanelDraft:
    guild_id: int
    channel_id: int
    title: str
    multi_role: bool
    entries: list[DraftRoleEntry] = field(default_factory=list)


class EmojiPickerSelect(discord.ui.Select["RolePickerView"]):
    def __init__(self, options: Iterable[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Choose an emoji",
            min_values=1,
            max_values=1,
            options=list(options),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values:
            return
        self.view.selected_emoji = self.values[0]
        await interaction.response.defer()


class RolePickerView(discord.ui.View):
    def __init__(self, guild: discord.Guild, draft: RolePanelDraft, builder: "RoleBuilderView") -> None:
        super().__init__(timeout=300)
        self.guild = guild
        self.draft = draft
        self.builder = builder
        self.selected_role: discord.Role | None = None
        self.selected_emoji: str | None = None
        self.source: str = "standard"
        self.page: int = 0
        self._rebuild_emoji_select()

    @property
    def source_items(self) -> list[str]:
        if self.source == "custom":
            return [str(emoji) for emoji in self.guild.emojis]
        return STANDARD_EMOJIS

    @property
    def page_count(self) -> int:
        items = self.source_items
        if not items:
            return 1
        return ((len(items) - 1) // 25) + 1

    def _rebuild_emoji_select(self) -> None:
        previous_role = self.selected_role
        self.clear_items()
        self.switch_source_button.label = f"Source: {'Standard' if self.source == 'standard' else 'Custom'}"
        self.add_item(RolePickerRoleSelect())
        items = self.source_items
        if not items:
            options = [discord.SelectOption(label="No emojis available", value="")]
        else:
            start = self.page * 25
            page_items = items[start : start + 25]
            options = [
                discord.SelectOption(label=f"{emoji}  #{start + index + 1}", value=emoji, emoji=emoji)
                for index, emoji in enumerate(page_items)
            ]
        self.add_item(EmojiPickerSelect(options=options))
        self.add_item(self.switch_source_button)
        self.add_item(self.prev_page_button)
        self.add_item(self.next_page_button)
        self.add_item(self.save_button)
        self.add_item(self.cancel_button)
        if previous_role is not None:
            self.selected_role = previous_role

    @discord.ui.button(label="Source: Standard", style=discord.ButtonStyle.secondary, row=3)
    async def switch_source_button(self, interaction: discord.Interaction, _: discord.ui.Button["RolePickerView"]) -> None:
        self.source = "custom" if self.source == "standard" else "standard"
        self.page = 0
        self._rebuild_emoji_select()
        await interaction.response.edit_message(
            content=f"Select role and emoji ({self.source} emojis, page {self.page + 1}/{self.page_count})",
            view=self,
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=3)
    async def prev_page_button(self, interaction: discord.Interaction, _: discord.ui.Button["RolePickerView"]) -> None:
        self.page = (self.page - 1) % self.page_count
        self._rebuild_emoji_select()
        await interaction.response.edit_message(
            content=f"Select role and emoji ({self.source} emojis, page {self.page + 1}/{self.page_count})",
            view=self,
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=3)
    async def next_page_button(self, interaction: discord.Interaction, _: discord.ui.Button["RolePickerView"]) -> None:
        self.page = (self.page + 1) % self.page_count
        self._rebuild_emoji_select()
        await interaction.response.edit_message(
            content=f"Select role and emoji ({self.source} emojis, page {self.page + 1}/{self.page_count})",
            view=self,
        )

    @discord.ui.button(label="Save role", style=discord.ButtonStyle.success, row=3)
    async def save_button(self, interaction: discord.Interaction, _: discord.ui.Button["RolePickerView"]) -> None:
        if self.selected_role is None:
            await interaction.response.send_message("Please select a role first.", ephemeral=True)
            return
        if not self.selected_emoji:
            await interaction.response.send_message("Please select an emoji first.", ephemeral=True)
            return
        if any(entry.emoji == self.selected_emoji for entry in self.draft.entries):
            await interaction.response.send_message("That emoji is already used by another role.", ephemeral=True)
            return
        self.draft.entries.append(DraftRoleEntry(role_id=self.selected_role.id, emoji=self.selected_emoji))
        await interaction.response.edit_message(content="Role added.", view=None)
        await self.builder.refresh()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
    async def cancel_button(self, interaction: discord.Interaction, _: discord.ui.Button["RolePickerView"]) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)
        self.stop()


class RolePickerRoleSelect(discord.ui.RoleSelect["RolePickerView"]):
    def __init__(self) -> None:
        super().__init__(placeholder="Choose a role", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values:
            return
        self.view.selected_role = self.values[0]
        await interaction.response.defer()


class RoleBuilderView(discord.ui.View):
    def __init__(self, cog: "Roles", draft: RolePanelDraft) -> None:
        super().__init__(timeout=1800)
        self.cog = cog
        self.draft = draft
        self.message: discord.InteractionMessage | None = None

    def render_content(self) -> str:
        mode = "enabled" if self.draft.multi_role else "disabled"
        lines = [
            f"**Role Panel:** {self.draft.title}",
            f"**Multi-role:** {mode}",
            f"**Channel:** <#{self.draft.channel_id}>",
            "",
        ]
        if not self.draft.entries:
            lines.append("No roles added yet. Use **Add Role** to keep adding entries (unlimited).")
        else:
            lines.append("Current entries:")
            for entry in self.draft.entries:
                lines.append(f"- {entry.emoji} <@&{entry.role_id}>")
        return "\n".join(lines)

    async def refresh(self) -> None:
        if self.message is not None:
            await self.message.edit(content=self.render_content(), view=self)

    @discord.ui.button(label="Add Role", style=discord.ButtonStyle.primary)
    async def add_role_button(self, interaction: discord.Interaction, _: discord.ui.Button["RoleBuilderView"]) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild context is required.", ephemeral=True)
            return
        picker = RolePickerView(guild=guild, draft=self.draft, builder=self)
        await interaction.response.send_message(
            f"Select role and emoji ({picker.source} emojis, page {picker.page + 1}/{picker.page_count})",
            view=picker,
            ephemeral=True,
        )

    @discord.ui.button(label="Publish", style=discord.ButtonStyle.success)
    async def publish_button(self, interaction: discord.Interaction, _: discord.ui.Button["RoleBuilderView"]) -> None:
        if not self.draft.entries:
            await interaction.response.send_message("Add at least one role before publishing.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild context is required.", ephemeral=True)
            return
        channel = guild.get_channel(self.draft.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Target channel no longer exists.", ephemeral=True)
            return

        description = "\n".join(
            f"{entry.emoji}  <@&{entry.role_id}>"
            for entry in self.draft.entries
        )
        embed = discord.Embed(title=self.draft.title, description=description, color=discord.Color.blurple())
        message = await channel.send(embed=embed)
        for entry in self.draft.entries:
            await message.add_reaction(entry.emoji)

        panel_id = self.cog.db.create_role_panel(
            guild_id=self.draft.guild_id,
            channel_id=self.draft.channel_id,
            message_id=message.id,
            title=self.draft.title,
            multi_role=self.draft.multi_role,
        )
        for entry in self.draft.entries:
            self.cog.db.add_role_panel_entry(panel_id=panel_id, role_id=entry.role_id, emoji=entry.emoji)

        for component in self.children:
            component.disabled = True
        await interaction.response.edit_message(content=f"{self.render_content()}\n\nPublished: {message.jump_url}", view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, _: discord.ui.Button["RoleBuilderView"]) -> None:
        await interaction.response.edit_message(content="Role panel creation cancelled.", view=None)
        self.stop()


class RoleCreateModal(discord.ui.Modal, title="Create role panel"):
    panel_title = discord.ui.TextInput(label="Panel title", placeholder="Choose your roles", max_length=120)
    multi_role = discord.ui.TextInput(
        label="Multi-role (true/false)",
        placeholder="true",
        default="true",
        max_length=5,
    )

    def __init__(self, cog: "Roles", channel_id: int, guild_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        multi_role = parse_bool(self.multi_role.value)
        if multi_role is None:
            await interaction.response.send_message("Please enter either `true` or `false`.", ephemeral=True)
            return
        draft = RolePanelDraft(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            title=self.panel_title.value.strip(),
            multi_role=multi_role,
        )
        view = RoleBuilderView(cog=self.cog, draft=draft)
        await interaction.response.send_message(view.render_content(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


class Roles(commands.Cog):
    role = app_commands.Group(name="role", description="Role panel commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = Database()

    @role.command(name="create", description="Create a reaction role panel")
    @app_commands.describe(channel="Channel where the role panel should be posted")
    @app_commands.checks.has_permissions(administrator=True)
    async def role_create(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used inside a server.", ephemeral=True)
            return
        await interaction.response.send_modal(
            RoleCreateModal(cog=self, channel_id=channel.id, guild_id=interaction.guild.id)
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        bot_user = self.bot.user
        if bot_user is not None and payload.user_id == bot_user.id:
            return
        panel = self.db.get_role_panel_by_message_id(payload.message_id)
        if panel is None:
            return
        panel_data, entries = panel
        entry = next((item for item in entries if emoji_matches(item.emoji, payload.emoji)), None)
        if entry is None:
            return
        guild = self.bot.get_guild(panel_data.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            return
        role = guild.get_role(entry.role_id)
        if role is None:
            return

        if role in member.roles:
            channel = guild.get_channel(panel_data.channel_id)
            if not isinstance(channel, discord.TextChannel):
                return
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, member)
            return

        if not panel_data.multi_role:
            channel = guild.get_channel(panel_data.channel_id)
            if not isinstance(channel, discord.TextChannel):
                return
            message = await channel.fetch_message(payload.message_id)
            await self._remove_other_panel_roles(member=member, selected_role_id=role.id, entries=entries, message=message)
        await member.add_roles(role, reason="Role toggle reaction added")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        panel = self.db.get_role_panel_by_message_id(payload.message_id)
        if panel is None:
            return
        panel_data, entries = panel
        entry = next((item for item in entries if emoji_matches(item.emoji, payload.emoji)), None)
        if entry is None:
            return
        guild = self.bot.get_guild(panel_data.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            return
        role = guild.get_role(entry.role_id)
        if role is None or role not in member.roles:
            return
        await member.remove_roles(role, reason="Role toggle reaction removed")

    async def _remove_other_panel_roles(
        self,
        member: discord.Member,
        selected_role_id: int,
        entries: list[RolePanelEntry],
        message: discord.Message,
    ) -> None:
        for entry in entries:
            if entry.role_id == selected_role_id:
                continue
            role = member.guild.get_role(entry.role_id)
            if role is not None and role in member.roles:
                await member.remove_roles(role, reason="Single-role panel replacement")
                await message.remove_reaction(entry.emoji, member)
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
