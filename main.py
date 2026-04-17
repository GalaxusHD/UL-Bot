import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import init_database

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.command()
async def ping(ctx: commands.Context) -> None:
    await ctx.send('Pong! 🏓')


async def load_cogs() -> None:
    for cog_name in ('birthdays', 'text_messages', 'roles'):
        await bot.load_extension(f'cogs.{cog_name}')
        print(f'Loaded cogs/{cog_name}.py')


@bot.event
async def on_ready() -> None:
    print(f'Bot ist online als {bot.user}')
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
