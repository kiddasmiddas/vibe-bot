from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.user_repo import UserRepository


@pytest.mark.asyncio
async def test_create_and_fetch_by_telegram_id(db_session) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(telegram_id=42, username="alice")
    assert user.id is not None
    assert user.is_banned is False
    assert user.is_premium is False

    fetched = await repo.get_by_telegram_id(42)
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.username == "alice"


@pytest.mark.asyncio
async def test_get_by_telegram_id_returns_none_for_unknown(db_session) -> None:
    repo = UserRepository(db_session)
    assert await repo.get_by_telegram_id(9999) is None


@pytest.mark.asyncio
async def test_set_banned_and_premium_updates(db_session) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(telegram_id=100, username="bob")

    await repo.set_banned(user.id, banned=True)
    until = datetime.now(UTC) + timedelta(days=30)
    await repo.update_premium(user.id, is_premium=True, premium_until=until)
    await db_session.flush()
    # session.get() через identity map вернёт закешированный instance;
    # делаем явный refresh, чтобы увидеть UPDATE-изменения.
    await db_session.refresh(user)
    assert user.is_banned is True
    assert user.is_premium is True
    assert user.premium_until is not None
