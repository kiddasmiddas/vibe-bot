"""Inline-клавиатура с действиями над карточкой кандидата (этап 4.2)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import matching as texts


class MatchingActionCb(CallbackData, prefix="match"):
    """Callback на действие в карточке кандидата.

    `action` ∈ {'like', 'superlike', 'dislike', 'skip', 'complain', 'block'}.
    `target_user_id` — `User.id` (внутренний PK), не Telegram ID.
    """

    action: str
    target_user_id: int


class SuperlikeCancelCb(CallbackData, prefix="slcancel"):
    """Callback кнопки «Отмена» под запросом текста для лайка с сообщением."""


def superlike_cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура с одной кнопкой «Отмена» под запросом superlike-сообщения."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CANCEL_SUPERLIKE, callback_data=SuperlikeCancelCb())
    return builder.as_markup()


def actions_kb(target_user_id: int) -> InlineKeyboardMarkup:
    """Inline-клавиатура действий над карточкой кандидата.

    Раскладка 2 + 1 + 3 — длинная кнопка «С сообщением» занимает целый ряд,
    иначе на узких экранах (мобильный Telegram) её подпись обрезается:
        [❤️ Лайк]   [👎 Дизлайк]
        [💬 С сообщением]
        [🚩 Жалоба] [🚫 Блок] [⏭]
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_LIKE,
        callback_data=MatchingActionCb(action="like", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_DISLIKE,
        callback_data=MatchingActionCb(action="dislike", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_SUPERLIKE,
        callback_data=MatchingActionCb(action="superlike", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_COMPLAIN,
        callback_data=MatchingActionCb(action="complain", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_BLOCK,
        callback_data=MatchingActionCb(action="block", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_SKIP,
        callback_data=MatchingActionCb(action="skip", target_user_id=target_user_id),
    )
    builder.adjust(2, 1, 3)
    return builder.as_markup()
