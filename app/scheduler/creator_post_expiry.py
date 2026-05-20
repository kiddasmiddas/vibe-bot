from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.creators import CreatorPost


async def expire_creator_posts(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Снимает с публикации посты «Аллеи креаторов», у которых expires_at < now().

    Запускается APScheduler-ом раз в сутки. Возвращает количество обработанных.
    Операция идемпотентна: повторный запуск ничего лишнего не сделает.
    """
    now = datetime.now(tz=UTC)

    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                update(CreatorPost)
                .where(
                    CreatorPost.is_published.is_(True),
                    CreatorPost.expires_at < now,
                )
                .values(is_published=False)
            )
            processed = result.rowcount  # type: ignore[union-attr]

    if processed:
        logger.info("creator_post_expiry: {} post(s) unpublished", processed)
    else:
        logger.debug("creator_post_expiry: no expired posts found")

    return processed
