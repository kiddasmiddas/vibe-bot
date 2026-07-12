"""Админ-пикер вайбов: переименование по номеру, тумблер, коллаж → вайб-обложка."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.admin.vibes import (
    cb_vibes_toggle,
    on_vibes_image,
    on_vibes_title,
)
from app.bot.keyboards.admin import AdminVibesCb
from app.bot.states.admin import AdminVibesStates
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.user_repo import UserRepository


def _fsm(user_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


def _mock_message(*, text: str | None = None, photo: bool = False) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    if photo:
        size = MagicMock()
        size.file_id = "AgAC-new-collage"
        message.photo = [size]
    else:
        message.photo = None
    return message


async def _make_admin(db_session):  # type: ignore[no-untyped-def]
    # is_admin() = telegram_id в ADMIN_TELEGRAM_IDS ИЛИ модератор; в тестах
    # проще дать флаг модератора (доступ к разделу тот же).
    user = await UserRepository(db_session).create(telegram_id=98001)
    user.is_moderator = True
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_rename_vibe_by_number(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminVibesStates.ask_title)
    await state.update_data(vibe_number=5, vibe_page=0)
    message = _mock_message(text="WhimsiGoth")

    await on_vibes_title(message, state, admin, db_session)

    vibe = await DictionaryRepository(db_session).get_vibe_by_number(5)
    assert vibe is not None and vibe.title == "WhimsiGoth"
    assert await state.get_state() is None
    message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_rename_rejects_empty_title(db_session) -> None:
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminVibesStates.ask_title)
    await state.update_data(vibe_number=5, vibe_page=0)
    before = (await DictionaryRepository(db_session).get_vibe_by_number(5)).title
    message = _mock_message(text="   ")

    await on_vibes_title(message, state, admin, db_session)

    after = (await DictionaryRepository(db_session).get_vibe_by_number(5)).title
    assert after == before
    # Состояние не сброшено — админ может прислать название повторно.
    assert await state.get_state() == AdminVibesStates.ask_title.state


@pytest.mark.asyncio
async def test_page_image_saved_to_cover_vibe(db_session) -> None:
    """Коллаж страницы 2 (вайбы 10–18) пишется в вайб-обложку №10."""
    admin = await _make_admin(db_session)
    state = _fsm(admin.telegram_id)
    await state.set_state(AdminVibesStates.ask_image)
    await state.update_data(vibe_page=1)
    message = _mock_message(photo=True)

    await on_vibes_image(message, state, admin, db_session)

    repo = DictionaryRepository(db_session)
    cover = await repo.get_vibe_by_number(10)
    assert cover is not None and cover.image_file_id == "AgAC-new-collage"
    # Соседний вайб страницы не тронут.
    neighbor = await repo.get_vibe_by_number(11)
    assert neighbor is not None and neighbor.image_file_id != "AgAC-new-collage"
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_toggle_vibe_active(db_session) -> None:
    admin = await _make_admin(db_session)
    repo = DictionaryRepository(db_session)
    assert (await repo.get_vibe_by_number(7)).is_active is True

    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = _mock_message()
    # show_screen редактирует сообщение — мокаем методы редактирования.
    callback.message.edit_text = AsyncMock()
    callback.message.delete = AsyncMock()

    await cb_vibes_toggle(
        callback, AdminVibesCb(action="toggle", page=0, number=7), admin, db_session
    )

    assert (await repo.get_vibe_by_number(7)).is_active is False


@pytest.mark.asyncio
async def test_non_admin_cannot_rename(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=98002)  # не админ
    state = _fsm(user.telegram_id)
    await state.set_state(AdminVibesStates.ask_title)
    await state.update_data(vibe_number=5, vibe_page=0)
    before = (await DictionaryRepository(db_session).get_vibe_by_number(5)).title
    message = _mock_message(text="Хакнул")

    await on_vibes_title(message, state, user, db_session)

    assert (await DictionaryRepository(db_session).get_vibe_by_number(5)).title == before
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_picker_buttons_show_titles(db_session) -> None:
    """Кнопки юзерского пикера — названия вайбов, переименование видно сразу."""
    from app.bot.keyboards.registration import vibe_picker_kb
    from app.bot.utils.vibe_picker import fetch_page_titles
    from app.db.models.dictionaries import Vibe

    repo = DictionaryRepository(db_session)
    vibe = await repo.get_vibe_by_number(2)
    await repo.update_item(Vibe, vibe.id, title="Готика")

    titles = await fetch_page_titles(db_session, 0)
    assert titles[2] == "Готика"

    kb = vibe_picker_kb(
        role="own", page=0, total_pages=4, done_text="Готово", any_text="Любой", titles=titles
    )
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Готика" in button_texts
    assert "2" not in button_texts

    # Выключенный вайб пропадает из titles → кнопка-фолбэк с цифрой (как раньше).
    await repo.set_active(Vibe, vibe.id, is_active=False)
    titles2 = await fetch_page_titles(db_session, 0)
    assert 2 not in titles2
    kb2 = vibe_picker_kb(
        role="own", page=0, total_pages=4, done_text="Готово", any_text="Любой", titles=titles2
    )
    button_texts2 = [btn.text for row in kb2.inline_keyboard for btn in row]
    assert "2" in button_texts2 and "Готика" not in button_texts2


@pytest.mark.asyncio
async def test_admin_page_labels_have_numbers_and_inactive_mark(db_session) -> None:
    """Кнопки админ-пикера: «N · Title», выключенные помечены ❌."""
    from app.bot.handlers.admin.vibes import _page_labels
    from app.db.models.dictionaries import Vibe

    repo = DictionaryRepository(db_session)
    vibe = await repo.get_vibe_by_number(3)
    await repo.update_item(Vibe, vibe.id, title="Сцена")
    labels = await _page_labels(db_session, 0)
    assert labels[3] == "3 · Сцена"

    await repo.set_active(Vibe, vibe.id, is_active=False)
    labels2 = await _page_labels(db_session, 0)
    assert labels2[3] == "❌ 3 · Сцена"
