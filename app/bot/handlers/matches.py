"""Раздел «Мои лайки / мэтчи» (этап 4.3).

Меню с двумя вкладками: входящие лайки (без матча) и список мэтчей. Внутри
каждой вкладки — постраничный просмотр карточки + действия.

 (тонкие хэндлеры), §11 (паттерны aiogram).
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.blocks import start_block_flow
from app.bot.handlers.complaints import start_complaint_flow
from app.bot.handlers.matching import (
    _build_candidate_input_media,
    _build_matching_service,
    _render_candidate,
    _send_candidate_media,
    _send_match_notifications,
    _try_add_dislike,
)
from app.bot.keyboards.main_menu import main_menu_kb
from app.bot.utils.render_profile import RenderedProfile, truncate_caption
from app.db.models.matching import Like, Match
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from app.texts import common as common_texts
from app.texts import matching as texts

router = Router(name="matches")


# --------------------------- CallbackData ---------------------------


class MatchesMenuCb(CallbackData, prefix="mts"):
    """Переход в одну из вкладок раздела."""

    section: str  # 'incoming' | 'matches'
    index: int = 0


class IncomingLikeActionCb(CallbackData, prefix="ilike"):
    """Действия на карточке входящего лайка."""

    action: str  # 'like_back' | 'dislike' | 'complain' | 'block' | 'next'
    liker_user_id: int
    index: int


class MatchPageCb(CallbackData, prefix="mtch"):
    """Пагинация по списку мэтчей."""

    action: str  # 'next'  (back-кнопку добавим позже при необходимости)
    index: int


# --------------------------- keyboards ---------------------------


def _matches_menu_kb(incoming_count: int, matches_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.MATCHES_BTN_INCOMING.format(n=incoming_count),
        callback_data=MatchesMenuCb(section="incoming", index=0),
    )
    builder.button(
        text=texts.MATCHES_BTN_MATCHES.format(n=matches_count),
        callback_data=MatchesMenuCb(section="matches", index=0),
    )
    builder.adjust(1)
    return builder.as_markup()


def _incoming_like_kb(liker_user_id: int, index: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.LIKE_BACK_BTN,
        callback_data=IncomingLikeActionCb(
            action="like_back", liker_user_id=liker_user_id, index=index
        ),
    )
    builder.button(
        text=texts.DISLIKE_INCOMING_BTN,
        callback_data=IncomingLikeActionCb(
            action="dislike", liker_user_id=liker_user_id, index=index
        ),
    )
    builder.button(
        text=texts.BTN_COMPLAIN,
        callback_data=IncomingLikeActionCb(
            action="complain", liker_user_id=liker_user_id, index=index
        ),
    )
    builder.button(
        text=texts.BTN_BLOCK,
        callback_data=IncomingLikeActionCb(
            action="block", liker_user_id=liker_user_id, index=index
        ),
    )
    builder.button(
        text=texts.NEXT_BTN,
        callback_data=IncomingLikeActionCb(action="next", liker_user_id=liker_user_id, index=index),
    )
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def _match_page_kb(other_user: User, index: int) -> InlineKeyboardMarkup:
    """Карточка мэтча: кнопка «Открыть профиль» + «Дальше» (если есть)."""
    builder = InlineKeyboardBuilder()
    if other_user.username:
        url = f"https://t.me/{other_user.username}"
    else:
        url = f"tg://user?id={other_user.telegram_id}"
    builder.button(text=texts.BTN_OPEN_PROFILE, url=url)
    builder.button(
        text=texts.NEXT_BTN,
        callback_data=MatchPageCb(action="next", index=index),
    )
    builder.adjust(1, 1)
    return builder.as_markup()


# --------------------------- helpers ---------------------------


async def _show_card(
    message: Message,
    bot: Bot,
    rendered: RenderedProfile,
    caption: str,
    kb: InlineKeyboardMarkup,
    *,
    edit: bool,
) -> None:
    """Показывает медиа-карточку.

    `edit=True` — карточка редактируется на месте через `edit_media`, чат не
    засоряется новыми сообщениями (используется при навигации кнопками).
    `edit=False` — карточка отправляется новым сообщением (вход из меню).

    Если `edit_media` упал или карточка text-only — мягко деградируем к новому
    сообщению.
    """
    if not edit:
        await _send_candidate_media(
            bot, message.chat.id, rendered, caption, kb, fallback_message=message
        )
        return

    media = _build_candidate_input_media(rendered, caption)
    if media is not None:
        try:
            await message.edit_media(media=media, reply_markup=kb)
            return
        except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
            logger.warning("Failed to edit matches card: {}", exc)
    await message.answer(caption, reply_markup=kb)


async def _end_section(message: Message, text: str, *, edit: bool) -> None:
    """Список пуст или закончился при навигации.

    При `edit=True` удаляем карточку (иначе осталось бы фото последнего
    профиля с текстом «больше нет») и шлём текстовое уведомление. При входе
    из меню (`edit=False`) — просто текст.
    """
    if not edit:
        await message.answer(text)
        return
    try:
        await message.delete()
    except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
        logger.warning("Failed to delete last matches card: {}", exc)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    await message.answer(text)


async def _show_incoming_like(
    message: Message,
    bot: Bot,
    db_session: AsyncSession,
    likes: list[Like],
    index: int,
    *,
    edit: bool = False,
) -> None:
    """Показывает входящий лайк по индексу.

    `edit=True` — карточка редактируется на месте (навигация кнопками),
    `edit=False` — шлётся новым сообщением (вход из меню). Если лайков нет
    или список закончился — сообщает об окончании.
    """
    if not likes or index >= len(likes):
        await _end_section(message, texts.NO_INCOMING_LIKES, edit=edit)
        return

    like = likes[index]
    profile = await ProfileRepository(db_session).get_by_user_id(like.from_user_id)
    if profile is None:
        logger.warning("incoming like from_user_id={} has no profile, skipping", like.from_user_id)
        await _end_section(message, texts.NO_INCOMING_LIKES, edit=edit)
        return

    rendered = await _render_candidate(db_session, profile)
    if rendered is None:
        await _end_section(message, texts.NO_INCOMING_LIKES, edit=edit)
        return

    if like.kind == "superlike" and like.message:
        header = texts.INCOMING_LIKE_WITH_MESSAGE.format(message=like.message)
    else:
        header = texts.INCOMING_LIKE_HEADER
    caption = truncate_caption(f"{header}\n{rendered.text}")
    kb = _incoming_like_kb(liker_user_id=like.from_user_id, index=index)
    await _show_card(message, bot, rendered, caption, kb, edit=edit)


async def _show_match_page(
    message: Message,
    bot: Bot,
    db_session: AsyncSession,
    matches: list[Match],
    viewer_user_id: int,
    index: int,
    *,
    edit: bool = False,
) -> None:
    if not matches or index >= len(matches):
        await _end_section(message, texts.NO_MATCHES_YET, edit=edit)
        return

    match = matches[index]
    other_user_id = match.user_b_id if match.user_a_id == viewer_user_id else match.user_a_id

    user_repo = UserRepository(db_session)
    other_user = await user_repo.get_by_id(other_user_id)
    profile = await ProfileRepository(db_session).get_by_user_id(other_user_id)
    if other_user is None or profile is None:
        logger.warning("match other_user_id={} missing user/profile", other_user_id)
        await _end_section(message, texts.NO_MATCHES_YET, edit=edit)
        return

    rendered = await _render_candidate(db_session, profile)
    if rendered is None:
        await _end_section(message, texts.NO_MATCHES_YET, edit=edit)
        return

    if match.initial_message:
        header = texts.MATCH_WITH_MESSAGE.format(
            nickname=profile.nickname, message=match.initial_message
        )
    else:
        header = texts.MATCH_HEADER.format(nickname=profile.nickname)
    caption = truncate_caption(f"{header}\n\n{rendered.text}")
    kb = _match_page_kb(other_user, index=index)
    await _show_card(message, bot, rendered, caption, kb, edit=edit)


# --------------------------- entry: меню ---------------------------


@router.message(F.text == common_texts.BTN_LIKES_MATCHES)
async def on_my_likes_matches(
    message: Message,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Точка входа: пользователь выбрал «Мои лайки / мэтчи» в главном меню."""
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None or not profile.is_completed:
        await message.answer(
            texts.NO_PROFILE_YET,
            reply_markup=main_menu_kb(is_registered=False),
        )
        return
    if profile.is_pending_review:
        await message.answer(texts.PROFILE_PENDING_REVIEW_BLOCKED)
        return

    service = _build_matching_service(db_session)
    incoming = await service.list_incoming_likes_for_user(user.id)
    matches = await service.list_matches_for_user(user.id)
    await message.answer(
        texts.MATCHES_MENU_HEADER,
        reply_markup=_matches_menu_kb(incoming_count=len(incoming), matches_count=len(matches)),
    )


