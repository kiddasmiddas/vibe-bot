"""Пейджер стоп-листов: одно сообщение со страницей-кнопками вместо флуда."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.admin.stopwords import (
    STOPWORDS_PAGE_SIZE,
    cb_stopwords_menu,
    cb_sw_list,
    cb_sw_open,
)
from app.bot.keyboards.admin import AdminMenuCb, AdminStopWordCb
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.user_repo import UserRepository


def _fsm(user_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


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
    user = await UserRepository(db_session).create(telegram_id=98001)
    user.is_moderator = True
    await db_session.flush()
    return user


async def _seed_words(db_session, admin, n: int) -> None:  # type: ignore[no-untyped-def]
    mod_repo = ModerationRepository(db_session)
    for i in range(n):
        await mod_repo.add_stop_word(
            pattern=f"pgrtest{i}", kind="word", category="other", admin_id=admin.id
        )


def _shown(mock_message) -> tuple[str, object]:
    call = mock_message.edit_text.call_args or mock_message.answer.call_args
    text = call.kwargs.get("text") or (call.args[0] if call.args else "")
    return text, call.kwargs.get("reply_markup")


def _item_buttons(markup) -> list[str]:
    return [
        btn.text
        for row in markup.inline_keyboard
        for btn in row
        if btn.text.startswith(("✅", "❌"))
    ]


@pytest.mark.asyncio
async def test_stopwords_menu_is_single_paged_message(db_session) -> None:
    """Вход в раздел — ОДНО сообщение с кнопками, не флуд карточек."""
    admin = await _make_admin(db_session)
    await _seed_words(db_session, admin, STOPWORDS_PAGE_SIZE + 3)
    callback = _mock_callback()

    await cb_stopwords_menu(callback, admin, db_session, _fsm(admin.telegram_id))

    text, markup = _shown(callback.message)
    assert "Стоп-листы" in text and "стр. 1/" in text
    assert len(_item_buttons(markup)) == STOPWORDS_PAGE_SIZE
    # Одно сообщение (show_screen), не N отдельных.
    assert callback.message.answer.await_count + callback.message.edit_text.await_count == 1


@pytest.mark.asyncio
async def test_stopwords_second_page_and_clamp(db_session) -> None:
    admin = await _make_admin(db_session)
    await _seed_words(db_session, admin, STOPWORDS_PAGE_SIZE + 3)
    total = await AdminRepository(db_session).count_stop_words()
    last_page = (total - 1) // STOPWORDS_PAGE_SIZE
    callback = _mock_callback()

    await cb_sw_list(
        callback,
        AdminStopWordCb(action="list", page=last_page),
        admin,
        db_session,
        _fsm(admin.telegram_id),
    )
    text, markup = _shown(callback.message)
    assert f"стр. {last_page + 1}/" in text
    assert len(_item_buttons(markup)) == total - last_page * STOPWORDS_PAGE_SIZE

    # Кривая страница из стейл-callback'а зажимается, не падает.
    callback2 = _mock_callback()
    await cb_sw_list(
        callback2,
        AdminStopWordCb(action="list", page=99),
        admin,
        db_session,
        _fsm(admin.telegram_id),
    )
    text2, _ = _shown(callback2.message)
    assert "стр." in text2


@pytest.mark.asyncio
async def test_stopword_open_card_in_place_keeps_page(db_session) -> None:
    """Карточка открывается на месте; «Назад» ведёт на ту же страницу."""
    admin = await _make_admin(db_session)
    await _seed_words(db_session, admin, 1)
    sw = (await AdminRepository(db_session).list_stop_words(limit=1))[0]
    callback = _mock_callback()

    await cb_sw_open(
        callback, AdminStopWordCb(action="open", sw_id=sw.id, page=2), admin, db_session
    )

    text, markup = _shown(callback.message)
    assert sw.pattern in text
    back_cbs = [
        AdminStopWordCb.unpack(btn.callback_data)
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data and btn.callback_data.startswith("adm_sw:list")
    ]
    assert back_cbs and back_cbs[0].page == 2


@pytest.mark.asyncio
async def test_stopwords_empty_shows_actions(db_session) -> None:
    """Пустой список — экран с «Добавить»/«Поиск», без падений.

    В сидах есть стоп-слова — чистим таблицу в транзакции теста (откатится)."""
    from sqlalchemy import delete

    from app.db.models.moderation import StopWord

    admin = await _make_admin(db_session)
    await db_session.execute(delete(StopWord))
    assert await AdminRepository(db_session).count_stop_words() == 0
    callback = _mock_callback()

    await cb_stopwords_menu(callback, admin, db_session, _fsm(admin.telegram_id))

    text, markup = _shown(callback.message)
    assert "Стоп-слов нет" in text
    assert markup is not None
    assert len(_item_buttons(markup)) == 0


@pytest.mark.asyncio
async def test_stopwords_non_admin_ignored(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=98002)  # не админ
    callback = _mock_callback()

    await cb_stopwords_menu(callback, user, db_session, _fsm(user.telegram_id))

    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_menu_cb_unused_import_guard() -> None:
    """AdminMenuCb остаётся точкой входа (smoke на пересборку роутера)."""
    assert AdminMenuCb(action="stopwords").pack()
