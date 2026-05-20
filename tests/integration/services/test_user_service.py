"""Интеграционные тесты `user_service.delete_user_data`.

Удаление анкеты НЕ банит пользователя и сохраняет его статус — проверяем,
что аккаунт остаётся, а социальные данные сносятся.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models.matching import Like
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.user_repo import UserRepository
from app.services.user_service import delete_user_data


@pytest.mark.asyncio
async def test_delete_user_data_keeps_account_and_status(db_session) -> None:
    user_repo = UserRepository(db_session)
    me = await user_repo.create(telegram_id=555001, username="victim")
    other = await user_repo.create(telegram_id=555002, username="other")

    # Статус: премиум + модератор.
    await user_repo.set_premium(me.id, datetime.now(UTC) + timedelta(days=30))
    await user_repo.set_moderator(me.id, moderator=True)
    # Соц-данные: лайк от пользователя.
    await MatchingRepository(db_session).add_like(
        from_user_id=me.id, to_user_id=other.id, kind="like"
    )
    await db_session.flush()

    await delete_user_data(me, db_session)
    await db_session.flush()
    await db_session.refresh(me)

    # Аккаунт жив, не забанен, статус сохранён.
    assert await user_repo.get_by_id(me.id) is not None
    assert me.is_banned is False
    assert me.is_premium is True
    assert me.is_moderator is True

    # Социальные данные удалены.
    likes = list((await db_session.execute(select(Like))).scalars().all())
    assert likes == []
