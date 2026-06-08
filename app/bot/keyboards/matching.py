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


class MatchingUndoCb(CallbackData, prefix="mt_undo"):
    """Callback кнопки «↩️ Назад» — возврат к предыдущей анкете (Premium).

    Stack глубины 1 — поддерживается только один шаг назад. Идентификатор
    предыдущего кандидата хранится в FSM, поэтому в callback_data ничего
    дополнительного передавать не нужно.
    """


def superlike_cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура с одной кнопкой «Отмена» под запросом superlike-сообщения."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CANCEL_SUPERLIKE, callback_data=SuperlikeCancelCb())
    return builder.as_markup()


def actions_kb(target_user_id: int, *, show_undo: bool = False) -> InlineKeyboardMarkup:
    """Inline-клавиатура действий над карточкой кандидата.

    Раскладка без `show_undo` — 2 + 1 + 3:
        [❤️ Лайк]   [👎 Дизлайк]
        [💬 С сообщением]
        [🚩 Жалоба] [🚫 Блок] [⏭]

    При `show_undo=True` (Premium-доступ И есть предыдущая анкета в стэке)
    под основными действиями добавляется отдельный ряд с одной кнопкой:
        [↩️ Назад]

    Free-юзеры этот ряд не видят — кнопка не рендерится. Это и UI-гейт,
    и страховка от подмены callback_data (хэндлер всё равно перепроверяет
    `has_premium_access`).
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
    if show_undo:
        builder.button(text=texts.BTN_UNDO, callback_data=MatchingUndoCb())
        builder.adjust(2, 1, 3, 1)
    else:
        builder.adjust(2, 1, 3)
    return builder.as_markup()
