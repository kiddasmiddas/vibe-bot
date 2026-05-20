"""Интеграционные тесты FSM-шагов own_vibe / desired_vibe (фаза 3.2, пикер).

После рефакторинга вайбов текстовый ввод заменён on inline-пикер:
- on_vibe_pick_own — одиночный выбор переводит в состояние desired_vibe.
- on_vibe_page_own / on_vibe_page_desired — навигация по страницам.
- on_vibe_pick_desired — toggle номера в FSM-наборе desired_vibe_numbers.
- on_vibe_done_desired — с пустым набором → alert, без перехода; с непустым →
  сохраняет desired_vibe_ids в FSM и переходит к main_media.
- on_vibe_any_desired — очищает desired_vibe_ids=[], переходит к main_media.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.registration import (
    on_vibe_any_desired,
    on_vibe_done_desired,
    on_vibe_page_desired,
    on_vibe_page_own,
    on_vibe_pick_desired,
    on_vibe_pick_own,
)
from app.bot.keyboards.registration import (
    VibePageCb,
    VibePickCb,
)
from app.bot.states.registration import RegistrationStates
from app.db.models.dictionaries import Vibe
from app.texts import registration as texts


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _mock_callback(user_id: int = 999) -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.bot = MagicMock()
    cb.message = MagicMock()
    cb.message.chat = MagicMock()
    cb.message.chat.id = 12345
    cb.message.photo = None  # text message, no photo
    cb.message.delete = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_media = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    # bot.send_photo so send_vibe_picker can call it
    cb.bot.send_photo = AsyncMock()
    cb.bot.send_message = AsyncMock()
    # message.bot for edit_vibe_picker
    cb.message.bot = cb.bot
    return cb


# ----------------------------- on_vibe_pick_own -----------------------------


@pytest.mark.asyncio
async def test_on_vibe_pick_own_valid_number_transitions_to_desired_vibe(
    db_session, storage
) -> None:
    """Нажатие на номер вайба в пикере own → FSM переходит в desired_vibe."""
    # Берём реальный вайб из seed (numbers 1..36, titles "Вайб N").
    vibe = (await db_session.execute(select(Vibe).where(Vibe.number == 1))).scalar_one()
    state = _fsm(storage)
    await state.set_state(RegistrationStates.own_vibe)
    await state.update_data(own_vibe_page=0)

    cb = _mock_callback()
    cb_data = VibePickCb(role="own", page=0, number=1)

    await on_vibe_pick_own(cb, cb_data, state, db_session)

    assert await state.get_state() == RegistrationStates.desired_vibe.state
    data = await state.get_data()
    assert data["own_vibe_id"] == vibe.id
    assert data["desired_vibe_numbers"] == []


@pytest.mark.asyncio
async def test_on_vibe_pick_own_wrong_role_ignored(db_session, storage) -> None:
    """Callback с role='desired' в состоянии own_vibe игнорируется."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.own_vibe)
    await state.update_data(own_vibe_page=0)

    cb = _mock_callback()
    cb_data = VibePickCb(role="desired", page=0, number=1)

    await on_vibe_pick_own(cb, cb_data, state, db_session)

    # State не изменился.
    assert await state.get_state() == RegistrationStates.own_vibe.state


@pytest.mark.asyncio
async def test_on_vibe_pick_own_unknown_number_ignored(db_session, storage) -> None:
    """Номер 9999 не существует в seed → state не меняется, own_vibe_id не записан."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.own_vibe)
    await state.update_data(own_vibe_page=0)

    cb = _mock_callback()
    cb_data = VibePickCb(role="own", page=0, number=9999)

    await on_vibe_pick_own(cb, cb_data, state, db_session)

    assert await state.get_state() == RegistrationStates.own_vibe.state
    data = await state.get_data()
    assert "own_vibe_id" not in data


# ----------------------------- on_vibe_page_own -----------------------------


@pytest.mark.asyncio
async def test_on_vibe_page_own_navigates_to_new_page(db_session, storage) -> None:
    """Стрелка ▶ на странице 0 → обновляет own_vibe_page=1 в FSM."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.own_vibe)
    await state.update_data(own_vibe_page=0)

    cb = _mock_callback()
    # photo = None → edit_vibe_picker пойдёт по ветке text→text
    cb.message.photo = None
    cb.message.edit_text = AsyncMock()
    cb_data = VibePageCb(role="own", page=1)

    await on_vibe_page_own(cb, cb_data, state, db_session)

    data = await state.get_data()
    assert data["own_vibe_page"] == 1


