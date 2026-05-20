"""Поток «Блокировка пользователя» (этап 5.2).

Запускается из карточки кандидата (matching.py) и из карточки входящего лайка
(matches.py) через публичный helper `start_block_flow`.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.blocks import BlockConfirmCb, confirm_block_kb
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.matching_repo import MatchingRepository
from app.services.analytics_events import EventType
from app.texts import blocks as texts

router = Router(name="blocks")


async def start_block_flow(
    callback: CallbackQuery,
    *,
    target_user_id: int,
) -> None:
    """Спрашивает подтверждение блокировки."""
    if callback.message is None:
        await callback.answer()
        return
    await callback.answer()
    await callback.message.answer(
        texts.ASK_BLOCK_CONFIRM,
        reply_markup=confirm_block_kb(target_user_id=target_user_id),
    )


@router.callback_query(BlockConfirmCb.filter(F.action == "confirm"))
async def on_block_confirm(
    callback: CallbackQuery,
    callback_data: BlockConfirmCb,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Записывает блок и подтверждает пользователю.

    На дубль блока (PK конфликт) реагируем мягко: говорим BLOCKED_OK всё равно.
    """
    if callback.message is None:
        await callback.answer()
        return

    target_user_id = callback_data.target_user_id
    repo = MatchingRepository(db_session)
    wrote = False
    try:
        async with db_session.begin_nested():
            await repo.add_block(blocker_id=user.id, blocked_id=target_user_id)
        wrote = True
    except IntegrityError as exc:
        logger.warning(
            "duplicate block from_user_id={} target_user_id={}: {}",
            user.id,
            target_user_id,
            exc,
        )

    if wrote:
        await AnalyticsRepository(db_session).log_event(
            user.id,
            event_type=EventType.USER_BLOCKED,
            payload={"target_user_id": target_user_id},
        )

    await callback.answer()
    await callback.message.answer(texts.BLOCKED_OK)
    # после блока — продолжить просмотр. Ленивый импорт,
    # чтобы избежать циклической зависимости с matching.py.
    from app.bot.handlers.matching import _show_next_candidate

    await _show_next_candidate(callback.message, db_session, bot, user)


@router.callback_query(BlockConfirmCb.filter(F.action == "cancel"))
async def on_block_cancel(
    callback: CallbackQuery,
    callback_data: BlockConfirmCb,
) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.BLOCK_CANCELLED)
