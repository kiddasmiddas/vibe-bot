from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType


class UserMiddleware(BaseMiddleware):
    """Outer middleware. Подгружает (или создаёт) `User` по `event.from_user`
    и пробрасывает его в `data['user']` вместе с открытой async-сессией
    БД (`data['db_session']`). Сессия коммитится после успешного хэндлера.
    """

    def __init__(self, session_factory: async_sessionmaker[Any]) -> None:
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None:
            # Например, channel post — пропускаем без user в data.
            data["user"] = None
            return await handler(event, data)

        async with self._session_factory() as session:
            user_repo = UserRepository(session)
            analytics_repo = AnalyticsRepository(session)

            user = await user_repo.get_by_telegram_id(tg_user.id)
            is_new = user is None
            if user is None:
                user = await user_repo.create(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                )
                await analytics_repo.log_event(user.id, event_type=EventType.BOT_START)
                logger.info("new user created: tg_id={} username={}", tg_user.id, tg_user.username)

            data["user"] = user
            data["db_session"] = session
            data["is_new_user"] = is_new
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
