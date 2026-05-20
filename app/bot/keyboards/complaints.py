"""Inline-клавиатуры для потока «Жалоба» (этап 5.1)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models.dictionaries import ComplaintReason
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.texts import complaints as texts


class ComplaintReasonCb(CallbackData, prefix="cr"):
    """Выбор причины жалобы."""

    reason_id: int
    target_user_id: int


class ComplaintCommentCb(CallbackData, prefix="cc"):
    """Действия в шаге ввода комментария."""

    action: str  # 'skip' | 'cancel'
    target_user_id: int


async def reasons_kb(
    target_user_id: int,
    dict_repo: DictionaryRepository,
) -> InlineKeyboardMarkup:
    """Клавиатура: одна кнопка на причину + ряд «Отмена»."""
    reasons = await dict_repo.list_active(ComplaintReason)
    builder = InlineKeyboardBuilder()
    for reason in reasons:
        builder.button(
            text=reason.title,
            callback_data=ComplaintReasonCb(
                reason_id=reason.id,
                target_user_id=target_user_id,
            ),
        )
    builder.button(
        text=texts.BTN_CANCEL,
        callback_data=ComplaintCommentCb(action="cancel", target_user_id=target_user_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def comment_kb(target_user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура шага ввода комментария: «Пропустить» / «Отмена»."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_SKIP_COMMENT,
        callback_data=ComplaintCommentCb(action="skip", target_user_id=target_user_id),
    )
    builder.button(
        text=texts.BTN_CANCEL,
        callback_data=ComplaintCommentCb(action="cancel", target_user_id=target_user_id),
    )
    builder.adjust(2)
    return builder.as_markup()
