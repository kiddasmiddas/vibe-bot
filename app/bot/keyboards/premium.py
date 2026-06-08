from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import premium as texts

# Допустимые значения тарифа в callback_data.
TARIFF_WEEK = "week"
TARIFF_MONTH = "month"
TARIFF_YEAR = "year"
ALLOWED_TARIFFS = (TARIFF_WEEK, TARIFF_MONTH, TARIFF_YEAR)


class PremiumActionCb(CallbackData, prefix="prem"):
    """Callback экрана Premium.

    action: 'buy' — покупка подписки.
    tariff: 'week' | 'month' | 'year' — выбранный тариф. Пустая строка =
            legacy-инвойс (для обратной совместимости со старыми сообщениями).
    """

    action: str
    tariff: str = ""


def premium_screen_kb() -> InlineKeyboardMarkup:
    """Клавиатура экрана Premium — три кнопки выбора тарифа."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_TARIFF_WEEK,
        callback_data=PremiumActionCb(action="buy", tariff=TARIFF_WEEK),
    )
    builder.button(
        text=texts.BTN_TARIFF_MONTH,
        callback_data=PremiumActionCb(action="buy", tariff=TARIFF_MONTH),
    )
    builder.button(
        text=texts.BTN_TARIFF_YEAR,
        callback_data=PremiumActionCb(action="buy", tariff=TARIFF_YEAR),
    )
    builder.adjust(1, 1, 1)
    return builder.as_markup()
