"""Раздел «Лента» (Feed) в админке (Волна 2B)."""

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
    AdminFeedCb,
    AdminMenuCb,
    admin_back_home_kb,
    feed_admin_menu_kb,
    feed_post_actions_kb,
)
from app.bot.states.admin import AdminFeedStates
from app.db.models.user import User
from app.db.repositories.feed_repo import FeedRepository
from app.texts.admin import (
    FEED_ADMIN_ASK_COMMENT_ID,
    FEED_ADMIN_COMMENT_DELETED,
    FEED_ADMIN_COMMENT_NOT_FOUND,
    FEED_ADMIN_INVALID_ID,
    FEED_ADMIN_LIST_EMPTY,
    FEED_ADMIN_MENU,
    FEED_ADMIN_POST_APPROVED,
    FEED_ADMIN_POST_CARD,
    FEED_ADMIN_POST_DELETED,
    FEED_ADMIN_POST_HIDDEN,
    FEED_ADMIN_POST_NOT_FOUND,
    FEED_ADMIN_RESTRICT_ASK_HOURS,
    FEED_ADMIN_RESTRICT_INVALID_HOURS,
    FEED_ADMIN_RESTRICTED,
    FEED_ADMIN_UNRESTRICTED,
)

router = Router(name="admin.feed")

_LIST_LIMIT = 20


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #


@router.callback_query(AdminMenuCb.filter(F.action == "feed"))
async def cb_feed_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=FEED_ADMIN_MENU, reply_markup=feed_admin_menu_kb())


# ------------------------------------------------------------------ #
# Post lists
# ------------------------------------------------------------------ #


