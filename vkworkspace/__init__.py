"""
vkworkspace - Async framework for VK Teams (VK Workspace) bots.

Usage::

    from vkworkspace import Bot, Dispatcher, Router, F

    router = Router()

    @router.message(Command("start"))
    async def start(message: Message):
        await message.answer("Hello!")

    async def main():
        bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
        dp = Dispatcher()
        dp.include_router(router)
        await dp.start_polling(bot)
"""

from vkworkspace.__meta__ import __version__
from vkworkspace.client.bot import Bot
from vkworkspace.dispatcher.dispatcher import Dispatcher
from vkworkspace.dispatcher.middlewares.base import BaseMiddleware
from vkworkspace.dispatcher.router import Router
from vkworkspace.listener import RedisListener
from vkworkspace.server import BotServer
from vkworkspace.utils.magic_filter import F
from vkworkspace.utils.scheduler import Scheduler

__all__ = [
    "BaseMiddleware",
    "Bot",
    "BotServer",
    "Dispatcher",
    "F",
    "RedisListener",
    "Router",
    "Scheduler",
    "__version__",
]
