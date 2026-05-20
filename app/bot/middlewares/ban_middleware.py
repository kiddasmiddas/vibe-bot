from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.texts import common as texts


class BanMiddleware(BaseMiddleware):
    """Outer middleware. Регистрируется ПОСЛЕ `UserMiddleware` —
    рассчитывает на `data['user']`. Если пользователь забанен — отвечает
    короткой заглушкой и НЕ пропускает апдейт дальше.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        if user is None or not getattr(user, "is_banned", False):
            return await handler(event, data)

        await _notify_banned(event)
        return None


async def _notify_banned(event: TelegramObject) -> None:
    message: Message | None = None
    callback: CallbackQuery | None = None

    if isinstance(event, Update):
        message = event.message
        callback = event.callback_query
    elif isinstance(event, Message):
        message = event
    elif isinstance(event, CallbackQuery):
        callback = event

    if callback is not None:
        await callback.answer(texts.BANNED, show_alert=True)
        return
    if message is not None:
        await message.answer(texts.BANNED)
