"""Раздел «⚙️ Настройки»: кураторские настройки кнопками (без сырых ключей).

Не путать с общей панелью ключ-значение (handlers/admin/settings.py) — она
скрыта флагом. Здесь только то, что клиент попросил менять руками:
приветственные тексты (делегируется редактору bot_texts) и лимиты анкеты.
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
from app.bot.keyboards.admin import (
    AdminAppCfgCb,
    AdminMenuCb,
    AdminTextsCb,
    admin_back_home_kb,
)
from app.bot.states.admin import AdminAppCfgStates
from app.db.models.user import User
from app.db.repositories.settings_repo import (
    SETTING_BIO_MAX_LENGTH,
    SETTING_FANDOMS_MAX_SELECTED,
    SettingsRepository,
)
from app.services.profile_limits import bio_max_length, fandoms_max_selected
from app.texts import bot_texts_admin as texts
from app.texts.admin import ADMIN_MENU_BTN_BACK

router = Router(name="admin.app_config")

# Диапазоны ввода: нижние границы отсекают ломающие значения (0 фандомов не
# даст пройти регистрацию; bio > 1024 гарантированно не влезет в caption).
FANDOMS_RANGE = (1, 50)
BIO_RANGE = (20, 1024)


def _menu_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import ADMIN_MENU_BTN_DICTS, ADMIN_MENU_BTN_NOTIF

    b = InlineKeyboardBuilder()
    # ⚙️ Настройки — хаб всей конфигурации: пуши, справочники, лимиты, тексты.
    b.button(text=ADMIN_MENU_BTN_NOTIF, callback_data=AdminMenuCb(action="notifications"))
    b.button(text=ADMIN_MENU_BTN_DICTS, callback_data=AdminMenuCb(action="dicts"))
    b.button(text=texts.BTN_PROFILE_LIMITS, callback_data=AdminAppCfgCb(action="limits"))
    b.button(
        text=texts.BTN_GENERAL_TEXTS,
        callback_data=AdminTextsCb(action="open", group="general", idx=0),
    )
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(1)
    return b.as_markup()


def _limits_kb(*, fandoms_max: int, bio_max: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=texts.BTN_LIMIT_FANDOMS.format(n=fandoms_max),
        callback_data=AdminAppCfgCb(action="limit_fandoms"),
    )
    b.button(
        text=texts.BTN_LIMIT_BIO.format(n=bio_max),
        callback_data=AdminAppCfgCb(action="limit_bio"),
    )
    b.button(text=texts.BTN_BACK_TO_APP_CFG, callback_data=AdminAppCfgCb(action="menu"))
    b.adjust(1)
    return b.as_markup()


def _back_to_limits_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_PROFILE_LIMITS, callback_data=AdminAppCfgCb(action="limits"))
    return b.as_markup()


async def _render_limits(message: Message, db_session: AsyncSession) -> None:
    fandoms_max = await fandoms_max_selected(db_session)
    bio_max = await bio_max_length(db_session)
    await show_screen(
        message,
        text=texts.LIMITS_MENU.format(fandoms_max=fandoms_max, bio_max=bio_max),
        reply_markup=_limits_kb(fandoms_max=fandoms_max, bio_max=bio_max),
    )


@router.callback_query(AdminMenuCb.filter(F.action == "app_cfg"))
@router.callback_query(AdminAppCfgCb.filter(F.action == "menu"))
async def cb_app_cfg_menu(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=texts.APP_CFG_MENU, reply_markup=_menu_kb())


@router.callback_query(AdminAppCfgCb.filter(F.action == "limits"))
async def cb_app_cfg_limits(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_limits(callback.message, db_session)


@router.callback_query(AdminAppCfgCb.filter(F.action == "limit_fandoms"))
async def cb_ask_fandoms_max(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await fandoms_max_selected(db_session)
    await state.set_state(AdminAppCfgStates.ask_fandoms_max)
    await callback.answer()
    if callback.message:
        lo, hi = FANDOMS_RANGE
        await callback.message.answer(
            texts.ASK_FANDOMS_MAX.format(n=current, lo=lo, hi=hi),
            reply_markup=admin_back_home_kb(),
        )


@router.callback_query(AdminAppCfgCb.filter(F.action == "limit_bio"))
async def cb_ask_bio_max(
    callback: CallbackQuery, user: User, db_session: AsyncSession, state: FSMContext
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    current = await bio_max_length(db_session)
    await state.set_state(AdminAppCfgStates.ask_bio_max)
    await callback.answer()
    if callback.message:
        lo, hi = BIO_RANGE
        await callback.message.answer(
            texts.ASK_BIO_MAX.format(n=current, lo=lo, hi=hi),
            reply_markup=admin_back_home_kb(),
        )


def _parse_in_range(raw: str, lo: int, hi: int) -> int | None:
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if lo <= value <= hi else None


async def _save_limit(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    *,
    key: str,
    label: str,
    lo: int,
    hi: int,
) -> None:
    value = _parse_in_range(message.text or "", lo, hi)
    if value is None:
        await message.answer(
            texts.ERR_INT_RANGE.format(lo=lo, hi=hi, example=(lo + hi) // 2),
            reply_markup=admin_back_home_kb(),
        )
        return
    await SettingsRepository(db_session).set(key, str(value), by_user_id=user.id)
    await state.clear()
    logger.info("admin {} set {}={}", user.id, key, value)
    await message.answer(
        texts.LIMIT_SAVED.format(label=label, n=value), reply_markup=_back_to_limits_kb()
    )


@router.message(StateFilter(AdminAppCfgStates.ask_fandoms_max), F.text)
async def on_fandoms_max(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    lo, hi = FANDOMS_RANGE
    await _save_limit(
        message,
        state,
        user,
        db_session,
        key=SETTING_FANDOMS_MAX_SELECTED,
        label=texts.LIMIT_LABEL_FANDOMS,
        lo=lo,
        hi=hi,
    )


@router.message(StateFilter(AdminAppCfgStates.ask_bio_max), F.text)
async def on_bio_max(
    message: Message, state: FSMContext, user: User, db_session: AsyncSession
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    lo, hi = BIO_RANGE
    await _save_limit(
        message,
        state,
        user,
        db_session,
        key=SETTING_BIO_MAX_LENGTH,
        label=texts.LIMIT_LABEL_BIO,
        lo=lo,
        hi=hi,
    )
