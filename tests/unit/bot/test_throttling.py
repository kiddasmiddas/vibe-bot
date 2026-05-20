from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from app.bot.middlewares.throttling import (
    RATE_LIMIT_MAX,
    ThrottlingMiddleware,
)


class FakeRedis:
    """In-memory имитация redis.asyncio.Redis для проверок throttling.

    `set(..., nx=True)` возвращает True для первой записи и None для повторной —
    так ведёт себя реальный клиент. Поддерживаем `px`/`ex` как «время жизни»
    (не моделируем истечение — для тестов в одном окне это OK).
    """

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.locks: set[str] = set()

    async def set(self, key, value, *, px=None, ex=None, nx=False):
        if nx and key in self.locks:
            return None
        self.locks.add(key)
        return True

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True


def _make_callback(tg_id: int = 42) -> CallbackQuery:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=tg_id)
    cb.answer = AsyncMock()
    return cb


def _make_message(tg_id: int = 42) -> Message:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(id=tg_id)
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_second_callback_within_burst_window_is_throttled_and_notified() -> None:
    redis = FakeRedis()
    mw = ThrottlingMiddleware(redis)
    handler = AsyncMock(return_value="ok")

    cb1 = _make_callback(tg_id=7)
    cb2 = _make_callback(tg_id=7)
    data: dict = {"event_from_user": cb1.from_user}

    res1 = await mw(handler, cb1, data)
    res2 = await mw(handler, cb2, data)

    assert res1 == "ok"
    assert res2 is None
    cb2.answer.assert_awaited_once()  # первое предупреждение отправлено
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_burst_throttle_notifies_only_once_per_window() -> None:
    """Подряд несколько спамных кликов в окне — ответ только один раз.

    Защищает от ответного трафика к Telegram-API на каждое спамное действие.
    """
    redis = FakeRedis()
    mw = ThrottlingMiddleware(redis)
    handler = AsyncMock(return_value="ok")

    first = _make_callback(tg_id=11)
    spam = [_make_callback(tg_id=11) for _ in range(5)]
    data: dict = {"event_from_user": first.from_user}

    await mw(handler, first, data)
    for cb in spam:
        result = await mw(handler, cb, data)
        assert result is None

    # answer вызвался ровно один раз — у первого спам-клика; остальные молчат.
    notified = sum(int(cb.answer.await_count > 0) for cb in spam)
    assert notified == 1


@pytest.mark.asyncio
async def test_rate_limit_blocks_21st_update_and_notifies_once() -> None:
    redis = FakeRedis()
    mw = ThrottlingMiddleware(redis)
    handler = AsyncMock(return_value="ok")

    msg = _make_message(tg_id=9)
    data: dict = {"event_from_user": msg.from_user}

    for _ in range(RATE_LIMIT_MAX):
        result = await mw(handler, msg, data)
        assert result == "ok"

    blocked_1 = await mw(handler, msg, data)
    blocked_2 = await mw(handler, msg, data)
    blocked_3 = await mw(handler, msg, data)

    assert blocked_1 is None
    assert blocked_2 is None
    assert blocked_3 is None
    assert handler.await_count == RATE_LIMIT_MAX
    # Только одно предупреждение за весь спам-всплеск.
    assert msg.answer.await_count == 1


@pytest.mark.asyncio
async def test_no_user_passes_through() -> None:
    redis = FakeRedis()
    mw = ThrottlingMiddleware(redis)
    handler = AsyncMock(return_value="ok")

    event = MagicMock()
    data: dict = {"event_from_user": None}

    result = await mw(handler, event, data)
    assert result == "ok"
    handler.assert_awaited_once()
