from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.user_repo import UserRepository


async def expire_premium_for_users(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Снимает Premium у пользователей, у которых premium_until < now().

    Запускается APScheduler-ом раз в сутки. Возвращает количество обработанных.
    Операция идемпотентна: повторный запуск ничего лишнего не сделает.
    """
    now = datetime.now(tz=UTC)
    processed = 0

    async with session_factory() as session:
        async with session.begin():
            user_repo = UserRepository(session)
            expired_users = await user_repo.list_expired_premium(now)

            for user in expired_users:
                await user_repo.clear_premium(user.id)
                processed += 1
                logger.info(
                    "premium expired: user_id={} premium_until={}",
                    user.id,
                    user.premium_until,
                )

    if processed:
        logger.info("premium_expiry: {} user(s) downgraded", processed)
    else:
        logger.debug("premium_expiry: no expired subscriptions found")

    return processed
