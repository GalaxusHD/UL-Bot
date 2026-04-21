import asyncio
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from database import init_database

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.command()
async def ping(ctx: commands.Context) -> None:
    await ctx.send('Pong! 🏓')


async def load_cogs() -> None:
    required_cogs = {
        'birthdays',
        'text_messages',
        'roles',
        'voice_management',
        'reminders',
        'welcome',
        'fun_and_utility',
        'heartbeat',
    }
    loaded_cogs = set()

    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and not filename.startswith('__'):
            cog_name = filename[:-3]
            await bot.load_extension(f'cogs.{cog_name}')
            loaded_cogs.add(cog_name)
            print(f'Loaded {filename}')

    missing_cogs = required_cogs - loaded_cogs
    if missing_cogs:
        raise RuntimeError(f'Missing required cogs: {", ".join(sorted(missing_cogs))}')


@bot.tree.command(name='reload', description='Lade Cogs neu, synchronisiere Befehle und starte Birthday-Tasks neu')
@app_commands.default_permissions(administrator=True)
async def reload_bot(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message('❌ Dieser Befehl ist nur auf Servern verfügbar.', ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ Du brauchst Administrator-Rechte!', ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    status_lines: list[str] = []
    had_errors = False

    try:
        loaded_extensions = [name for name in bot.extensions.keys() if name.startswith('cogs.')]
        for extension in loaded_extensions:
            await bot.unload_extension(extension)
        await load_cogs()
        status_lines.append('✅ Alle Cogs wurden neu geladen.')
    except Exception as exc:
        had_errors = True
        status_lines.append(f'❌ Fehler beim Neuladen der Cogs: {exc}')

    try:
        synced = await bot.tree.sync()
        status_lines.append(f'✅ Slash-Commands synchronisiert ({len(synced)}).')
    except Exception as exc:
        had_errors = True
        status_lines.append(f'❌ Fehler beim Synchronisieren der Commands: {exc}')

    birthdays_cog = bot.get_cog('Birthdays')
    if birthdays_cog is None:
        had_errors = True
        status_lines.append('❌ Birthday-Cog nicht gefunden; Listen und Scheduler konnten nicht aktualisiert werden.')
    else:
        try:
            refreshed = 0
            for guild in bot.guilds:
                await birthdays_cog.refresh_birthday_list(guild)
                refreshed += 1
            status_lines.append(f'✅ Geburtstagslisten aktualisiert ({refreshed} Server).')
        except Exception as exc:
            had_errors = True
            status_lines.append(f'❌ Fehler beim Aktualisieren der Geburtstagslisten: {exc}')

        try:
            if birthdays_cog.daily_scheduler.is_running():
                birthdays_cog.daily_scheduler.cancel()
                for _ in range(10):
                    if not birthdays_cog.daily_scheduler.is_running():
                        break
                    await asyncio.sleep(0.1)

            if not birthdays_cog.daily_scheduler.is_running():
                birthdays_cog.daily_scheduler.start()
                status_lines.append('✅ Birthday-Scheduler wurde neu gestartet.')
            else:
                had_errors = True
                status_lines.append('❌ Birthday-Scheduler konnte nicht neu gestartet werden.')
        except Exception as exc:
            had_errors = True
            status_lines.append(f'❌ Fehler beim Neustarten des Schedulers: {exc}')

    if had_errors:
        status_lines.insert(0, '⚠️ Reload abgeschlossen, aber mit Fehlern:')
    else:
        status_lines.insert(0, '✅ Reload erfolgreich abgeschlossen:')

    await interaction.followup.send('\n'.join(status_lines), ephemeral=True)


@bot.event
async def on_ready() -> None:
    print(f'Bot is online as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as exc:  # pragma: no cover - runtime safety
        print(exc)


async def main() -> None:
    if not TOKEN:
        raise RuntimeError('DISCORD_TOKEN is not set')

    init_database()
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


if __name__ == '__main__':
    asyncio.run(main())