@pytest.mark.asyncio
async def test_on_vibe_page_own_noop_when_same_page(db_session, storage) -> None:
    """Нажатие центральной кнопки N/M (page == current) — ничего не делает."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.own_vibe)
    await state.update_data(own_vibe_page=2)

    cb = _mock_callback()
    cb_data = VibePageCb(role="own", page=2)

    await on_vibe_page_own(cb, cb_data, state, db_session)

    # edit_vibe_picker не вызывался (no message edit).
    cb.message.edit_text.assert_not_awaited()


# ----------------------------- on_vibe_pick_desired -------------------------


@pytest.mark.asyncio
async def test_on_vibe_pick_desired_toggles_on(db_session, storage) -> None:
    """Первый тап на номере → добавляется в desired_vibe_numbers."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.desired_vibe)
    await state.update_data(desired_vibe_numbers=[])

    cb = _mock_callback()
    cb.message.photo = None
    cb.message.edit_text = AsyncMock()
    cb_data = VibePickCb(role="desired", page=0, number=5)

    await on_vibe_pick_desired(cb, cb_data, state, db_session)

    data = await state.get_data()
    assert 5 in data["desired_vibe_numbers"]


@pytest.mark.asyncio
async def test_on_vibe_pick_desired_toggles_off(db_session, storage) -> None:
    """Повторный тап на уже выбранном номере → удаляется из desired_vibe_numbers."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.desired_vibe)
    await state.update_data(desired_vibe_numbers=[5, 7])

    cb = _mock_callback()
    cb.message.photo = None
    cb.message.edit_text = AsyncMock()
    cb_data = VibePickCb(role="desired", page=0, number=5)

    await on_vibe_pick_desired(cb, cb_data, state, db_session)

    data = await state.get_data()
    assert 5 not in data["desired_vibe_numbers"]
    assert 7 in data["desired_vibe_numbers"]


# ----------------------------- on_vibe_done_desired -------------------------


@pytest.mark.asyncio
async def test_on_vibe_done_desired_empty_set_shows_alert(db_session, storage) -> None:
    """«Готово» с пустым набором → alert и state остаётся на desired_vibe."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.desired_vibe)
    await state.update_data(desired_vibe_numbers=[])

    cb = _mock_callback()

    await on_vibe_done_desired(cb, state, db_session)

    cb.answer.assert_awaited_once_with(texts.DESIRED_VIBE_NEED_NON_EMPTY, show_alert=True)
    assert await state.get_state() == RegistrationStates.desired_vibe.state


@pytest.mark.asyncio
async def test_on_vibe_done_desired_non_empty_advances(db_session, storage) -> None:
    """«Готово» с выбранными номерами → desired_vibe_ids в FSM, переход к main_media."""
    # Берём несколько реальных вайбов из seed.
    vibe1 = (await db_session.execute(select(Vibe).where(Vibe.number == 3))).scalar_one()
    vibe7 = (await db_session.execute(select(Vibe).where(Vibe.number == 7))).scalar_one()

    state = _fsm(storage)
    await state.set_state(RegistrationStates.desired_vibe)
    await state.update_data(desired_vibe_numbers=[3, 7])

    cb = _mock_callback()

    await on_vibe_done_desired(cb, state, db_session)

    assert await state.get_state() == RegistrationStates.main_media.state
    data = await state.get_data()
    assert "desired_vibe_ids" in data
    assert set(data["desired_vibe_ids"]) == {vibe1.id, vibe7.id}
    # ASK_MEDIA отправлен через callback.message.answer.
    cb.message.answer.assert_awaited()
    answered = [call.args[0] for call in cb.message.answer.await_args_list]
    assert texts.ASK_MEDIA in answered


# ----------------------------- on_vibe_any_desired --------------------------


@pytest.mark.asyncio
async def test_on_vibe_any_desired_stores_empty_and_advances(storage) -> None:
    """«Любой вайб» → desired_vibe_ids=[], переход к main_media."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.desired_vibe)
    await state.update_data(desired_vibe_numbers=[5, 10])

    cb = _mock_callback()

    await on_vibe_any_desired(cb, state)

    data = await state.get_data()
    assert data["desired_vibe_ids"] == []
    assert await state.get_state() == RegistrationStates.main_media.state
    cb.message.answer.assert_awaited()
    answered = [call.args[0] for call in cb.message.answer.await_args_list]
    assert texts.ASK_MEDIA in answered


# ----------------------------- on_vibe_page_desired -------------------------


@pytest.mark.asyncio
async def test_on_vibe_page_desired_navigates(db_session, storage) -> None:
    """Навигация по страницам в пикере desired_vibe обновляет отображение."""
    state = _fsm(storage)
    await state.set_state(RegistrationStates.desired_vibe)
    await state.update_data(desired_vibe_numbers=[])

    cb = _mock_callback()
    cb.message.photo = None
    cb.message.edit_text = AsyncMock()
    cb_data = VibePageCb(role="desired", page=2)

    await on_vibe_page_desired(cb, cb_data, state, db_session)

    # Callback ответил (не зависает).
    cb.answer.assert_awaited()
