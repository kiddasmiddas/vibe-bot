"""Раздел «Пользователи»: вход показывает меню (без авто-выгрузки),
CSV отдаётся только по кнопке «Выгрузить всех»."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers.admin.users import cb_users_export, cb_users_menu
from app.db.repositories.user_repo import UserRepository


def _fsm(user_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


def _mock_message() -> MagicMock:
    message = MagicMock()
    message.text = "screen"
    message.photo = None
    message.video = None
    message.animation = None
    message.document = None
    message.answer = AsyncMock()
    message.answer_document = AsyncMock()
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    return message


def _mock_callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = _mock_message()
    return callback


async def _make_admin(db_session):  # type: ignore[no-untyped-def]
    user = await UserRepository(db_session).create(telegram_id=95001)
    user.is_moderator = True
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_menu_does_not_auto_export(db_session) -> None:
    """Вход в раздел показывает меню и НЕ выгружает файл автоматически."""
    admin = await _make_admin(db_session)
    callback = _mock_callback()

    await cb_users_menu(callback, admin, _fsm(admin.telegram_id))

    callback.message.answer_document.assert_not_awaited()
    # Меню отрисовано (edit_text либо answer — show_screen).
    assert callback.message.edit_text.await_count + callback.message.answer.await_count >= 1


@pytest.mark.asyncio
async def test_export_button_sends_csv(db_session) -> None:
    """Кнопка «Выгрузить всех» отдаёт CSV-документ."""
    admin = await _make_admin(db_session)
    await UserRepository(db_session).create(telegram_id=95002, username="bob")
    callback = _mock_callback()

    await cb_users_export(callback, admin, _fsm(admin.telegram_id), db_session)

    callback.message.answer_document.assert_awaited_once()
    doc = callback.message.answer_document.call_args.args[0]
    assert doc.filename.startswith("users_") and doc.filename.endswith(".csv")


@pytest.mark.asyncio
async def test_non_admin_cannot_export(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=95003)  # не админ
    callback = _mock_callback()

    await cb_users_export(callback, user, _fsm(user.telegram_id), db_session)

    callback.message.answer_document.assert_not_awaited()
