from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from app.bot.middlewares.ban_middleware import BanMiddleware
from app.texts import common as texts


@pytest.mark.asyncio
async def test_banned_user_message_does_not_reach_handler() -> None:
    mw = BanMiddleware()
    handler = AsyncMock()

    user = MagicMock(is_banned=True)
    message = MagicMock(spec=Message)
    message.answer = AsyncMock()

    data = {"user": user}

    result = await mw(handler, message, data)

    assert result is None
    handler.assert_not_called()
    message.answer.assert_awaited_once_with(texts.BANNED)


@pytest.mark.asyncio
async def test_banned_user_callback_gets_alert() -> None:
    mw = BanMiddleware()
    handler = AsyncMock()

    user = MagicMock(is_banned=True)
    callback = MagicMock(spec=CallbackQuery)
    callback.answer = AsyncMock()

    data = {"user": user}

    result = await mw(handler, callback, data)

    assert result is None
    handler.assert_not_called()
    callback.answer.assert_awaited_once_with(texts.BANNED, show_alert=True)


@pytest.mark.asyncio
async def test_not_banned_user_passes_through() -> None:
    mw = BanMiddleware()
    handler = AsyncMock(return_value="ok")

    user = MagicMock(is_banned=False)
    event = MagicMock()
    data = {"user": user}

    result = await mw(handler, event, data)

    assert result == "ok"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_user_passes_through() -> None:
    mw = BanMiddleware()
    handler = AsyncMock(return_value="ok")

    event = MagicMock()
    data: dict = {"user": None}

    result = await mw(handler, event, data)

    assert result == "ok"
    handler.assert_awaited_once()
