"""Inline-клавиатуры для потока «Блокировка» (этап 5.2)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import blocks as texts


class BlockConfirmCb(CallbackData, prefix="blk"):
    """Подтверждение/отмена блокировки."""

    action: str  # 'confirm' | 'cancel'
    target_user_id: int


def confirm_block_kb(target_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_CONFIRM_BLOCK,
        callback_data=BlockConfirmCb(action="confirm", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_CANCEL_BLOCK,
        callback_data=BlockConfirmCb(action="cancel", target_user_id=target_user_id),
    )
    builder.adjust(1, 1)
    return builder.as_markup()
