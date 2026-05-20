"""Раздел «На проверке» — ручная модерация анкет и постов Аллеи (10.8.1)."""

from __future__ import annotations

from html import escape as _html_escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminMenuCb,
    AdminReviewCb,
    AdminReviewProfileCb,
    admin_back_home_kb,
    review_menu_kb,
    review_post_kb,
    review_profile_card_kb,
)
from app.bot.states.admin import AdminReviewStates
from app.bot.utils.render_profile import build_rendered_profile, truncate_caption
from app.db.models.user import User
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.creator_repo import CreatorRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import (
    REVIEW_APPROVED,
    REVIEW_ASK_REASON,
    REVIEW_AUTHOR_BANNED_POST_DELETED,
    REVIEW_EMPTY,
    REVIEW_ERROR_NO_ITEM_ID,
    REVIEW_MENU,
    REVIEW_POST_CARD,
    REVIEW_PROFILE_CARD_CAPTION,
    REVIEW_PROFILE_CARD_NO_RENDER,
    REVIEW_REJECTED,
    USERS_BANNED,
)

router = Router(name="admin.review")

# Одна карточка за раз — экономичнее и нагляднее.
_PAGE_SIZE = 1


def _fmt_username_part(username: str | None) -> str:
    """Форматирует username как ' (@username)' или пустую строку."""
    if username:
        return f" (@{username})"
    return ""


