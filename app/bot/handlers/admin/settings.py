"""Раздел «Настройки» — редактирование app_settings (10.9)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import AdminMenuCb, AdminSettingsCb, admin_back_home_kb
from app.bot.states.admin import AdminSettingsStates
from app.db.models.user import User
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.texts.admin import (
    ADMIN_MENU_BTN_HOME,
    SETTINGS_BTN_EDIT,
    SETTINGS_EDIT_ASK_VALUE,
    SETTINGS_EMPTY,
    SETTINGS_ITEM,
    SETTINGS_KEY_NOT_FOUND,
    SETTINGS_MENU,
    SETTINGS_NOT_FOUND,
    SETTINGS_UPDATED,
)

router = Router(name="admin.settings")


@router.callback_query(AdminMenuCb.filter(F.action == "settings"))
async def cb_settings_menu(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    admin_repo = AdminRepository(db_session)
    settings_list = await admin_repo.list_all_settings()
    await callback.answer()
    if not callback.message:
        return

    if not settings_list:
        await show_screen(callback.message, text=SETTINGS_EMPTY, reply_markup=admin_back_home_kb())
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    await show_screen(callback.message, text=SETTINGS_MENU)
    for key, value in settings_list:
        text = SETTINGS_ITEM.format(key=key, value=value)
        b = InlineKeyboardBuilder()
        b.button(
            text=SETTINGS_BTN_EDIT,
            callback_data=AdminSettingsCb(action="edit", key=key),
        )
        b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
        await callback.message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(AdminSettingsCb.filter(F.action == "edit"))
async def cb_settings_edit_start(
    callback: CallbackQuery,
    callback_data: AdminSettingsCb,
    user: User,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    settings_repo = SettingsRepository(db_session)
    current = await settings_repo.get(callback_data.key)
    if current is None:
        await callback.answer(SETTINGS_NOT_FOUND, show_alert=True)
        return
    await state.set_state(AdminSettingsStates.edit_ask_value)
    await state.update_data(settings_key=callback_data.key)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            SETTINGS_EDIT_ASK_VALUE.format(key=callback_data.key, current=current),
            parse_mode="HTML",
            reply_markup=admin_back_home_kb(),
        )


@router.message(StateFilter(AdminSettingsStates.edit_ask_value), F.text)
async def on_settings_value(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    key = data.get("settings_key")
    await state.clear()
    if not key:
        await message.answer(SETTINGS_KEY_NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    value = (message.text or "").strip()
    settings_repo = SettingsRepository(db_session)
    await settings_repo.set(key, value, by_user_id=user.id)
    logger.info("admin {} updated setting {}={}", user.id, key, value)
    await message.answer(
        SETTINGS_UPDATED.format(key=key), parse_mode="HTML", reply_markup=admin_back_home_kb()
    )
