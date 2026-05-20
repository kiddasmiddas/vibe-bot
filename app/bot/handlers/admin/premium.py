"""Раздел «Premium» — ручная выдача/отзыв (10.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminMenuCb,
    AdminPremiumCb,
    admin_back_home_kb,
    premium_action_kb,
    premium_duration_kb,
)
from app.bot.states.admin import AdminPremiumStates
from app.db.models.user import User
from app.db.repositories.premium_repo import PremiumRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import (
    PREMIUM_GRANT_ASK_DURATION,
    PREMIUM_GRANTED,
    PREMIUM_NOT_FOUND,
    PREMIUM_REVOKED,
    PREMIUM_SEARCH_PROMPT,
    PREMIUM_USER_CARD,
)

router = Router(name="admin.premium")

_DURATIONS: dict[str, int] = {
    "dur_30": 30,
    "dur_90": 90,
    "dur_365": 365,
}


@router.callback_query(AdminMenuCb.filter(F.action == "premium"))
async def cb_premium_menu(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminPremiumStates.search_user_query)
    await callback.answer()
    if callback.message:
        await show_screen(
            callback.message, text=PREMIUM_SEARCH_PROMPT, reply_markup=admin_back_home_kb()
        )


@router.message(StateFilter(AdminPremiumStates.search_user_query), F.text)
async def on_premium_search(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    query = (message.text or "").strip()
    user_repo = UserRepository(db_session)
    results = await user_repo.search(query)
    if not results:
        await message.answer(PREMIUM_NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    await state.clear()
    for found in results[:3]:
        text = PREMIUM_USER_CARD.format(
            user_id=found.id,
            telegram_id=found.telegram_id,
            premium="✅" if found.is_premium else "❌",
            premium_until=found.premium_until.strftime("%Y-%m-%d") if found.premium_until else "—",
        )
        await message.answer(
            text,
            reply_markup=premium_action_kb(found.id, is_premium=found.is_premium),
            parse_mode="HTML",
        )


@router.callback_query(AdminPremiumCb.filter(F.action == "grant"))
async def cb_premium_grant_start(
    callback: CallbackQuery,
    callback_data: AdminPremiumCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminPremiumStates.ask_duration)
    await state.update_data(premium_target_user_id=callback_data.target_user_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            PREMIUM_GRANT_ASK_DURATION,
            reply_markup=premium_duration_kb(callback_data.target_user_id),
        )


@router.callback_query(AdminPremiumCb.filter(F.action.in_({"dur_30", "dur_90", "dur_365"})))
async def cb_premium_grant_confirm(
    callback: CallbackQuery,
    callback_data: AdminPremiumCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    days = _DURATIONS.get(callback_data.action, 30)
    target_user_id = callback_data.target_user_id
    until = datetime.now(tz=UTC) + timedelta(days=days)

    user_repo = UserRepository(db_session)
    prem_repo = PremiumRepository(db_session)
    await user_repo.set_premium(target_user_id, until)
    await prem_repo.create_subscription(
        user_id=target_user_id,
        ends_at=until,
        # CHECK-констрейнт допускает только 'purchase' | 'manual'.
        granted_by="manual",
        granted_by_user_id=user.id,
    )
    await state.clear()
    logger.info("admin {} granted premium to user {} until {}", user.id, target_user_id, until)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            PREMIUM_GRANTED.format(user_id=target_user_id, until=until.strftime("%Y-%m-%d")),
            reply_markup=admin_back_home_kb(),
        )


@router.callback_query(AdminPremiumCb.filter(F.action == "revoke"))
async def cb_premium_revoke(
    callback: CallbackQuery,
    callback_data: AdminPremiumCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    user_repo = UserRepository(db_session)
    await user_repo.clear_premium(callback_data.target_user_id)
    logger.info("admin {} revoked premium from user {}", user.id, callback_data.target_user_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            PREMIUM_REVOKED.format(user_id=callback_data.target_user_id),
            reply_markup=admin_back_home_kb(),
        )