async def _show_pending_profile_card(
    callback: CallbackQuery,
    db_session: AsyncSession,
    *,
    offset: int,
) -> None:
    """Подгружает одну анкету по offset и рендерит её карточкой (edit-based)."""
    if not callback.message:
        return

    admin_repo = AdminRepository(db_session)
    total = await admin_repo.count_pending_profiles()

    if total == 0:
        await show_screen(
            callback.message,
            text=REVIEW_EMPTY,
            reply_markup=admin_back_home_kb(),
        )
        return

    # Если offset вышел за пределы (e.g. одобрили последнюю) — показываем первую.
    offset = min(offset, total - 1)

    profiles = await admin_repo.list_pending_profiles(limit=_PAGE_SIZE, offset=offset)
    if not profiles:
        await show_screen(
            callback.message,
            text=REVIEW_EMPTY,
            reply_markup=admin_back_home_kb(),
        )
        return

    profile = profiles[0]
    page = offset + 1

    kb = review_profile_card_kb(profile_id=profile.id, offset=offset)

    # Подгружаем пользователя для username и telegram_id.
    user_repo = UserRepository(db_session)
    profile_user = await user_repo.get_by_id(profile.user_id)
    tg_id = profile_user.telegram_id if profile_user else 0
    username_part = _fmt_username_part(profile_user.username if profile_user else None)

    rendered = await build_rendered_profile(db_session, profile)

    # User-supplied поля (nickname/bio/city внутри rendered.text, username) идут в
    # сообщение с parse_mode="HTML" — экранируем, иначе модератор увидит чужую
    # разметку или активные ссылки tg://user?id=…
    safe_username_part = _html_escape(username_part)

    if rendered is not None:
        caption = REVIEW_PROFILE_CARD_CAPTION.format(
            page=page,
            total=total,
            user_id=profile.user_id,
            tg_id=tg_id,
            username_part=safe_username_part,
            profile_text=_html_escape(rendered.text),
        )
        await show_screen(
            callback.message,
            text=truncate_caption(caption),
            reply_markup=kb,
            media_file_id=rendered.media_file_id,
            media_type=rendered.media_type,
            parse_mode="HTML",
        )
    else:
        caption = REVIEW_PROFILE_CARD_NO_RENDER.format(
            page=page,
            total=total,
            user_id=profile.user_id,
            tg_id=tg_id,
            username_part=safe_username_part,
        )
        await show_screen(
            callback.message,
            text=caption,
            reply_markup=kb,
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.callback_query(AdminMenuCb.filter(F.action == "review"))
async def cb_review_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=REVIEW_MENU, reply_markup=review_menu_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "profiles"))
async def cb_review_profiles(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_pending_profile_card(callback, db_session, offset=0)


@router.callback_query(AdminReviewProfileCb.filter(F.action == "approve"))
async def cb_approve_profile_card(
    callback: CallbackQuery,
    callback_data: AdminReviewProfileCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    profile_repo = ProfileRepository(db_session)
    mod_repo = ModerationRepository(db_session)
    await profile_repo.update(callback_data.profile_id, is_pending_review=False)
    await mod_repo.log_moderation(
        user_id=user.id,
        target_kind="profile_media",
        target_id=callback_data.profile_id,
        check_type="nsfw_image",
        decision="approved",
        reason="admin_approved",
    )
    logger.info("admin {} approved profile {}", user.id, callback_data.profile_id)
    await callback.answer(REVIEW_APPROVED)
    # Тот же offset — текущая анкета выбыла из очереди, покажется следующая.
    await _show_pending_profile_card(callback, db_session, offset=callback_data.offset)


@router.callback_query(AdminReviewProfileCb.filter(F.action == "reject"))
async def cb_reject_profile_card_start(
    callback: CallbackQuery,
    callback_data: AdminReviewProfileCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminReviewStates.ask_reject_reason)
    await state.update_data(
        review_target_kind="profile",
        review_item_id=callback_data.profile_id,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(REVIEW_ASK_REASON, reply_markup=admin_back_home_kb())


@router.callback_query(AdminReviewProfileCb.filter(F.action == "skip"))
async def cb_review_profile_skip(
    callback: CallbackQuery,
    callback_data: AdminReviewProfileCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Пропустить: перейти к следующей анкете без изменения статуса текущей."""
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_pending_profile_card(callback, db_session, offset=callback_data.offset)


@router.callback_query(AdminReviewProfileCb.filter(F.action == "menu"))
async def cb_review_profile_menu(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Возврат в меню «На проверке»."""
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=REVIEW_MENU, reply_markup=review_menu_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "posts"))
async def cb_review_posts(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    creator_repo = CreatorRepository(db_session)
    posts = await creator_repo.list_pending_review_posts(limit=10)
    await callback.answer()
    if not callback.message:
        return
    if not posts:
        await callback.message.answer(REVIEW_EMPTY, reply_markup=admin_back_home_kb())
        return
    for post in posts:
        text = REVIEW_POST_CARD.format(
            post_id=post.id,
            author=post.author_display_name,
            description=post.description[:100],
        )
        await callback.message.answer(text, reply_markup=review_post_kb(post.id), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Legacy handlers: AdminReviewCb approve/reject/ban — оставлены для постов
# «Аллеи» и возможных старых inline-кнопок в истории чата.
# ---------------------------------------------------------------------------


@router.callback_query(AdminReviewCb.filter(F.action == "approve_profile"))
async def cb_approve_profile(
    callback: CallbackQuery,
    callback_data: AdminReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    profile_repo = ProfileRepository(db_session)
    mod_repo = ModerationRepository(db_session)
    await profile_repo.update(callback_data.item_id, is_pending_review=False)
    await mod_repo.log_moderation(
        user_id=user.id,
        target_kind="profile_media",
        target_id=callback_data.item_id,
        check_type="nsfw_image",
        decision="approved",
        reason="admin_approved",
    )
    logger.info("admin {} approved profile {}", user.id, callback_data.item_id)
    await callback.answer(REVIEW_APPROVED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "reject_profile"))
async def cb_reject_profile_start(
    callback: CallbackQuery,
    callback_data: AdminReviewCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminReviewStates.ask_reject_reason)
    await state.update_data(
        review_target_kind="profile",
        review_item_id=callback_data.item_id,
        review_offset=0,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(REVIEW_ASK_REASON, reply_markup=admin_back_home_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "ban_profile_user"))
async def cb_ban_profile_user(
    callback: CallbackQuery,
    callback_data: AdminReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    profile_repo = ProfileRepository(db_session)
    profile = await profile_repo.get_by_id(callback_data.item_id)
    if profile:
        user_repo = UserRepository(db_session)
        await user_repo.set_banned(profile.user_id, banned=True)
        await profile_repo.update(profile.id, is_pending_review=False, is_hidden=True)
        logger.info(
            "admin {} banned user {} via review of profile {}",
            user.id,
            profile.user_id,
            profile.id,
        )
    await callback.answer(USERS_BANNED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "approve_post"))
async def cb_approve_post(
    callback: CallbackQuery,
    callback_data: AdminReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    creator_repo = CreatorRepository(db_session)
    mod_repo = ModerationRepository(db_session)
    await creator_repo.approve_post(callback_data.item_id)
    await mod_repo.log_moderation(
        user_id=user.id,
        target_kind="creator_post_photo",
        target_id=callback_data.item_id,
        check_type="nsfw_image",
        decision="approved",
        reason="admin_approved",
    )
    logger.info("admin {} approved post {}", user.id, callback_data.item_id)
    await callback.answer(REVIEW_APPROVED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "delete_post"))
async def cb_delete_post_start(
    callback: CallbackQuery,
    callback_data: AdminReviewCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminReviewStates.ask_reject_reason)
    await state.update_data(
        review_target_kind="post",
        review_item_id=callback_data.item_id,
        review_offset=0,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(REVIEW_ASK_REASON, reply_markup=admin_back_home_kb())


@router.callback_query(AdminReviewCb.filter(F.action == "ban_post_author"))
async def cb_ban_post_author(
    callback: CallbackQuery,
    callback_data: AdminReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    creator_repo = CreatorRepository(db_session)
    post = await creator_repo.get_by_id(callback_data.item_id)
    if post and post.author_user_id:
        user_repo = UserRepository(db_session)
        await user_repo.set_banned(post.author_user_id, banned=True)
        await creator_repo.delete_post(post.id)
        logger.info(
            "admin {} banned user {} and deleted post {} via review",
            user.id,
            post.author_user_id,
            post.id,
        )
    await callback.answer(REVIEW_AUTHOR_BANNED_POST_DELETED, show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminReviewStates.ask_reject_reason), F.text)
async def on_review_reject_reason(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    reason = (message.text or "").strip()
    target_kind = data.get("review_target_kind")
    item_id = data.get("review_item_id")
    await state.clear()

    if item_id is None:
        await message.answer(REVIEW_ERROR_NO_ITEM_ID, reply_markup=admin_back_home_kb())
        return

    mod_repo = ModerationRepository(db_session)
    if target_kind == "profile":
        profile_repo = ProfileRepository(db_session)
        await profile_repo.update(int(item_id), is_pending_review=False, is_hidden=True)
        await mod_repo.log_moderation(
            user_id=user.id,
            target_kind="profile_media",
            target_id=int(item_id),
            check_type="nsfw_image",
            decision="rejected",
            reason=reason,
        )
    elif target_kind == "post":
        creator_repo = CreatorRepository(db_session)
        await mod_repo.log_moderation(
            user_id=user.id,
            target_kind="creator_post_photo",
            target_id=int(item_id),
            check_type="nsfw_image",
            decision="rejected",
            reason=reason,
        )
        await creator_repo.delete_post(int(item_id))

    logger.info(
        "admin {} rejected {} #{} reason={}",
        user.id,
        target_kind,
        item_id,
        reason,
    )
    await message.answer(REVIEW_REJECTED, reply_markup=admin_back_home_kb())
