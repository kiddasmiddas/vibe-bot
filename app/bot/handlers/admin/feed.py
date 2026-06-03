"""Раздел «Лента» (Feed) в админке (Волна 2B)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape as _html_escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminFeedCb,
    AdminFeedReviewCb,
    AdminMenuCb,
    admin_back_home_kb,
    feed_admin_menu_kb,
    feed_review_card_kb,
)
from app.bot.states.admin import AdminFeedStates
from app.bot.utils.render_profile import truncate_caption
from app.db.models.user import User
from app.db.repositories.feed_repo import FeedRepository
from app.texts.admin import (
    FEED_ADMIN_ASK_COMMENT_ID,
    FEED_ADMIN_COMMENT_DELETED,
    FEED_ADMIN_COMMENT_NOT_FOUND,
    FEED_ADMIN_INVALID_ID,
    FEED_ADMIN_MENU,
    FEED_ADMIN_POST_APPROVED,
    FEED_ADMIN_POST_DELETED,
    FEED_ADMIN_POST_HIDDEN,
    FEED_ADMIN_POST_NOT_FOUND,
    FEED_ADMIN_RESTRICT_ASK_HOURS,
    FEED_ADMIN_RESTRICT_INVALID_HOURS,
    FEED_ADMIN_RESTRICTED,
    FEED_ADMIN_UNRESTRICTED,
    FEED_REVIEW_POST_CARD_CAPTION,
    REVIEW_EMPTY,
)

router = Router(name="admin.feed")

_LIST_LIMIT = 20
_PAGE_SIZE = 1

# Локализованные метки статусов для карточки поста.
_STATUS_LABELS: dict[str, str] = {
    "pending": "⏳ На проверке",
    "active": "✅ Активный",
    "hidden": "🙈 Скрытый",
    "hidden_by_moderator": "🙈 Скрытый",
    "blocked": "🚫 Заблокированный",
    "expired": "⌛ Истёкший",
    "deleted_by_user": "🗑 Удалён пользователем",
}


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
# Single-card feed review (edit-based, paginated)
# ------------------------------------------------------------------ #


async def _show_pending_feed_card(
    callback: CallbackQuery,
    db_session: AsyncSession,
    *,
    offset: int,
    status: str,
) -> None:
    """Подгружает один пост по offset и рендерит его карточкой (edit-based).

    status: "pending" | "active" | "hidden"
    """
    if not callback.message:
        return

    repo = FeedRepository(db_session)

    # Определяем источник выборки и считаем total.
    if status == "pending":
        total = await repo.count_pending_review_posts()
    elif status == "active":
        total = await repo.count_posts_by_status("active")
    else:
        total = await repo.count_posts_by_status("hidden_by_moderator")

    if total == 0:
        await show_screen(
            callback.message,
            text=REVIEW_EMPTY,
            reply_markup=admin_back_home_kb(),
        )
        return

    # Если offset вышел за пределы — показываем первую позицию.
    offset = min(offset, total - 1)

    if status == "pending":
        posts = await repo.list_pending_review_posts(limit=_PAGE_SIZE, offset=offset)
    elif status == "active":
        posts = await repo.list_posts_by_status("active", limit=_PAGE_SIZE, offset=offset)
    else:
        posts = await repo.list_posts_by_status(
            "hidden_by_moderator", limit=_PAGE_SIZE, offset=offset
        )

    if not posts:
        await show_screen(
            callback.message,
            text=REVIEW_EMPTY,
            reply_markup=admin_back_home_kb(),
        )
        return

    post = posts[0]
    page = offset + 1

    # Медиа поста.
    media_list = await repo.get_photos_for_post(post.id)

    kb = feed_review_card_kb(post_id=post.id, offset=offset, status=status)

    # Счётчик медиа — если несколько, указываем "📸 фото 1 из N".
    if len(media_list) > 1:
        photo_counter = f"📸 фото 1 из {len(media_list)}\n"
    else:
        photo_counter = ""

    status_label = _STATUS_LABELS.get(
        "pending" if post.is_pending_review else post.status, post.status
    )

    # HTML-escape user-supplied поля (author_name — денормализованный ник из профиля).
    safe_author_name = _html_escape(post.author_name)
    username_part = f" | {safe_author_name}" if safe_author_name else ""

    # Тело поста: для caption медиа ограничение 1024; truncate_caption применяем к финальной строке.
    body = _html_escape(post.text)

    caption_raw = FEED_REVIEW_POST_CARD_CAPTION.format(
        page=page,
        total=total,
        user_id=post.author_user_id or "—",
        username_part=username_part,
        status_label=status_label,
        photo_counter=photo_counter,
        body=body,
    )

    if media_list:
        first_media = media_list[0]
        await show_screen(
            callback.message,
            text=truncate_caption(caption_raw),
            reply_markup=kb,
            media_file_id=first_media.file_id,
            media_type=first_media.media_type,
            parse_mode="HTML",
        )
    else:
        # Текстовый пост без медиа — truncate до 4096 (лимит обычного сообщения).
        await show_screen(
            callback.message,
            text=truncate_caption(caption_raw, limit=4096),
            reply_markup=kb,
            parse_mode="HTML",
        )


# ------------------------------------------------------------------ #
# Post lists → теперь открывают одиночную карточку с offset=0
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
    await callback.answer()
    await _show_pending_feed_card(callback, db_session, offset=0, status="active")


@router.callback_query(AdminFeedCb.filter(F.action == "list_hidden"))
async def cb_feed_list_hidden(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_pending_feed_card(callback, db_session, offset=0, status="hidden")


@router.callback_query(AdminFeedCb.filter(F.action == "list_pending"))
async def cb_feed_list_pending(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_pending_feed_card(callback, db_session, offset=0, status="pending")


# ------------------------------------------------------------------ #
# AdminFeedReviewCb action handlers
# ------------------------------------------------------------------ #


@router.callback_query(AdminFeedReviewCb.filter(F.action == "approve"))
async def cb_frv_approve(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Одобрить pending-пост: снимает is_pending_review, пост сразу публикуется."""
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.post_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    await repo.approve_post(post_id)
    logger.info("admin {} approved feed post {} via review card", user.id, post_id)
    await callback.answer(FEED_ADMIN_POST_APPROVED.format(id=post_id))
    # Одобренный пост выбыл из pending-очереди — тот же offset покажет следующий.
    await _show_pending_feed_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminFeedReviewCb.filter(F.action == "hide"))
