"""Раздел «Уведомления»: кулдауны пуш-уведомлений (лайки анкеты, комментарии).

Значения хранятся в app_settings и читаются сервисом уведомлений DB-direct,
поэтому правки применяются мгновенно. 0 = соответствующие пуши выключены.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import AdminMenuCb, AdminNotifCb, admin_back_home_kb
from app.bot.states.admin import AdminNotifStates
from app.db.models.user import User
from app.db.repositories.settings_repo import SettingsRepository
from app.services.notification_service import (
    DEFAULT_COMMENT_PAUSE_MIN,
    DEFAULT_LIKE_COOLDOWN_HOURS,
    SETTING_COMMENT_PAUSE_MIN,
    SETTING_LIKE_COOLDOWN_HOURS,
)
from app.texts import notifications as texts
from app.texts.admin import ADMIN_MENU_BTN_BACK

router = Router(name="admin.notifications")


async def _current_value(db_session: AsyncSession, key: str, default: int) -> int:
    """Текущее значение кулдауна; 0 валиден (= выключено), отрицательные → 0."""
    val = await SettingsRepository(db_session).get_int(key)
    if val is None:
        return default
    return max(val, 0)


def _menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_LIKE_FREQ, callback_data=AdminNotifCb(action="like_freq"))
    b.button(text=texts.BTN_COMMENT_FREQ, callback_data=AdminNotifCb(action="comment_freq"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(1)
    return b.as_markup()


def _back_to_notif_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_BACK_TO_NOTIF, callback_data=AdminMenuCb(action="notifications"))
    return b.as_markup()


async def _render_menu(message: Message, db_session: AsyncSession) -> None:
    like_hours = await _current_value(
        db_session, SETTING_LIKE_COOLDOWN_HOURS, DEFAULT_LIKE_COOLDOWN_HOURS
    )
    comment_minutes = await _current_value(
        db_session, SETTING_COMMENT_PAUSE_MIN, DEFAULT_COMMENT_PAUSE_MIN
    )
    await show_screen(
        message,
        text=texts.MENU.format(like_hours=like_hours, comment_minutes=comment_minutes),
        reply_markup=_menu_kb(),
    )


@router.callback_query(AdminMenuCb.filter(F.action == "notifications"))
async def cb_notif_menu(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_menu(callback.message, db_session)


@router.callback_query(AdminNotifCb.filter(F.action == "like_freq"))
async def cb_notif_like_freq(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await _current_value(
        db_session, SETTING_LIKE_COOLDOWN_HOURS, DEFAULT_LIKE_COOLDOWN_HOURS
    )
    await state.set_state(AdminNotifStates.ask_like_hours)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            texts.LIKE_FREQ_SCREEN.format(n=current), reply_markup=admin_back_home_kb()
        )


@router.callback_query(AdminNotifCb.filter(F.action == "comment_freq"))
async def cb_notif_comment_freq(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await _current_value(db_session, SETTING_COMMENT_PAUSE_MIN, DEFAULT_COMMENT_PAUSE_MIN)
    await state.set_state(AdminNotifStates.ask_comment_minutes)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            texts.COMMENT_FREQ_SCREEN.format(n=current), reply_markup=admin_back_home_kb()
        )


def _parse_non_negative_int(raw: str) -> int | None:
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


@router.message(StateFilter(AdminNotifStates.ask_like_hours), F.text)
async def on_notif_like_hours(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    value = _parse_non_negative_int(message.text or "")
    if value is None:
        await message.answer(texts.FREQ_INVALID, reply_markup=admin_back_home_kb())
        return
    await SettingsRepository(db_session).set(
        SETTING_LIKE_COOLDOWN_HOURS, str(value), by_user_id=user.id
    )
    await state.clear()
    logger.info("admin {} set {}={}", user.id, SETTING_LIKE_COOLDOWN_HOURS, value)
    confirmation = (
        texts.LIKE_FREQ_DISABLED if value == 0 else texts.LIKE_FREQ_UPDATED.format(n=value)
    )
    await message.answer(confirmation, reply_markup=_back_to_notif_kb())


@router.message(StateFilter(AdminNotifStates.ask_comment_minutes), F.text)
async def on_notif_comment_minutes(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    value = _parse_non_negative_int(message.text or "")
    if value is None:
        await message.answer(texts.FREQ_INVALID, reply_markup=admin_back_home_kb())
        return
    await SettingsRepository(db_session).set(
        SETTING_COMMENT_PAUSE_MIN, str(value), by_user_id=user.id
    )
    await state.clear()
    logger.info("admin {} set {}={}", user.id, SETTING_COMMENT_PAUSE_MIN, value)
    confirmation = (
        texts.COMMENT_FREQ_DISABLED if value == 0 else texts.COMMENT_FREQ_UPDATED.format(n=value)
    )
    await message.answer(confirmation, reply_markup=_back_to_notif_kb())
