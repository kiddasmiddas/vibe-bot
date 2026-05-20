from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.bot.commands import setup_bot_commands
from app.bot.dispatcher import build_dispatcher
from app.cache import get_redis
from app.config import settings
from app.db.base import async_session_factory
from app.logger import setup_logger
from app.scheduler import build_scheduler, start_scheduler, stop_scheduler

WEBHOOK_APP_PORT = 8080

_scheduler: AsyncIOScheduler | None = None


async def _on_startup(bot: Bot) -> None:
    global _scheduler
    _scheduler = build_scheduler(async_session_factory, bot)
    start_scheduler(_scheduler)

    await setup_bot_commands(bot)

    if settings.environment == "prod":
        url = f"{settings.webhook_host}{settings.webhook_path}"
        await bot.set_webhook(
            url=url,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
        )
        logger.info("webhook set: url={}", url)


async def _on_shutdown(bot: Bot) -> None:
    global _scheduler
    if _scheduler is not None:
        stop_scheduler(_scheduler)

    if settings.environment == "prod":
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("webhook deleted")

    redis = get_redis()
    try:
        await redis.aclose()
    except Exception as exc:
        logger.warning("redis close failed: {}", exc)


def _build_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    redis = get_redis()
    dp = build_dispatcher(bot, redis)
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)
    return bot, dp


async def _run_polling() -> None:
    bot, dp = _build_bot_and_dispatcher()
    logger.info("starting long polling")
    await dp.start_polling(bot)


def _run_webhook() -> None:
    bot, dp = _build_bot_and_dispatcher()
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.webhook_secret or None,
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)
    logger.info("starting webhook server on 0.0.0.0:{}", WEBHOOK_APP_PORT)
    web.run_app(app, host="0.0.0.0", port=WEBHOOK_APP_PORT)


def main() -> None:
    setup_logger()
    logger.info("vibe-bot is starting in {} mode", settings.environment)
    try:
        if settings.environment == "prod":
            _run_webhook()
        else:
            asyncio.run(_run_polling())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
