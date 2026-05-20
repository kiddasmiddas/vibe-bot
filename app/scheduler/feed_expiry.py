from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.settings_repo import SettingsRepository

_DEFAULT_PURGE_DAYS = 4


async def expire_feed_posts(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Переводит активные посты Ленты в статус 'expired' при expires_at < now().

    Запускается каждые 10 минут. Операция идемпотентна.
    Возвращает количество обработанных постов.
    """
    now = datetime.now(tz=UTC)

    async with session_factory() as session:
        async with session.begin():
            repo = FeedRepository(session)
            processed = await repo.expire_active_posts(now)

    if processed:
        logger.info("feed_expiry: {} post(s) expired", processed)
    else:
        logger.debug("feed_expiry: no expired posts found")

    return processed


async def purge_feed_posts(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Физически удаляет старые посты Ленты (expired/hidden/deleted/blocked).

    Порог: expires_at < now() - feed_post_purge_days (из settings, дефолт 4 дня).
    CASCADE удаляет связанные media, comments, reactions.
    Запускается ежедневно в 03:20 UTC.
    Возвращает количество удалённых постов.
    """
    async with session_factory() as session:
        purge_days = _DEFAULT_PURGE_DAYS
        try:
            settings_repo = SettingsRepository(session)
            val = await settings_repo.get_int("feed_post_purge_days")
            if val is not None:
                purge_days = val
        except Exception:
            logger.warning(
                "feed_purge: failed to read feed_post_purge_days, using default {}",
                purge_days,
            )

        before = datetime.now(tz=UTC) - timedelta(days=purge_days)

        async with session.begin():
            repo = FeedRepository(session)
            deleted = await repo.purge_old_posts(before)

    if deleted:
        logger.info(
            "feed_purge: {} post(s) physically deleted (purge_days={})", deleted, purge_days
        )
    else:
        logger.debug("feed_purge: nothing to purge")

    return deleted
