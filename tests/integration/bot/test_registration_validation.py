"""Интеграционные тесты валидаторов FSM-регистрации (этап 3.1).

Хэндлеры вызываются напрямую с MemoryStorage-based FSMContext и реальной
БД-сессией (через conftest fixture `db_session`). Это не запускает aiogram-роутер
целиком, но проверяет логику отдельных хэндлеров и их связку с
ContentModerationService / SettingsRepository.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.registration import (
    cmd_cancel,
    on_age,
    on_bio,
    on_captcha_choice,
    on_looking_for_age_max,
    on_looking_for_age_min,
    on_nickname,
)
from app.bot.keyboards.registration import CaptchaCb
from app.bot.states.registration import RegistrationStates
from app.db.repositories.user_repo import UserRepository
from app.texts import registration as texts


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _mock_message(text: str):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


async def _make_user(db_session, *, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


@pytest.mark.asyncio
async def test_nickname_too_short_stays_in_state(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.nickname)
    user = await _make_user(db_session, telegram_id=4001)

    message = _mock_message("a")
    await on_nickname(message, state, user, db_session)

    message.answer.assert_awaited_once()
    answered_text = message.answer.call_args.args[0]
    assert "Минимум" in answered_text or "коротк" in answered_text.lower()
    assert await state.get_state() == RegistrationStates.nickname.state


@pytest.mark.asyncio
async def test_nickname_with_link_rejected_by_moderation(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.nickname)
    user = await _make_user(db_session, telegram_id=4002)

    message = _mock_message("hello https://evil.com")
    await on_nickname(message, state, user, db_session)

    message.answer.assert_awaited_once()
    answered_text = message.answer.call_args.args[0]
    assert answered_text == texts.MODERATION_REJECTED_LINK
    assert await state.get_state() == RegistrationStates.nickname.state


@pytest.mark.asyncio
async def test_nickname_valid_advances_to_age(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.nickname)
    user = await _make_user(db_session, telegram_id=4003)

    message = _mock_message("VibeyOne")
    await on_nickname(message, state, user, db_session)

    assert await state.get_state() == RegistrationStates.age.state
    data = await state.get_data()
    assert data["nickname"] == "VibeyOne"


@pytest.mark.asyncio
async def test_age_not_number_stays_in_state(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.age)

    message = _mock_message("abc")
    await on_age(message, state, db_session)

    message.answer.assert_awaited_once_with(texts.AGE_NOT_NUMBER)
    assert await state.get_state() == RegistrationStates.age.state


@pytest.mark.asyncio
async def test_age_below_min_rejected(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.age)

    message = _mock_message("15")
    await on_age(message, state, db_session)

    message.answer.assert_awaited_once()
    answered_text = message.answer.call_args.args[0]
    # min_age=18 в seed, поэтому 15 должен быть отклонён.
    assert "18" in answered_text
    assert await state.get_state() == RegistrationStates.age.state


@pytest.mark.asyncio
async def test_age_valid_advances_to_gender(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.age)

    message = _mock_message("25")
    await on_age(message, state, db_session)

    assert await state.get_state() == RegistrationStates.gender.state
    data = await state.get_data()
    assert data["age"] == 25


@pytest.mark.asyncio
async def test_looking_for_age_max_lt_min_rejected(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.looking_for_age_max)
    await state.update_data(la_min=30)

    message = _mock_message("25")
    await on_looking_for_age_max(message, state, db_session)

    message.answer.assert_awaited_once_with(texts.AGE_MIN_GT_MAX)
    assert await state.get_state() == RegistrationStates.looking_for_age_max.state


@pytest.mark.asyncio
async def test_looking_for_age_min_valid_advances(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.looking_for_age_min)

    message = _mock_message("20")
    await on_looking_for_age_min(message, state, db_session)

    assert await state.get_state() == RegistrationStates.looking_for_age_max.state
    data = await state.get_data()
    assert data["la_min"] == 20


@pytest.mark.asyncio
async def test_bio_too_long_rejected(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.bio)
    user = await _make_user(db_session, telegram_id=4004)

    long_text = "a" * 1000  # bio_max_length=500 в seed
    message = _mock_message(long_text)
    await on_bio(message, state, user, db_session)

    message.answer.assert_awaited_once()
    answered_text = message.answer.call_args.args[0]
    assert "500" in answered_text
    assert await state.get_state() == RegistrationStates.bio.state


@pytest.mark.asyncio
async def test_cancel_clears_state(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.bio)
    await state.update_data(nickname="X", age=22)
    user = await _make_user(db_session, telegram_id=4005)

    message = _mock_message("/cancel")
    await cmd_cancel(message, state, user, db_session)

    assert await state.get_state() is None
    data = await state.get_data()
    assert data == {}
    message.answer.assert_awaited_once()
    answered_text = message.answer.call_args.args[0]
    assert answered_text == texts.CANCELLED


# ----------------------------- captcha -----------------------------


def _mock_callback(message_mock=None) -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = message_mock or _mock_message("captcha message")
    return callback


@pytest.mark.asyncio
async def test_captcha_correct_advances_to_nickname(storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.captcha)
    await state.update_data(captcha_answer="🦊")

    callback = _mock_callback()
    callback_data = CaptchaCb(choice="🦊")
    await on_captcha_choice(callback, callback_data, state)

    assert await state.get_state() == RegistrationStates.nickname.state
    callback.answer.assert_awaited_once()
    # nickname prompt отправлен
    answered_texts = [call.args[0] for call in callback.message.answer.await_args_list]
    assert texts.ASK_NICKNAME in answered_texts


@pytest.mark.asyncio
async def test_captcha_wrong_stays_in_captcha_and_regenerates(storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.captcha)
    await state.update_data(captcha_answer="🦊")

    callback = _mock_callback()
    callback_data = CaptchaCb(choice="🐱")
    await on_captcha_choice(callback, callback_data, state)

    # Остаёмся в captcha
    assert await state.get_state() == RegistrationStates.captcha.state
    # Новый ответ в FSM — всегда "🦊" (единственный target в пуле)
    data = await state.get_data()
    assert data["captcha_answer"] == "🦊"
    # Пользователь получил сообщение об ошибке
    answered_texts = [call.args[0] for call in callback.message.answer.await_args_list]
    assert texts.CAPTCHA_WRONG in answered_texts
