from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import main_menu_kb
from app.db.models.user import User
from app.services import user_service
from app.texts import gdpr as texts

router = Router(name="gdpr")


class GdprConfirmCb(CallbackData, prefix="gdpr"):
    action: str  # "delete" | "cancel"


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_CONFIRM,
                    callback_data=GdprConfirmCb(action="delete").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=texts.BTN_CANCEL,
                    callback_data=GdprConfirmCb(action="cancel").pack(),
                ),
            ],
        ]
    )


@router.message(Command("delete", "delete_my_data"))
async def cmd_delete_my_data(message: Message) -> None:
    await message.answer(
        texts.CONFIRM_PROMPT,
        reply_markup=_confirm_keyboard(),
    )


@router.callback_query(GdprConfirmCb.filter())
async def cb_gdpr_confirm(
    callback: CallbackQuery,
    callback_data: GdprConfirmCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    if callback_data.action == "cancel":
        await callback.message.edit_text(texts.CANCELLED)
        await callback.answer()
        return

    # action == "delete"
    logger.info(
        "gdpr: user_id={} telegram_id={} confirmed deletion",
        user.id,
        user.telegram_id,
    )
    # Транзакцией управляет UserMiddleware (commit после хендлера) — здесь
    # отдельный session.begin() не открываем, иначе InvalidRequestError.
    await user_service.delete_user_data(user, db_session)

    await callback.message.edit_text(texts.DELETED)
    await callback.message.answer(
        texts.CREATE_NEW_PROFILE_PROMPT,
        reply_markup=main_menu_kb(is_registered=False),
    )
    await callback.answer()
