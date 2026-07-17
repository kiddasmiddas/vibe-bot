"""Карусель «✏️ Тексты»: карточки, сохранение оверрайда, сброс, гарды.

Оверрайды живут в app_settings (text_*); сообщения хранятся как html_text,
кнопки — как plain text. Валидация плейсхолдеров держит state для повтора.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.admin.bot_texts import (
    cb_texts_edit,
    cb_texts_open,
    cb_texts_reset,
    on_texts_new_value,
)
from app.bot.keyboards.admin import AdminTextsCb
from app.bot.states.admin import AdminTextsStates
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.services import bot_texts
from app.services.bot_texts import GROUPS, REGISTRY


def _fsm(user_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


def _mock_message(*, text: str | None = None, html_text: str | None = None) -> MagicMock:
    message = MagicMock()
    message.text = text if text is not None else "screen"
    message.html_text = html_text if html_text is not None else (text or "")
    # show_screen считает сообщение медиа, если любое из полей truthy.
    message.photo = None
    message.video = None
    message.animation = None
    message.document = None
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    return message


def _mock_callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = _mock_message()
    return callback


async def _make_admin(db_session):  # type: ignore[no-untyped-def]
    user = await UserRepository(db_session).create(telegram_id=97001)
    user.is_moderator = True
    await db_session.flush()
    return user


def _idx_of(key: str, group: str = "notif") -> int:
    return next(i for i, s in enumerate(GROUPS[group]) if s.key == key)


@pytest.mark.asyncio
async def test_open_renders_card_with_default(db_session) -> None:
    admin = await _make_admin(db_session)
    callback = _mock_callback()
    idx = _idx_of(bot_texts.KEY_LIKE_PUSH_ONE)

    await cb_texts_open(
        callback,
        AdminTextsCb(action="open", group="notif", idx=idx),
        admin,
        db_session,
        _fsm(admin.telegram_id),
    )

    callback.message.edit_text.assert_awaited()
    call = callback.message.edit_text.call_args
    shown = call.kwargs.get("text") or (call.args[0] if call.args else "")

    assert REGISTRY[bot_texts.KEY_LIKE_PUSH_ONE].default in shown


@pytest.mark.asyncio
async def test_edit_saves_override_and_clears_state(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    idx = _idx_of(bot_texts.KEY_LIKE_PUSH_MANY)
    callback = _mock_callback()
    await cb_texts_edit(callback, AdminTextsCb(action="edit", group="notif", idx=idx), admin, state)
    assert await state.get_state() == AdminTextsStates.ask_value.state

    message = _mock_message(text="Целых {n} новых лайков!")
    await on_texts_new_value(message, state, admin, db_session)

    saved = await SettingsRepository(db_session).get(bot_texts.KEY_LIKE_PUSH_MANY)
    assert saved == "Целых {n} новых лайков!"
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_edit_rejects_unknown_placeholder_and_keeps_state(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    idx = _idx_of(bot_texts.KEY_LIKE_PUSH_MANY)
    await state.set_state(AdminTextsStates.ask_value)
    await state.update_data(text_group="notif", text_idx=idx, text_key=bot_texts.KEY_LIKE_PUSH_MANY)

    message = _mock_message(text="Лайков: {count}")
    await on_texts_new_value(message, state, admin, db_session)

    assert await SettingsRepository(db_session).get(bot_texts.KEY_LIKE_PUSH_MANY) is None
    # Состояние не сброшено — админ может прислать текст повторно.
    assert await state.get_state() == AdminTextsStates.ask_value.state


@pytest.mark.asyncio
async def test_edit_button_via_edit_btn_saves_linked_button(db_session) -> None:
    """«✏️ Редактировать кнопку» на карточке пуша правит связанный button_key."""
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    idx = _idx_of(bot_texts.KEY_LIKE_PUSH_ONE)  # у лайка кнопка «Посмотреть»
    callback = _mock_callback()

    await cb_texts_edit(
        callback, AdminTextsCb(action="edit_btn", group="notif", idx=idx), admin, state
    )
    data = await state.get_data()
    assert data["text_key"] == bot_texts.KEY_BTN_VIEW_LIKES

    message = _mock_message(text="Глянуть", html_text="<b>Глянуть</b>")
    await on_texts_new_value(message, state, admin, db_session)

    # Для кнопки хранится plain message.text (без HTML-обёртки).
    assert await SettingsRepository(db_session).get(bot_texts.KEY_BTN_VIEW_LIKES) == "Глянуть"
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_stale_state_without_text_key_is_safe_noop(db_session) -> None:
    """FSM-state старого формата (без text_key, остался с прошлого деплоя) —
    ввод не сохраняется никуда, state сбрасывается."""
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminTextsStates.ask_value)
    await state.update_data(text_group="notif", text_idx=0)  # text_key отсутствует

    message = _mock_message(text="Куда-то не туда")
    await on_texts_new_value(message, state, admin, db_session)

    for spec in GROUPS["notif"]:
        assert await SettingsRepository(db_session).get(spec.key) is None
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_reset_button_via_reset_btn(db_session) -> None:
    admin = await _make_admin(db_session)
    repo = SettingsRepository(db_session)
    await repo.set(bot_texts.KEY_BTN_OPEN_POST, "Тык")
    idx = _idx_of(bot_texts.KEY_COMMENT_PUSH)  # у коммента кнопка «Открыть пост»
    callback = _mock_callback()

    await cb_texts_reset(
        callback, AdminTextsCb(action="reset_btn", group="notif", idx=idx), admin, db_session
    )

    assert await repo.get(bot_texts.KEY_BTN_OPEN_POST) is None


@pytest.mark.asyncio
async def test_reset_deletes_override(db_session) -> None:
    admin = await _make_admin(db_session)
    repo = SettingsRepository(db_session)
    await repo.set(bot_texts.KEY_LIKE_PUSH_ONE, "Кастом")
    callback = _mock_callback()
    idx = _idx_of(bot_texts.KEY_LIKE_PUSH_ONE)

    await cb_texts_reset(
        callback, AdminTextsCb(action="reset", group="notif", idx=idx), admin, db_session
    )

    assert await repo.get(bot_texts.KEY_LIKE_PUSH_ONE) is None


@pytest.mark.asyncio
async def test_non_admin_cannot_save(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=97002)  # не админ
    state = _fsm(user.telegram_id)
    await state.set_state(AdminTextsStates.ask_value)
    await state.update_data(text_group="notif", text_idx=0, text_key=GROUPS["notif"][0].key)

    message = _mock_message(text="Хакнул")
    await on_texts_new_value(message, state, user, db_session)

    spec = GROUPS["notif"][0]
    assert await SettingsRepository(db_session).get(spec.key) is None
    assert await state.get_state() is None
