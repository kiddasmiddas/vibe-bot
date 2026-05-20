from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.handlers.admin import admin_router
from app.bot.handlers.blocks import router as blocks_router
from app.bot.handlers.common import router as common_router
from app.bot.handlers.complaints import router as complaints_router
from app.bot.handlers.feed_menu import router as feed_menu_router
from app.bot.handlers.gdpr import router as gdpr_router
from app.bot.handlers.matches import router as matches_router
from app.bot.handlers.matching import router as matching_router
from app.bot.handlers.premium import router as premium_router
from app.bot.handlers.profile import router as profile_router
from app.bot.handlers.registration import router as registration_router
from app.bot.handlers.support import router as support_router
from app.bot.middlewares import BanMiddleware, ThrottlingMiddleware, UserMiddleware
from app.db.base import async_session_factory as default_session_factory


def build_dispatcher(
    bot: Bot,
    redis: Redis,
    *,
    session_factory: async_sessionmaker | None = None,
) -> Dispatcher:
    """Создаёт Dispatcher с RedisStorage, регистрирует мидлвари и роутеры.

    Порядок outer-мидлварей:
    1) ThrottlingMiddleware — самая дешёвая проверка (Redis SETNX/INCR). При
       флуде апдейт отбрасывается ДО открытия сессии БД и подгрузки User.
       Уведомление пользователю отправляется не больше одного раза за окно
       троттлинга — повторные хиты молча игнорируются.
    2) UserMiddleware — открывает async-сессию и подгружает/создаёт User.
    3) BanMiddleware — читает `user.is_banned`, отсекает забаненных.
    """
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    factory = session_factory or default_session_factory

    dp.update.outer_middleware(ThrottlingMiddleware(redis))
    dp.update.outer_middleware(UserMiddleware(factory))
    dp.update.outer_middleware(BanMiddleware())

    dp.include_router(common_router)
    dp.include_router(registration_router)
    dp.include_router(profile_router)
    dp.include_router(matching_router)
    dp.include_router(matches_router)
    dp.include_router(complaints_router)
    dp.include_router(blocks_router)
    dp.include_router(feed_menu_router)
    dp.include_router(support_router)
    dp.include_router(premium_router)
    dp.include_router(gdpr_router)
    dp.include_router(admin_router)

    # Делаем bot доступным в data на случай ручных send-ов из мидлварей/сервисов.
    dp["bot"] = bot

    return dp