@router.callback_query(AdminFeedCb.filter(F.action == "list_active"))
async def cb_feed_list_active(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = FeedRepository(db_session)
    posts = await repo.list_posts_by_status("active", limit=_LIST_LIMIT)
    await callback.answer()
    if not callback.message:
        return
    if not posts:
        await callback.message.answer(FEED_ADMIN_LIST_EMPTY, reply_markup=admin_back_home_kb())
        return
    for post in posts:
        text = FEED_ADMIN_POST_CARD.format(
            id=post.id,
            author_name=post.author_name,
            author_user_id=post.author_user_id,
            status=post.status,
            pending="Да" if post.is_pending_review else "Нет",
            text=post.text[:120],
            created_at=post.created_at.strftime("%Y-%m-%d %H:%M") if post.created_at else "—",
            expires_at=post.expires_at.strftime("%Y-%m-%d %H:%M") if post.expires_at else "—",
        )
        await callback.message.answer(
            text,
            reply_markup=feed_post_actions_kb(post.id, is_pending=post.is_pending_review),
            parse_mode="HTML",
        )


@router.callback_query(AdminFeedCb.filter(F.action == "list_hidden"))
async def cb_feed_list_hidden(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = FeedRepository(db_session)
    posts = await repo.list_posts_by_status("hidden_by_moderator", limit=_LIST_LIMIT)
    await callback.answer()
    if not callback.message:
        return
    if not posts:
        await callback.message.answer(FEED_ADMIN_LIST_EMPTY, reply_markup=admin_back_home_kb())
        return
    for post in posts:
        text = FEED_ADMIN_POST_CARD.format(
            id=post.id,
            author_name=post.author_name,
            author_user_id=post.author_user_id,
            status=post.status,
            pending="Да" if post.is_pending_review else "Нет",
            text=post.text[:120],
            created_at=post.created_at.strftime("%Y-%m-%d %H:%M") if post.created_at else "—",
            expires_at=post.expires_at.strftime("%Y-%m-%d %H:%M") if post.expires_at else "—",
        )
        await callback.message.answer(
            text,
            reply_markup=feed_post_actions_kb(post.id, is_pending=post.is_pending_review),
            parse_mode="HTML",
        )


@router.callback_query(AdminFeedCb.filter(F.action == "list_pending"))
async def cb_feed_list_pending(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = FeedRepository(db_session)
    posts = await repo.list_pending_review_posts(limit=_LIST_LIMIT)
    await callback.answer()
    if not callback.message:
        return
    if not posts:
        await callback.message.answer(FEED_ADMIN_LIST_EMPTY, reply_markup=admin_back_home_kb())
        return
    for post in posts:
        text = FEED_ADMIN_POST_CARD.format(
            id=post.id,
            author_name=post.author_name,
            author_user_id=post.author_user_id,
            status=post.status,
            pending="Да",
            text=post.text[:120],
            created_at=post.created_at.strftime("%Y-%m-%d %H:%M") if post.created_at else "—",
            expires_at=post.expires_at.strftime("%Y-%m-%d %H:%M") if post.expires_at else "—",
        )
        await callback.message.answer(
            text,
            reply_markup=feed_post_actions_kb(post.id, is_pending=True),
            parse_mode="HTML",
        )


# ------------------------------------------------------------------ #
# Post actions
# ------------------------------------------------------------------ #


@router.callback_query(AdminFeedCb.filter(F.action == "hide_post"))
async def cb_feed_hide_post(
    callback: CallbackQuery,
    callback_data: AdminFeedCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.item_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    await repo.set_post_status(post_id, "hidden_by_moderator")
    logger.info("admin {} hid feed post {}", user.id, post_id)
    await callback.answer(FEED_ADMIN_POST_HIDDEN.format(id=post_id), show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminFeedCb.filter(F.action == "delete_post"))
async def cb_feed_delete_post(
    callback: CallbackQuery,
    callback_data: AdminFeedCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.item_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    await repo.set_post_status(post_id, "blocked")
    logger.info("admin {} blocked feed post {}", user.id, post_id)
    await callback.answer(FEED_ADMIN_POST_DELETED.format(id=post_id), show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


@router.callback_query(AdminFeedCb.filter(F.action == "approve_post"))
async def cb_feed_approve_post(
    callback: CallbackQuery,
    callback_data: AdminFeedCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.item_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    await repo.approve_post(post_id)
    logger.info("admin {} approved feed post {} (cleared pending_review)", user.id, post_id)
    await callback.answer(FEED_ADMIN_POST_APPROVED.format(id=post_id), show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=admin_back_home_kb())


# ------------------------------------------------------------------ #
# Comment deletion (FSM — ask comment_id, then delete)
# ------------------------------------------------------------------ #


@router.callback_query(AdminFeedCb.filter(F.action == "ask_comment_id"))
async def cb_feed_ask_comment_id(
    callback: CallbackQuery,
    callback_data: AdminFeedCb,
    user: User,
    state: FSMContext,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminFeedStates.ask_comment_id)
    await state.update_data(feed_post_id=callback_data.item_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(FEED_ADMIN_ASK_COMMENT_ID, reply_markup=admin_back_home_kb())


@router.message(StateFilter(AdminFeedStates.ask_comment_id), F.text)
async def on_feed_comment_id_entered(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(FEED_ADMIN_INVALID_ID, reply_markup=admin_back_home_kb())
        return
    comment_id = int(raw)
    repo = FeedRepository(db_session)
    comment = await repo.get_comment(comment_id)
    if not comment:
        await state.clear()
        await message.answer(FEED_ADMIN_COMMENT_NOT_FOUND, reply_markup=admin_back_home_kb())
        return
    await repo.set_comment_status(comment_id, "deleted_by_moderator")
    await state.clear()
    logger.info("admin {} deleted feed comment {}", user.id, comment_id)
    await message.answer(
        FEED_ADMIN_COMMENT_DELETED.format(id=comment_id), reply_markup=admin_back_home_kb()
    )


# ------------------------------------------------------------------ #
# Comment restriction (FSM — ask hours, then set_restriction)
# ------------------------------------------------------------------ #


@router.callback_query(AdminFeedCb.filter(F.action == "restrict"))
async def cb_feed_restrict_start(
    callback: CallbackQuery,
    callback_data: AdminFeedCb,
    user: User,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.item_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post or not post.author_user_id:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    target_user_id = post.author_user_id
    await state.set_state(AdminFeedStates.restrict_ask_hours)
    await state.update_data(feed_restrict_user_id=target_user_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            FEED_ADMIN_RESTRICT_ASK_HOURS.format(user_id=target_user_id),
            reply_markup=admin_back_home_kb(),
        )


@router.message(StateFilter(AdminFeedStates.restrict_ask_hours), F.text)
async def on_feed_restrict_hours_entered(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(FEED_ADMIN_RESTRICT_INVALID_HOURS, reply_markup=admin_back_home_kb())
        return
    hours = int(raw)
    data = await state.get_data()
    target_user_id: int = data["feed_restrict_user_id"]
    until = datetime.now(tz=UTC) + timedelta(hours=hours)
    repo = FeedRepository(db_session)
    await repo.set_restriction(target_user_id, until, user.id)
    await state.clear()
    logger.info("admin {} restricted user {} comments until {}", user.id, target_user_id, until)
    await message.answer(
        FEED_ADMIN_RESTRICTED.format(
            user_id=target_user_id,
            until=until.strftime("%Y-%m-%d %H:%M UTC"),
        ),
        reply_markup=admin_back_home_kb(),
    )


# ------------------------------------------------------------------ #
# Remove restriction
# ------------------------------------------------------------------ #


@router.callback_query(AdminFeedCb.filter(F.action == "unrestrict"))
async def cb_feed_unrestrict(
    callback: CallbackQuery,
    callback_data: AdminFeedCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.item_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post or not post.author_user_id:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    target_user_id = post.author_user_id
    await repo.remove_restriction(target_user_id)
    logger.info("admin {} removed restriction for user {}", user.id, target_user_id)
    await callback.answer(FEED_ADMIN_UNRESTRICTED.format(user_id=target_user_id), show_alert=True)
