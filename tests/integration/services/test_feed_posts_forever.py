"""Посты Ленты «навсегда»: feed_post_ttl_hours=0 → expires_at NULL.

Вечные посты видны в ленте, не экспирятся шедулером; скрытые/удалённые
вечные посты purge чистит по created_at (иначе копились бы бесконечно).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.profile import Profile
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.user_repo import UserRepository
from app.services.feed_service import FeedService


class _StubModeration:
    async def check_text(self, text: str, **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
        class _R:
            approved = True
            decision = "approved"
            reason = None

        return _R()


class _StubSettings:
    def __init__(self, values: dict[str, int] | None = None) -> None:
        self._values = values or {}

    async def get_int(self, key: str) -> int | None:
        return self._values.get(key)


async def _make_user(db: AsyncSession, telegram_id: int) -> Any:
    return await UserRepository(db).create(telegram_id=telegram_id, username=f"u{telegram_id}")


def _service(db: AsyncSession, values: dict[str, int]) -> FeedService:
    return FeedService(
        db,
        feed_repo=FeedRepository(db),
        settings_repo=_StubSettings(values),  # type: ignore[arg-type]
        analytics_repo=AnalyticsRepository(db),
        moderation_service=_StubModeration(),  # type: ignore[arg-type]
    )


_BASE = {"feed_premoderate_first_n_posts": 0, "feed_post_limit_regular_month": 100}


@pytest.mark.asyncio
async def test_ttl_zero_creates_eternal_post(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, 40_001)
    svc = _service(db_session, {**_BASE, "feed_post_ttl_hours": 0})

    post_id, _ = await svc.create_post(
        user=user, profile=Profile(nickname="T"), text="вечный пост", media=[]
    )

    post = await FeedRepository(db_session).get_by_id(post_id)
    assert post is not None and post.expires_at is None


@pytest.mark.asyncio
async def test_ttl_positive_still_sets_expiry(db_session: AsyncSession) -> None:
    """Механизм TTL не выпилен: значение >0 возвращает экспирацию."""
    user = await _make_user(db_session, 40_002)
    svc = _service(db_session, {**_BASE, "feed_post_ttl_hours": 48})

    post_id, _ = await svc.create_post(
        user=user, profile=Profile(nickname="T"), text="временный пост", media=[]
    )

    post = await FeedRepository(db_session).get_by_id(post_id)
    assert post is not None and post.expires_at is not None


@pytest.mark.asyncio
async def test_eternal_post_listed_in_feed(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, 40_003)
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db_session)
    post = await repo.create_post(
        author_user_id=user.id,
        author_name="T",
        text="вечный",
        status="active",
        is_pending_review=False,
        published_at=now,
        expires_at=None,
    )
    await db_session.flush()

    posts, _ = await repo.list_active_cursor(None, limit=50)
    assert post.id in {p.id for p in posts}


@pytest.mark.asyncio
async def test_expire_scheduler_ignores_eternal_posts(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, 40_004)
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db_session)
    eternal = await repo.create_post(
        author_user_id=user.id,
        author_name="T",
        text="вечный",
        status="active",
        is_pending_review=False,
        published_at=now - timedelta(days=30),
        expires_at=None,
    )
    stale = await repo.create_post(
        author_user_id=user.id,
        author_name="T",
        text="просроченный",
        status="active",
        is_pending_review=False,
        published_at=now - timedelta(days=3),
        expires_at=now - timedelta(days=1),
    )
    await db_session.flush()

    processed = await repo.expire_active_posts(now)

    assert processed == 1
    assert (await repo.get_by_id(eternal.id)).status == "active"
    assert (await repo.get_by_id(stale.id)).status == "expired"


@pytest.mark.asyncio
async def test_purge_cleans_eternal_deleted_by_created_at(db_session: AsyncSession) -> None:
    """Вечный, но удалённый юзером пост чистится purge'ем по created_at."""
    user = await _make_user(db_session, 40_005)
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db_session)
    deleted_old = await repo.create_post(
        author_user_id=user.id,
        author_name="T",
        text="удалённый вечный",
        status="deleted_by_user",
        is_pending_review=False,
        published_at=now - timedelta(days=90),
        expires_at=None,
    )
    active_old = await repo.create_post(
        author_user_id=user.id,
        author_name="T",
        text="живой вечный",
        status="active",
        is_pending_review=False,
        published_at=now - timedelta(days=90),
        expires_at=None,
    )
    await db_session.flush()
    # Посты «созданы» 90 дней назад (create_post ставит created_at=now — двигаем руками).
    for post in (deleted_old, active_old):
        post.created_at = now - timedelta(days=90)
    await db_session.flush()

    purged = await repo.purge_old_posts(
        now - timedelta(days=4),
        keep_created_since=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    )

    assert purged == 1
    assert await repo.get_by_id(deleted_old.id) is None
    assert (await repo.get_by_id(active_old.id)) is not None