# --------------------------- меню → вкладка ---------------------------


@router.callback_query(MatchesMenuCb.filter())
async def cb_matches_menu(
    callback: CallbackQuery,
    callback_data: MatchesMenuCb,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.answer()
    service = _build_matching_service(db_session)
    if callback_data.section == "incoming":
        likes = await service.list_incoming_likes_for_user(user.id)
        await _show_incoming_like(callback.message, bot, db_session, likes, 0)
    elif callback_data.section == "matches":
        matches = await service.list_matches_for_user(user.id)
        await _show_match_page(callback.message, bot, db_session, matches, user.id, 0)


# --------------------------- incoming likes: действия ---------------------------


@router.callback_query(IncomingLikeActionCb.filter())
async def cb_incoming_like_action(
    callback: CallbackQuery,
    callback_data: IncomingLikeActionCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    action = callback_data.action
    liker_user_id = callback_data.liker_user_id

    if action == "complain":
        await start_complaint_flow(
            callback,
            state,
            target_user_id=liker_user_id,
            db_session=db_session,
        )
        return

    if action == "block":
        await start_block_flow(callback, target_user_id=liker_user_id)
        return

    await callback.answer()

    service = _build_matching_service(db_session)
    analytics_repo = AnalyticsRepository(db_session)

    if action == "like_back":
        outcome = await service.process_like(
            from_user_id=user.id,
            to_user_id=liker_user_id,
            kind="like",
        )
        if outcome.like_recorded:
            await analytics_repo.log_event(
                user.id,
                event_type=EventType.LIKE,
                payload={"target_user_id": liker_user_id},
            )
        if outcome.match_created:
            await analytics_repo.log_event(
                user.id,
                event_type=EventType.MATCH,
                payload={"match_id": outcome.match_id, "other_user_id": liker_user_id},
            )
            await _send_match_notifications(
                bot,
                db_session,
                initiator_user=user,
                other_user_id=liker_user_id,
                initial_message=outcome.initial_message,
            )
    elif action == "dislike":
        wrote = await _try_add_dislike(db_session, from_user_id=user.id, to_user_id=liker_user_id)
        if wrote:
            await analytics_repo.log_event(
                user.id,
                event_type=EventType.DISLIKE,
                payload={"target_user_id": liker_user_id},
            )

    # Переход к следующему. После like_back/dislike лайк уйдёт из списка
    # (см. matching_repo.list_incoming_likes), поэтому индекс не сдвигаем.
    likes = await service.list_incoming_likes_for_user(user.id)
    if action == "next":
        next_index = callback_data.index + 1
    else:
        next_index = callback_data.index
    await _show_incoming_like(callback.message, bot, db_session, likes, next_index, edit=True)


# --------------------------- матчи: пагинация ---------------------------


@router.callback_query(MatchPageCb.filter())
async def cb_match_page(
    callback: CallbackQuery,
    callback_data: MatchPageCb,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.answer()
    service = _build_matching_service(db_session)
    matches = await service.list_matches_for_user(user.id)
    next_index = callback_data.index + 1
    await _show_match_page(
        callback.message, bot, db_session, matches, user.id, next_index, edit=True
    )
