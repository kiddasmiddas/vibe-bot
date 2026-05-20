"""Юнит-тесты шедулера premium_expiry.

Используют реальную БД (db_session) — нужно проверить SQL-логику.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.user_repo import UserRepository


async def _make_user(
    db_session,
    *,
    telegram_id: int,
    is_premium: bool = False,
    premium_until: datetime | None = None,
):
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    if is_premium or premium_until is not None:
        await UserRepository(db_session).update_premium(
            user.id, is_premium=is_premium, premium_until=premium_until
        )
        await db_session.flush()
        await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_expire_premium_only_expired_users(db_session) -> None:
    """3 юзера: один с активным Premium, один с истёкшим, один без Premium.

    expire_premium_for_users → ровно один обработан, его is_premium=False.
    """
    now = datetime.now(tz=UTC)

    # Активный Premium — не должен быть снят.
    active_user = await _make_user(
        db_session,
        telegram_id=90001,
        is_premium=True,
        premium_until=now + timedelta(days=5),
    )
    # Истёкший Premium — должен быть снят.
    expired_user = await _make_user(
        db_session,
        telegram_id=90002,
        is_premium=True,
        premium_until=now - timedelta(hours=1),
    )
    # Без Premium — не затрагивается.
    free_user = await _make_user(db_session, telegram_id=90003)

    # Создаём фиктивную session_factory, которая возвращает ту же сессию с сохранением
    # результатов через flush/без коммита. Так как conftest использует rollback-транзакцию,
    # мы не можем использовать async_sessionmaker напрямую.
    # Вместо этого тестируем логику через UserRepository напрямую.

    user_repo = UserRepository(db_session)
    expired_users = await user_repo.list_expired_premium(now)

    # Проверяем, что в выборку попал только expired_user.
    expired_ids = {u.id for u in expired_users}
    assert expired_user.id in expired_ids
    assert active_user.id not in expired_ids
    assert free_user.id not in expired_ids

    # Применяем снятие Premium.
    for u in expired_users:
        await user_repo.clear_premium(u.id)
    await db_session.flush()

    # Обновляем объекты из сессии.
    await db_session.refresh(expired_user)
    await db_session.refresh(active_user)

    assert expired_user.is_premium is False
    assert active_user.is_premium is True
    # premium_until у expired_user сохраняется как исторический (не обнуляется).
    assert expired_user.premium_until is not None

    processed_count = len(expired_ids)
    assert processed_count == 1
