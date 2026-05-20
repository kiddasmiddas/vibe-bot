from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models.premium import PremiumSubscription
from app.db.repositories.premium_repo import PremiumRepository
from app.db.repositories.user_repo import UserRepository


async def _make_user(db_session, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


@pytest.mark.asyncio
async def test_create_subscription_visible_via_get_active(db_session) -> None:
    user = await _make_user(db_session, 6001)
    repo = PremiumRepository(db_session)
    ends_at = datetime.now(tz=UTC) + timedelta(days=30)

    sub = await repo.create_subscription(user_id=user.id, ends_at=ends_at, granted_by="manual")
    assert sub.id is not None

    active = await repo.get_active_subscription(user.id)
    assert active is not None
    assert active.id == sub.id


@pytest.mark.asyncio
async def test_extend_subscription_updates_existing_active(db_session) -> None:
    user = await _make_user(db_session, 6002)
    repo = PremiumRepository(db_session)
    first_end = datetime.now(tz=UTC) + timedelta(days=10)
    new_end = datetime.now(tz=UTC) + timedelta(days=40)

    sub = await repo.create_subscription(user_id=user.id, ends_at=first_end, granted_by="purchase")
    same = await repo.extend_subscription(user.id, new_end)
    await db_session.flush()

    assert same.id == sub.id
    # должно быть только одно ряд (не создаётся дубль)
    rows = (
        (
            await db_session.execute(
                select(PremiumSubscription).where(PremiumSubscription.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].ends_at >= new_end - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_extend_subscription_without_active_creates_new(db_session) -> None:
    user = await _make_user(db_session, 6003)
    repo = PremiumRepository(db_session)
    until = datetime.now(tz=UTC) + timedelta(days=30)

    sub = await repo.extend_subscription(user.id, until)
    assert sub.id is not None
    assert sub.granted_by == "purchase"

    active = await repo.get_active_subscription(user.id)
    assert active is not None
    assert active.id == sub.id


@pytest.mark.asyncio
async def test_expired_subscription_not_active(db_session) -> None:
    user = await _make_user(db_session, 6004)
    repo = PremiumRepository(db_session)
    # Создаём подписку с started_at=now-2d и ends_at=now-1d (истёкшая).
    # Прямо через ORM, чтобы CHECK ends_at > started_at не нарушался.
    started = datetime.now(tz=UTC) - timedelta(days=2)
    ended = datetime.now(tz=UTC) - timedelta(days=1)
    sub = PremiumSubscription(
        user_id=user.id,
        started_at=started,
        ends_at=ended,
        granted_by="manual",
    )
    db_session.add(sub)
    await db_session.flush()

    assert await repo.get_active_subscription(user.id) is None
