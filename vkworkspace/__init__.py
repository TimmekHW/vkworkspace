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

import logging

from vkworkspace.__meta__ import __version__
from vkworkspace.client.bot import Bot
from vkworkspace.dispatcher.dispatcher import Dispatcher
from vkworkspace.dispatcher.middlewares.base import BaseMiddleware
from vkworkspace.dispatcher.router import Router
from vkworkspace.listener import RedisListener
from vkworkspace.server import BotServer
from vkworkspace.utils.magic_filter import F
from vkworkspace.utils.scheduler import Scheduler

logging.getLogger("vkworkspace").addHandler(logging.NullHandler())


def enable_debug() -> None:
    """Enable DEBUG logging for all vkworkspace components.

    Adds a StreamHandler with a timestamped formatter to the
    ``vkworkspace`` logger.  Call once at startup::

        import vkworkspace
        vkworkspace.enable_debug()
    """
    logger = logging.getLogger("vkworkspace")
    logger.setLevel(logging.DEBUG)
    if not any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.NullHandler)
        for h in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)


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
    "enable_debug",
]
