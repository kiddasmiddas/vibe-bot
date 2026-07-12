"""Тесты NotificationThrottle: агрегация лайк/коммент-пушей, суперлайк, fail-open."""

from __future__ import annotations

import pytest

from app.services.notification_service import (
    SETTING_COMMENT_PAUSE_MIN,
    SETTING_LIKE_COOLDOWN_HOURS,
    NotificationThrottle,
)


class _StubSettings:
    """settings_repo с фиксированными значениями кулдаунов."""

    def __init__(self, values: dict[str, int | None]) -> None:
        self._values = values

    async def get_int(self, key: str) -> int | None:
        return self._values.get(key)


class _FakeRedis:
    """In-memory Redis: set(nx)/get/delete/incr/expire, без реального TTL.

    Истечение кулдауна в тестах эмулируется явным `expire_key()`.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._fail = fail

    def _check(self) -> None:
        if self._fail:
            raise ConnectionError("redis down")

    async def set(self, key: str, value, ex: int | None = None, nx: bool = False):  # type: ignore[no-untyped-def]
        self._check()
        if nx and key in self._store:
            return None
        self._store[key] = str(value)
        return True

    async def get(self, key: str) -> str | None:
        self._check()
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._check()
        self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        self._check()
        cur = int(self._store.get(key, "0")) + 1
        self._store[key] = str(cur)
        return cur

    async def expire(self, key: str, ttl: int) -> bool:
        self._check()
        return True

    def expire_key(self, key: str) -> None:
        """Тестовый хелпер: «истёк TTL» — ключ пропадает."""
        self._store.pop(key, None)


def _throttle(
    redis: _FakeRedis,
    *,
    like_hours: int | None = 24,
    comment_min: int | None = 15,
) -> NotificationThrottle:
    settings = _StubSettings(
        {
            SETTING_LIKE_COOLDOWN_HOURS: like_hours,
            SETTING_COMMENT_PAUSE_MIN: comment_min,
        }
    )
    return NotificationThrottle(settings_repo=settings, redis=redis)  # type: ignore[arg-type]


# --------------------------- лайки ---------------------------


@pytest.mark.asyncio
async def test_first_like_pushes_immediately() -> None:
    throttle = _throttle(_FakeRedis())
    assert await throttle.register_like(1) == 1


@pytest.mark.asyncio
async def test_likes_within_cooldown_accumulate() -> None:
    redis = _FakeRedis()
    throttle = _throttle(redis)
    assert await throttle.register_like(1) == 1
    assert await throttle.register_like(1) is None
    assert await throttle.register_like(1) is None
    # Кулдаун истёк → следующий лайк несёт накопленные 2 + себя.
    redis.expire_key("notif:like:cd:1")
    assert await throttle.register_like(1) == 3
    # Счётчик забран — новое окно начинается с 1 (после нового истечения).
    redis.expire_key("notif:like:cd:1")
    assert await throttle.register_like(1) == 1


@pytest.mark.asyncio
async def test_like_counters_are_per_user() -> None:
    throttle = _throttle(_FakeRedis())
    assert await throttle.register_like(1) == 1
    assert await throttle.register_like(2) == 1


@pytest.mark.asyncio
async def test_likes_disabled_when_zero() -> None:
    throttle = _throttle(_FakeRedis(), like_hours=0)
    assert await throttle.register_like(1) is None


@pytest.mark.asyncio
async def test_negative_setting_means_disabled() -> None:
    throttle = _throttle(_FakeRedis(), like_hours=-5)
    assert await throttle.register_like(1) is None


@pytest.mark.asyncio
async def test_default_when_setting_absent() -> None:
    """Нет настройки → дефолт 24 ч: пуши работают."""
    throttle = _throttle(_FakeRedis(), like_hours=None)
    assert await throttle.register_like(1) == 1


@pytest.mark.asyncio
async def test_redis_down_fail_open() -> None:
    throttle = _throttle(_FakeRedis(fail=True))
    assert await throttle.register_like(1) is None


# --------------------------- суперлайк ---------------------------


@pytest.mark.asyncio
async def test_superlike_pushes_immediately_and_resets_cooldown() -> None:
    redis = _FakeRedis()
    throttle = _throttle(redis)
    assert await throttle.register_superlike(1) is True
    # Обычный лайк сразу после суперлайка — в кулдауне, копится.
    assert await throttle.register_like(1) is None
    redis.expire_key("notif:like:cd:1")
    assert await throttle.register_like(1) == 2


@pytest.mark.asyncio
async def test_superlike_disabled_when_zero() -> None:
    throttle = _throttle(_FakeRedis(), like_hours=0)
    assert await throttle.register_superlike(1) is False


@pytest.mark.asyncio
async def test_superlike_redis_down_fail_open() -> None:
    throttle = _throttle(_FakeRedis(fail=True))
    assert await throttle.register_superlike(1) is False


# --------------------------- комментарии ---------------------------


@pytest.mark.asyncio
async def test_first_comment_pushes_immediately() -> None:
    throttle = _throttle(_FakeRedis())
    assert await throttle.register_post_comment(10) == 1


@pytest.mark.asyncio
async def test_comments_within_pause_accumulate_per_post() -> None:
    redis = _FakeRedis()
    throttle = _throttle(redis)
    assert await throttle.register_post_comment(10) == 1
    assert await throttle.register_post_comment(10) is None
    # Другой пост — независимое окно.
    assert await throttle.register_post_comment(11) == 1
    redis.expire_key("notif:post:cd:10")
    assert await throttle.register_post_comment(10) == 2


@pytest.mark.asyncio
async def test_comments_disabled_when_zero() -> None:
    throttle = _throttle(_FakeRedis(), comment_min=0)
    assert await throttle.register_post_comment(10) is None