async def cb_frv_hide(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.post_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    await repo.set_post_status(post_id, "hidden_by_moderator")
    logger.info("admin {} hid feed post {}", user.id, post_id)
    await callback.answer(FEED_ADMIN_POST_HIDDEN.format(id=post_id))
    # Текущий пост выбыл из выборки — тот же offset показывает следующий.
    await _show_pending_feed_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminFeedReviewCb.filter(F.action == "delete"))
async def cb_frv_delete(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.post_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    await repo.set_post_status(post_id, "blocked")
    logger.info("admin {} blocked feed post {}", user.id, post_id)
    await callback.answer(FEED_ADMIN_POST_DELETED.format(id=post_id))
    await _show_pending_feed_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminFeedReviewCb.filter(F.action == "del_comments"))
async def cb_frv_del_comments(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    state: FSMContext,
) -> None:
    """Удалить комментарий: запускаем FSM для ввода comment_id."""
    if not is_admin(user):
        await callback.answer()
        return
    await state.set_state(AdminFeedStates.ask_comment_id)
    await state.update_data(feed_post_id=callback_data.post_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(FEED_ADMIN_ASK_COMMENT_ID, reply_markup=admin_back_home_kb())


@router.callback_query(AdminFeedReviewCb.filter(F.action == "restrict"))
async def cb_frv_restrict(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.post_id
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


@router.callback_query(AdminFeedReviewCb.filter(F.action == "unrestrict"))
async def cb_frv_unrestrict(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    post_id = callback_data.post_id
    repo = FeedRepository(db_session)
    post = await repo.get_by_id(post_id)
    if not post or not post.author_user_id:
        await callback.answer(FEED_ADMIN_POST_NOT_FOUND, show_alert=True)
        return
    target_user_id = post.author_user_id
    await repo.remove_restriction(target_user_id)
    logger.info("admin {} removed restriction for user {}", user.id, target_user_id)
    await callback.answer(FEED_ADMIN_UNRESTRICTED.format(user_id=target_user_id))
    # unrestrict не меняет очерёдность поста — показываем ту же карточку.
    await _show_pending_feed_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminFeedReviewCb.filter(F.action == "skip"))
async def cb_frv_skip(
    callback: CallbackQuery,
    callback_data: AdminFeedReviewCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Пропустить: offset уже кодирован в callback_data как offset+1."""
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_pending_feed_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminFeedReviewCb.filter(F.action == "menu"))
async def cb_frv_menu(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Возврат в меню Feed-админки."""
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(callback.message, text=FEED_ADMIN_MENU, reply_markup=feed_admin_menu_kb())


# ------------------------------------------------------------------ #
# Legacy post actions (AdminFeedCb — оставлены для совместимости со
# старыми inline-кнопками в истории чата)
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
# Remove restriction (legacy AdminFeedCb)
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
