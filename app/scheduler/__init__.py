from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.scheduler.creator_post_expiry import expire_creator_posts
from app.scheduler.feed_expiry import expire_feed_posts, purge_feed_posts
from app.scheduler.premium_expiry import expire_premium_for_users


def _guarded(
    job_id: str, coro_factory: Callable[[], Awaitable[object]]
) -> Callable[[], Awaitable[None]]:
    """Оборачивает джобу так, чтобы исключение не терялось.

    AsyncIOScheduler сам ждёт async-функцию (не нужен create_task) — поэтому
    исключение всплывёт сюда, мы его логируем, и APScheduler корректно
    зафиксирует job как ошибочную (job listener / event). Без обёртки
    `lambda: create_task(...)` исключение тонуло в never-retrieved Task.
    """

    async def _runner() -> None:
        try:
            await coro_factory()
        except Exception:
            logger.exception("scheduler job {} failed", job_id)

    return _runner


def build_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    bot: object,
) -> AsyncIOScheduler:
    """Создаёт AsyncIOScheduler с UTC-таймзоной и регистрирует все джобы.

    Джобы:
    - premium_expiry      — ежедневно в 03:00 UTC
    - creator_post_expiry — ежедневно в 03:10 UTC
    - feed_expiry         — каждые 10 минут
    - feed_purge          — ежедневно в 03:20 UTC
    - broadcast_runner    — каждую минуту
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        _guarded("premium_expiry", lambda: expire_premium_for_users(session_factory)),
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="premium_expiry",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _guarded("creator_post_expiry", lambda: expire_creator_posts(session_factory)),
        CronTrigger(hour=3, minute=10, timezone="UTC"),
        id="creator_post_expiry",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _guarded("feed_expiry", lambda: expire_feed_posts(session_factory)),
        "interval",
        minutes=10,
        id="feed_expiry",
        replace_existing=True,
        misfire_grace_time=600,
    )

    scheduler.add_job(
        _guarded("feed_purge", lambda: purge_feed_posts(session_factory)),
        CronTrigger(hour=3, minute=20, timezone="UTC"),
        id="feed_purge",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    try:
        from app.scheduler.broadcast_runner import run_scheduled_broadcasts

        scheduler.add_job(
            _guarded(
                "broadcast_runner",
                lambda: run_scheduled_broadcasts(session_factory, bot),  # type: ignore[arg-type]
            ),
            "interval",
            minutes=1,
            id="broadcast_runner",
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("scheduler: broadcast_runner job registered")
    except ImportError:
        logger.warning(
            "scheduler: broadcast_runner not available (Stage 9 not merged yet) — skipping job"
        )

    return scheduler


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Запускает scheduler. Вызывается в on_startup."""
    scheduler.start()
    logger.info("APScheduler started: jobs={}", [j.id for j in scheduler.get_jobs()])


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Останавливает scheduler. Вызывается в on_shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
