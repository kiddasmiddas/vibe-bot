"""Тесты AdsRotationService: показ после N-й анкеты, премиум-скип, ротация, fail-open."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.ads_rotation_repo import AdsRotationRepository
from app.services.ads_rotation_service import AdsRotationService


class _StubSettings:
    """settings_repo с фиксированным ads_rotation_every_n."""

    def __init__(self, every_n: int | None) -> None:
        self._n = every_n

    async def get_int(self, key: str) -> int | None:
        return self._n


class _FakeRedis:
    """Минимальный Redis: incr + expire (для счётчика просмотров)."""

    def __init__(self, *, fail: bool = False) -> None:
        self._store: dict[str, int] = {}
        self._fail = fail

    async def incr(self, key: str) -> int:
        if self._fail:
            raise ConnectionError("redis down")
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True


def _service(db: AsyncSession, *, every_n: int | None, redis: _FakeRedis) -> AdsRotationService:
    return AdsRotationService(
        ads_repo=AdsRotationRepository(db),
        settings_repo=_StubSettings(every_n),  # type: ignore[arg-type]
        redis=redis,
    )


@pytest.mark.asyncio
async def test_premium_never_sees_ad(db_session: AsyncSession) -> None:
    repo = AdsRotationRepository(db_session)
    await repo.create(text="ad")
    svc = _service(db_session, every_n=1, redis=_FakeRedis())

    results = [await svc.tick_and_pick(1, is_premium=True) for _ in range(5)]
    assert results == [None, None, None, None, None]


@pytest.mark.asyncio
async def test_ad_every_n(db_session: AsyncSession) -> None:
    """N=3: реклама выпадает на 3-й и 6-й анкете, между — None."""
    repo = AdsRotationRepository(db_session)
    await repo.create(text="ad")
    svc = _service(db_session, every_n=3, redis=_FakeRedis())

    outcomes = [await svc.tick_and_pick(42, is_premium=False) for _ in range(6)]
    shown = [o is not None for o in outcomes]
    assert shown == [False, False, True, False, False, True]


@pytest.mark.asyncio
async def test_rotation_sequence(db_session: AsyncSession) -> None:
    """N=1: каждая анкета даёт рекламу, креативы идут по кругу."""
    repo = AdsRotationRepository(db_session)
    a = await repo.create(text="A")
    b = await repo.create(text="B")
    svc = _service(db_session, every_n=1, redis=_FakeRedis())

    picks = [await svc.tick_and_pick(7, is_premium=False) for _ in range(4)]
    ids = [p.id for p in picks if p is not None]
    assert ids == [a.id, b.id, a.id, b.id]


@pytest.mark.asyncio
async def test_disabled_when_n_zero(db_session: AsyncSession) -> None:
    repo = AdsRotationRepository(db_session)
    await repo.create(text="ad")
    svc = _service(db_session, every_n=0, redis=_FakeRedis())
    assert await svc.tick_and_pick(1, is_premium=False) is None


@pytest.mark.asyncio
async def test_empty_pool(db_session: AsyncSession) -> None:
    svc = _service(db_session, every_n=1, redis=_FakeRedis())
    # Счётчик дошёл до N, но пул пуст → None.
    assert await svc.tick_and_pick(1, is_premium=False) is None


@pytest.mark.asyncio
async def test_redis_down_fail_open(db_session: AsyncSession) -> None:
    """Redis недоступен → рекламу не показываем, но и не падаем."""
    repo = AdsRotationRepository(db_session)
    await repo.create(text="ad")
    svc = _service(db_session, every_n=1, redis=_FakeRedis(fail=True))
    assert await svc.tick_and_pick(1, is_premium=False) is None


@pytest.mark.asyncio
async def test_default_every_n_when_setting_absent(db_session: AsyncSession) -> None:
    """Нет настройки → дефолт 10: первые 9 анкет без рекламы, на 10-й — реклама."""
    repo = AdsRotationRepository(db_session)
    await repo.create(text="ad")
    svc = _service(db_session, every_n=None, redis=_FakeRedis())

    outcomes = [await svc.tick_and_pick(99, is_premium=False) for _ in range(10)]
    assert all(o is None for o in outcomes[:9])
    assert outcomes[9] is not None
