"""Раздел «⚙️ Настройки» → «📏 Лимиты анкеты»: сохранение и валидация диапазонов.

Плюс лимит фандомов в мульти-селекте: добавить сверх капа нельзя, снять можно
(старые анкеты с превышением не блокируются).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.admin.app_config import on_bio_max, on_fandoms_max
from app.bot.handlers.registration import _handle_multi_select
from app.bot.states.admin import AdminAppCfgStates
from app.bot.utils.pagination import MultiSelectCb
from app.db.repositories.settings_repo import (
    SETTING_BIO_MAX_LENGTH,
    SETTING_FANDOMS_MAX_SELECTED,
    SettingsRepository,
)
from app.db.repositories.user_repo import UserRepository
from app.texts import registration as reg_texts


def _fsm(user_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


def _mock_message(text: str) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


async def _make_admin(db_session):  # type: ignore[no-untyped-def]
    user = await UserRepository(db_session).create(telegram_id=96001)
    user.is_moderator = True
    await db_session.flush()
    return user


# --------------------------- сохранение лимитов ---------------------------


@pytest.mark.asyncio
async def test_fandoms_limit_saved(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminAppCfgStates.ask_fandoms_max)

    await on_fandoms_max(_mock_message("10"), state, admin, db_session)

    assert await SettingsRepository(db_session).get_int(SETTING_FANDOMS_MAX_SELECTED) == 10
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_fandoms_limit_rejects_out_of_range(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminAppCfgStates.ask_fandoms_max)
    before = await SettingsRepository(db_session).get_int(SETTING_FANDOMS_MAX_SELECTED)

    for bad in ("0", "51", "abc", "-3"):
        await on_fandoms_max(_mock_message(bad), state, admin, db_session)

    assert await SettingsRepository(db_session).get_int(SETTING_FANDOMS_MAX_SELECTED) == before
    # Состояние держится — админ может прислать число повторно.
    assert await state.get_state() == AdminAppCfgStates.ask_fandoms_max.state


@pytest.mark.asyncio
async def test_bio_limit_saved(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminAppCfgStates.ask_bio_max)

    await on_bio_max(_mock_message("300"), state, admin, db_session)

    assert await SettingsRepository(db_session).get_int(SETTING_BIO_MAX_LENGTH) == 300


# --------------------------- лимит в мульти-селекте ---------------------------


def _toggle_callback(value: int) -> tuple[MagicMock, MultiSelectCb]:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.delete = AsyncMock()  # fallback-ветка delete+resend
    return callback, MultiSelectCb(action="toggle", entity="fandom", value=value)


async def _run_toggle(state: FSMContext, db_session, value: int, *, max_selected: int) -> MagicMock:  # type: ignore[no-untyped-def]
    callback, callback_data = _toggle_callback(value)
    await _handle_multi_select(
        callback=callback,
        callback_data=callback_data,
        state=state,
        db_session=db_session,
        state_key="fandom_ids",
        page_key="fandom_page",
        require_non_empty=True,
        empty_error="пусто",
        on_done=AsyncMock(),
        on_back=AsyncMock(),
        on_page=AsyncMock(),
        on_build_kb=None,
        max_selected=max_selected,
        limit_error=reg_texts.FANDOMS_LIMIT_REACHED,
    )
    return callback


@pytest.mark.asyncio
async def test_toggle_blocked_at_limit(db_session) -> None:
    state = _fsm(555)
    await state.update_data(fandom_ids=[1, 2, 3])

    callback = await _run_toggle(state, db_session, value=4, max_selected=3)

    # Alert с лимитом, выбор не изменился.
    args, kwargs = callback.answer.call_args
    assert "3" in args[0] and kwargs.get("show_alert") is True
    assert sorted((await state.get_data())["fandom_ids"]) == [1, 2, 3]


@pytest.mark.asyncio
async def test_toggle_remove_allowed_over_limit(db_session) -> None:
    """Старая анкета с превышением лимита: снять выбор можно всегда."""
    state = _fsm(556)
    await state.update_data(fandom_ids=[1, 2, 3, 4, 5])

    await _run_toggle(state, db_session, value=5, max_selected=3)

    assert sorted((await state.get_data())["fandom_ids"]) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_toggle_add_under_limit(db_session) -> None:
    state = _fsm(557)
    await state.update_data(fandom_ids=[1])

    await _run_toggle(state, db_session, value=2, max_selected=3)

    assert sorted((await state.get_data())["fandom_ids"]) == [1, 2]
