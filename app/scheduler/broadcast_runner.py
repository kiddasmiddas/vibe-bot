from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Bot
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.promo_repo import PromoRepository
from app.services.broadcast_service import BroadcastService


async def run_scheduled_broadcasts(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """Вытаскивает PromoPost со status='queued' AND scheduled_at<=now() и запускает рассылку.

    Предназначен для вызова APScheduler-ом раз в минуту (подключается в Этапе 11).
    Операция идемпотентна: повторный запуск в ту же минуту не создаст дублей
    (BroadcastService пропускает получателей со status='sent').
    """
    now = datetime.now(tz=UTC)
    async with session_factory() as session:
        promo_repo = PromoRepository(session)
        ready_posts = await promo_repo.list_scheduled_ready(now)

    if not ready_posts:
        logger.debug("broadcast_runner: no scheduled broadcasts ready at {}", now)
        return

    logger.info("broadcast_runner: {} post(s) ready to send", len(ready_posts))

    for post in ready_posts:
        logger.info("broadcast_runner: starting promo_post_id={}", post.id)
        # Отдельная сессия на каждую рассылку. НЕ оборачиваем в session.begin():
        # рассылка может идти минуты (TelegramRetryAfter → sleep), а висящая
        # транзакция PostgreSQL под нагрузкой даёт "idle in transaction".
        # BroadcastService.run управляет flush сам, мы только финально коммитим.
        async with session_factory() as session:
            service = BroadcastService(session=session, bot=bot)
            try:
                result = await service.run(post.id)
                await session.commit()
                logger.info(
                    "broadcast_runner: promo_post_id={} sent={} failed={} skipped={}",
                    post.id,
                    result.sent,
                    result.failed,
                    result.skipped,
                )
            except Exception:
                await session.rollback()
                logger.exception("broadcast_runner: failed promo_post_id={}", post.id)
