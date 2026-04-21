from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from discord.ext import commands, tasks

logger = logging.getLogger(__name__)
HEARTBEAT_FILE = Path(__file__).resolve().parent.parent / '.bot_heartbeat'


class Heartbeat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._shutting_down = False

    @tasks.loop(seconds=30)
    async def heartbeat_loop(self) -> None:
        await self._write_heartbeat()

    @heartbeat_loop.before_loop
    async def before_heartbeat_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.heartbeat_loop.is_running():
            self.heartbeat_loop.start()
        await self._write_heartbeat()

    def cog_unload(self) -> None:
        self._shutting_down = True
        if self.heartbeat_loop.is_running():
            self.heartbeat_loop.cancel()
        self._write_heartbeat_sync()

    async def _write_heartbeat(self) -> None:
        payload = {
            'timestamp': datetime.now(timezone.utc).timestamp(),
            'pid': os.getpid(),
            'status': 'shutting_down' if self._shutting_down else 'alive',
        }
        self._write_payload(payload)

    def _write_heartbeat_sync(self) -> None:
        payload = {
            'timestamp': datetime.now(timezone.utc).timestamp(),
            'pid': os.getpid(),
            'status': 'shutting_down',
        }
        self._write_payload(payload)

    def _write_payload(self, payload: dict[str, str | int | float]) -> None:
        temp_file = HEARTBEAT_FILE.with_suffix('.tmp')
        try:
            temp_file.write_text(json.dumps(payload), encoding='utf-8')
            temp_file.replace(HEARTBEAT_FILE)
        except OSError as exc:
            logger.warning('Failed to write heartbeat file: %s', exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Heartbeat(bot))
