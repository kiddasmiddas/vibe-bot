from __future__ import annotations

import pytest

from app.db.repositories.settings_repo import SettingsRepository


@pytest.mark.asyncio
async def test_seeded_settings_are_readable(db_session) -> None:
    repo = SettingsRepository(db_session)
    assert await repo.get_int("premium_price_rub") == 199
    assert await repo.get_int("premium_duration_days") == 30
    assert await repo.get_int("match_w_fandom") == 3


@pytest.mark.asyncio
async def test_set_overwrites_value(db_session) -> None:
    repo = SettingsRepository(db_session)
    await repo.set("premium_price_rub", "299")
    await db_session.flush()
    assert await repo.get_int("premium_price_rub") == 299


@pytest.mark.asyncio
async def test_get_unknown_returns_none(db_session) -> None:
    repo = SettingsRepository(db_session)
    assert await repo.get("no_such_key") is None
    assert await repo.get_int("no_such_key") is None
    assert await repo.get_float("no_such_key") is None


@pytest.mark.asyncio
async def test_redis_cache_short_circuits_db(db_session, fake_redis) -> None:
    """Если значение лежит в Redis, мы не идём в БД."""
    repo = SettingsRepository(db_session, redis=fake_redis)
    # Первое чтение — из БД, кладёт в кэш.
    val = await repo.get("premium_price_rub")
    assert val == "199"
    # Подменяем значение в кэше — следующее чтение должно вернуть кэшированное.
    await fake_redis.set("settings:premium_price_rub", "999", ex=60)
    assert await repo.get("premium_price_rub") == "999"


@pytest.mark.asyncio
async def test_set_invalidates_cache(db_session, fake_redis) -> None:
    repo = SettingsRepository(db_session, redis=fake_redis)
    await repo.get("premium_price_rub")  # прогревает кэш на "199"
    await repo.set("premium_price_rub", "1500")
    # Cache должен содержать новое значение.
    assert await fake_redis.get("settings:premium_price_rub") == "1500"
