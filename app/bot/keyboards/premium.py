from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import premium as texts


class PremiumActionCb(CallbackData, prefix="prem"):
    action: str


def premium_screen_kb() -> InlineKeyboardMarkup:
    """Клавиатура экрана Premium — кнопка «Оплатить»."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_BUY,
        callback_data=PremiumActionCb(action="buy"),
    )
    return builder.as_markup()
