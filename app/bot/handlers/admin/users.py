"""Раздел «Пользователи» админки (10.3)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, is_full_admin, show_screen
from app.bot.keyboards.admin import (
    AdminMenuCb,
    AdminUserActionCb,
    admin_back_home_kb,
    user_action_kb,
    users_menu_kb,
)
from app.bot.states.admin import AdminUserStates
from app.db.models.profile import Profile
from app.db.models.user import User
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import (
    USERS_BANNED,
    USERS_CARD,
    USERS_LIST_CAPTION,
    USERS_LIST_EMPTY,
    USERS_MENU,
    USERS_MOD_GRANTED,
    USERS_MOD_REVOKED,
    USERS_NOT_FOUND,
    USERS_PROFILE_HIDDEN,
    USERS_PROFILE_SHOWN,
    USERS_SEARCH_PROMPT,
    USERS_STATUS_ADMIN,
    USERS_STATUS_MODERATOR,
    USERS_STATUS_PREMIUM,
    USERS_STATUS_REGULAR,
    USERS_UNBANNED,
)

router = Router(name="admin.users")


def _build_users_csv(rows: list[tuple[User, str | None]]) -> bytes:
    """Формирует CSV-выгрузку пользователей. UTF-8 с BOM — для Excel."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["telegram_id", "username", "тариф", "имя в боте"])
    for u, nickname in rows:
        writer.writerow(
            [
                u.telegram_id,
                u.username or "",
                "Premium" if u.is_premium else "Free",
                nickname or "",
            ]
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


async def _send_user_card(
    message: Message,
    profile: Profile | None,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    """Шлёт карточку пользователя: с фото анкеты, если оно есть, иначе текстом.

    При ошибке Telegram (битый file_id, отклонённая клавиатура) — деградирует
    к тексту, чтобы результат поиска всегда был виден администратору.
    """
    media_type = profile.main_media_type if profile else None
    file_id = profile.main_media_file_id if profile else None

    if file_id and media_type in ("photo", "video", "gif"):
        try:
            if media_type == "photo":
                await message.answer_photo(
                    file_id, caption=text, reply_markup=kb, parse_mode="HTML"
                )
            elif media_type == "video":
                await message.answer_video(
                    file_id, caption=text, reply_markup=kb, parse_mode="HTML"
                )
            else:
                await message.answer_animation(
                    file_id, caption=text, reply_markup=kb, parse_mode="HTML"
                )
            return
        except TelegramBadRequest as exc:
            logger.warning("user card media send failed: {}", exc)

    try:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as exc:
        logger.warning("user card kb rejected: {}", exc)
        await message.answer(text, parse_mode="HTML")


@router.callback_query(AdminMenuCb.filter(F.action == "users"))
async def cb_users_menu(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    """Открывает раздел «Пользователи»: меню из двух кнопок (выгрузка + поиск).

    Файл больше НЕ выгружается автоматически при входе — только по кнопке
    «📤 Выгрузить всех», чтобы не спамить документом на каждом открытии.
    """
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=USERS_MENU, reply_markup=users_menu_kb())


@router.callback_query(AdminUserActionCb.filter(F.action == "export"))
async def cb_users_export(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    """Кнопка «Выгрузить всех» — отдаёт CSV-файл со всеми пользователями."""
    if not is_admin(user):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    if callback.message is None:
        return

    rows = await AdminRepository(db_session).list_all_users_for_export()
    if not rows:
        await callback.message.answer(USERS_LIST_EMPTY, reply_markup=users_menu_kb())
        return

    csv_bytes = _build_users_csv(rows)
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d_%H-%M")
    document = BufferedInputFile(csv_bytes, filename=f"users_{stamp}.csv")
    await callback.message.answer_document(
        document,
        caption=USERS_LIST_CAPTION.format(count=len(rows)),
        reply_markup=users_menu_kb(),
    )


@router.callback_query(AdminUserActionCb.filter(F.action == "search"))
async def cb_users_search(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """Кнопка «Поиск» — запрашивает Telegram ID и включает FSM поиска."""
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminUserStates.search_user_query)
    await callback.answer()
    if callback.message:
        await callback.message.answer(USERS_SEARCH_PROMPT, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminUserStates.search_user_query), F.text)
async def on_user_search_query(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Обрабатывает ввод поискового запроса."""
    if not is_admin(user):
        await state.clear()
        return

    query = (message.text or "").strip()
    user_repo = UserRepository(db_session)
    results = await user_repo.search(query)

    if not results:
        await message.answer(USERS_NOT_FOUND, reply_markup=admin_back_home_kb())
        return

    await state.clear()
    profile_repo = ProfileRepository(db_session)

    for found_user in results[:5]:  # показываем не больше 5
        profile = await profile_repo.get_by_user_id(found_user.id)
        nickname = profile.nickname if profile else "—"
        username = found_user.username or "—"

        target_is_admin = is_full_admin(found_user)
        if target_is_admin:
            status = USERS_STATUS_ADMIN
        elif found_user.is_moderator:
            status = USERS_STATUS_MODERATOR
        elif found_user.is_premium:
            status = USERS_STATUS_PREMIUM
        else:
            status = USERS_STATUS_REGULAR

        text = USERS_CARD.format(
            user_id=found_user.id,
            telegram_id=found_user.telegram_id,
            username=username,
            nickname=nickname,
            status=status,
            banned="✅" if found_user.is_banned else "❌",
        )
        kb = user_action_kb(
            found_user.id,
            telegram_id=found_user.telegram_id,
            username=found_user.username,
            is_banned=found_user.is_banned,
            is_hidden=profile.is_hidden if profile else False,
            is_moderator=found_user.is_moderator,
            # Назначать/снимать модераторов может только полный администратор.
            can_manage_moderators=is_full_admin(user),
            target_is_admin=target_is_admin,
        )
        await _send_user_card(message, profile, text, kb)


@router.callback_query(AdminUserActionCb.filter(F.action == "ban"))
async def cb_ban_user(
    callback: CallbackQuery,
    callback_data: AdminUserActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    user_repo = UserRepository(db_session)
    await user_repo.set_banned(callback_data.target_user_id, banned=True)
    logger.info("admin {} banned user {}", user.id, callback_data.target_user_id)
    await callback.answer(USERS_BANNED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminUserActionCb.filter(F.action == "unban"))
async def cb_unban_user(
    callback: CallbackQuery,
    callback_data: AdminUserActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    user_repo = UserRepository(db_session)
    await user_repo.set_banned(callback_data.target_user_id, banned=False)
    logger.info("admin {} unbanned user {}", user.id, callback_data.target_user_id)
    await callback.answer(USERS_UNBANNED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminUserActionCb.filter(F.action == "make_mod"))
async def cb_make_moderator(
    callback: CallbackQuery,
    callback_data: AdminUserActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Назначить пользователя модератором. Только полный администратор."""
    if not is_full_admin(user):
        await callback.answer()
        return
    await UserRepository(db_session).set_moderator(callback_data.target_user_id, moderator=True)
    logger.info("admin {} granted moderator to user {}", user.id, callback_data.target_user_id)
    await callback.answer(USERS_MOD_GRANTED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminUserActionCb.filter(F.action == "remove_mod"))
async def cb_remove_moderator(
    callback: CallbackQuery,
    callback_data: AdminUserActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Снять роль модератора. Только полный администратор."""
    if not is_full_admin(user):
        await callback.answer()
        return
    await UserRepository(db_session).set_moderator(callback_data.target_user_id, moderator=False)
    logger.info("admin {} revoked moderator from user {}", user.id, callback_data.target_user_id)
    await callback.answer(USERS_MOD_REVOKED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminUserActionCb.filter(F.action == "hide_profile"))
async def cb_hide_profile(
    callback: CallbackQuery,
    callback_data: AdminUserActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    profile_repo = ProfileRepository(db_session)
    profile = await profile_repo.get_by_user_id(callback_data.target_user_id)
    if profile:
        await profile_repo.set_hidden(profile.id, hidden=True)
    logger.info("admin {} hid profile of user {}", user.id, callback_data.target_user_id)
    await callback.answer(USERS_PROFILE_HIDDEN, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminUserActionCb.filter(F.action == "show_profile"))
async def cb_show_profile(
    callback: CallbackQuery,
    callback_data: AdminUserActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    profile_repo = ProfileRepository(db_session)
    profile = await profile_repo.get_by_user_id(callback_data.target_user_id)
    if profile:
        await profile_repo.set_hidden(profile.id, hidden=False)
    logger.info("admin {} showed profile of user {}", user.id, callback_data.target_user_id)
    await callback.answer(USERS_PROFILE_SHOWN, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())
