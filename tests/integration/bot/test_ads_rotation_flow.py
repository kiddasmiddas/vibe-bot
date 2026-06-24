"""Интеграция авто-рекламы в матчинг: после N-й анкеты не-премиум видит рекламу,
премиум — нет. aiogram-объекты и Redis замоканы.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import matching as matching_module
from app.bot.handlers.matching import on_matching_action
from app.bot.keyboards.matching import MatchingActionCb
from app.db.repositories.ads_rotation_repo import AdsRotationRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository


class _FakeRedis:
    """In-memory Redis: get/set/incr/expire — для счётчика и кэша настроек."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self._store[key] = str(value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        cur = int(self._store.get(key, "0")) + 1
        self._store[key] = str(cur)
        return cur

    async def expire(self, key: str, ttl: int) -> bool:
        return True


def _fsm(storage: MemoryStorage, user_id: int) -> FSMContext:
    return FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


def _mock_message() -> MagicMock:
    message = MagicMock()
    message.answer = AsyncMock()
    message.answer_photo = AsyncMock()
    message.edit_media = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    message.delete = AsyncMock()
    return message


def _mock_callback(message: MagicMock) -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = message
    return cb


@pytest.mark.asyncio
async def test_non_premium_sees_ad_after_nth(db_session, monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(matching_module, "get_redis", lambda: redis)
    # N=1 — реклама на первой же анкете.
    await SettingsRepository(db_session, redis).set("ads_rotation_every_n", "1")
    await AdsRotationRepository(db_session).create(text="РЕКЛАМА-ТЕКСТ", button_label=None)

    user = await UserRepository(db_session).create(telegram_id=95001, username="u")
    assert user.is_premium is False

    message = _mock_message()
    callback = _mock_callback(message)
    state = _fsm(MemoryStorage(), user.id)
    cd = MatchingActionCb(action="skip", target_user_id=user.id)

    await on_matching_action(callback, cd, state, user, db_session, MagicMock())

    # Кнопки текущей карточки погашены, реклама отправлена новым сообщением.
    assert message.edit_reply_markup.await_count >= 1
    answered = [c.args[0] for c in message.answer.await_args_list if c.args]
    assert "РЕКЛАМА-ТЕКСТ" in answered


@pytest.mark.asyncio
async def test_premium_does_not_see_ad(db_session, monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(matching_module, "get_redis", lambda: redis)
    await SettingsRepository(db_session, redis).set("ads_rotation_every_n", "1")
    await AdsRotationRepository(db_session).create(text="РЕКЛАМА-ТЕКСТ", button_label=None)

    user = await UserRepository(db_session).create(telegram_id=95002, username="p")
    user.is_premium = True
    await db_session.flush()

    message = _mock_message()
    callback = _mock_callback(message)
    state = _fsm(MemoryStorage(), user.id)
    cd = MatchingActionCb(action="skip", target_user_id=user.id)

    await on_matching_action(callback, cd, state, user, db_session, MagicMock())

    answered = [c.args[0] for c in message.answer.await_args_list if c.args]
    assert "РЕКЛАМА-ТЕКСТ" not in answered
