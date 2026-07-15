"""Пейджер справочников: одно сообщение со страницей-кнопками вместо флуда."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.handlers.admin.dictionaries import cb_dict_list, cb_dict_open
from app.bot.keyboards.admin import DICTS_PAGE_SIZE, AdminDictCb
from app.db.models.dictionaries import Fandom
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.user_repo import UserRepository


def _mock_callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    message = MagicMock()
    message.text = "screen"
    message.photo = None
    message.video = None
    message.animation = None
    message.document = None
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    callback.message = message
    return callback


async def _make_admin(db_session):  # type: ignore[no-untyped-def]
    user = await UserRepository(db_session).create(telegram_id=96001)
    user.is_moderator = True
    await db_session.flush()
    return user


def _shown(mock_message) -> tuple[str, object]:
    """(текст, разметка) из последнего edit_text/answer show_screen'а."""
    call = mock_message.edit_text.call_args or mock_message.answer.call_args
    text = call.kwargs.get("text") or (call.args[0] if call.args else "")
    return text, call.kwargs.get("reply_markup")


def _buttons(markup) -> list[str]:
    return [btn.text for row in markup.inline_keyboard for btn in row]


@pytest.mark.asyncio
async def test_dict_list_is_single_paged_message(db_session) -> None:
    """Список — ОДНО сообщение: элементы кнопками, всё сверх страницы — листанием."""
    admin = await _make_admin(db_session)
    callback = _mock_callback()

    await cb_dict_list(callback, AdminDictCb(action="fandoms", model="fandom"), admin, db_session)

    text, markup = _shown(callback.message)
    assert "Фандомы" in text and "стр. 1/" in text
    labels = _buttons(markup)
    # Сид = 15 фандомов → 2 страницы по DICTS_PAGE_SIZE: на первой ровно 8 элементов.
    item_labels = [b for b in labels if b.startswith(("✅", "❌"))]
    assert len(item_labels) == DICTS_PAGE_SIZE
    # Флуда отдельными сообщениями нет: только show_screen (одно сообщение).
    assert callback.message.answer.await_count + callback.message.edit_text.await_count == 1


@pytest.mark.asyncio
async def test_dict_list_second_page_and_clamp(db_session) -> None:
    admin = await _make_admin(db_session)
    total = len(await DictionaryRepository(db_session).list_all(Fandom))
    callback = _mock_callback()

    await cb_dict_list(
        callback, AdminDictCb(action="page", model="fandom", page=1), admin, db_session
    )
    text, markup = _shown(callback.message)
    assert "стр. 2/" in text
    item_labels = [b for b in _buttons(markup) if b.startswith(("✅", "❌"))]
    assert len(item_labels) == total - DICTS_PAGE_SIZE

    # Кривая страница из стейл-callback'а зажимается в диапазон, не падает.
    callback2 = _mock_callback()
    await cb_dict_list(
        callback2, AdminDictCb(action="page", model="fandom", page=99), admin, db_session
    )
    text2, _ = _shown(callback2.message)
    assert "стр." in text2


@pytest.mark.asyncio
async def test_dict_open_replaces_in_place(db_session) -> None:
    """Тап по элементу открывает карточку в том же сообщении (без нового)."""
    admin = await _make_admin(db_session)
    fandom = (await DictionaryRepository(db_session).list_all(Fandom))[0]
    callback = _mock_callback()

    await cb_dict_open(
        callback,
        AdminDictCb(action="open", model="fandom", item_id=fandom.id),
        admin,
        db_session,
    )

    text, markup = _shown(callback.message)
    assert fandom.title in text
    assert markup is not None


@pytest.mark.asyncio
async def test_dict_list_non_admin_ignored(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=96002)  # не админ
    callback = _mock_callback()

    await cb_dict_list(callback, AdminDictCb(action="fandoms", model="fandom"), user, db_session)

    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_not_awaited()
