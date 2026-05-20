"""Раздел «Искать своих» (этап 4.2): просмотр анкет, лайки, дизлайки.

Хэндлер опирается на `MatchingService.get_next_candidates` — сервис чистый,
все побочные эффекты (запись `viewed_profiles`, аналитика, лайки/дизлайки)
делаются здесь, при фактическом показе или клике по кнопке.

 (тонкие хэндлеры), §11 (паттерны aiogram).
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.blocks import start_block_flow
from app.bot.handlers.complaints import start_complaint_flow
from app.bot.keyboards.main_menu import main_menu_kb
from app.bot.keyboards.matching import (
    MatchingActionCb,
    SuperlikeCancelCb,
    actions_kb,
    superlike_cancel_kb,
)
from app.bot.states.matching import MatchingStates
from app.bot.utils.render_profile import (
    RenderedProfile,
    build_rendered_profile,
    truncate_caption,
)
from app.db.models.profile import Profile
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from app.services.content_moderation_service import ContentModerationService
from app.services.matching_service import CandidateResult, MatchingService
from app.texts import common as common_texts
from app.texts import matching as texts

router = Router(name="matching")


# --------------------------- helpers ---------------------------


def _build_matching_service(db_session: AsyncSession) -> MatchingService:
    return MatchingService(
        profile_repo=ProfileRepository(db_session),
        matching_repo=MatchingRepository(db_session),
        settings_repo=SettingsRepository(db_session),
        dictionary_repo=DictionaryRepository(db_session),
        user_repo=UserRepository(db_session),
        session=db_session,
    )


def _open_profile_kb(target_user: User) -> InlineKeyboardMarkup:
    """Кнопка-ссылка «Открыть профиль». Если у пользователя есть username —
    используем `t.me/<username>`, иначе — `tg://user?id=<telegram_id>`.

    `tg://user?id=...` работает только если получатель сам существует в Telegram
    (нет публичного раскрытия) — это безопасно.
    """
    if target_user.username:
        url = f"https://t.me/{target_user.username}"
    else:
        url = f"tg://user?id={target_user.telegram_id}"
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_OPEN_PROFILE, url=url)
    return builder.as_markup()


def _format_match_notification(nickname: str, initial_message: str | None) -> str:
    if initial_message:
        return texts.MATCH_WITH_MESSAGE.format(nickname=nickname, message=initial_message)
    return texts.MATCH_HEADER.format(nickname=nickname)


async def _send_match_notifications(
    bot: Bot,
    db_session: AsyncSession,
    *,
    initiator_user: User,
    other_user_id: int,
    initial_message: str | None,
) -> None:
    """Шлёт уведомления обоим участникам мэтча.

    Карточки не отправляются медиа-сообщением — только текст + inline-кнопка
    «Открыть профиль». Это проще и не спамит.
    """
    user_repo = UserRepository(db_session)
    profile_repo = ProfileRepository(db_session)

    other_user = await user_repo.get_by_id(other_user_id)
    if other_user is None:
        logger.error("match notification: other_user_id={} not found", other_user_id)
        return

    initiator_profile = await profile_repo.get_by_user_id(initiator_user.id)
    other_profile = await profile_repo.get_by_user_id(other_user_id)
    if initiator_profile is None or other_profile is None:
        logger.error(
            "match notification: missing profile (initiator={} other={})",
            initiator_user.id,
            other_user_id,
        )
        return

    # Инициатору — карточка другого юзера.
    text_for_initiator = _format_match_notification(other_profile.nickname, initial_message)
    text_for_other = _format_match_notification(initiator_profile.nickname, initial_message)

    try:
        await bot.send_message(
            chat_id=initiator_user.telegram_id,
            text=text_for_initiator,
            reply_markup=_open_profile_kb(other_user),
        )
    except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
        logger.warning("Failed to send match notification to initiator: {}", exc)

    try:
        await bot.send_message(
            chat_id=other_user.telegram_id,
            text=text_for_other,
            reply_markup=_open_profile_kb(initiator_user),
        )
    except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
        logger.warning("Failed to send match notification to other: {}", exc)


async def _render_candidate(
    db_session: AsyncSession,
    candidate: Profile,
) -> RenderedProfile | None:
    """Делегирует рендеринг карточки кандидата в `build_rendered_profile`.

    `desired_vibe_id IS NULL` — валидное состояние («любой вайб»), не ошибка.
    `build_rendered_profile` обрабатывает этот случай корректно.
    """
    return await build_rendered_profile(db_session, candidate, viewer_is_self=False)


async def _send_candidate_media(
    bot: Bot,
    chat_id: int,
    rendered: RenderedProfile,
    caption: str,
    kb: InlineKeyboardMarkup,
    *,
    fallback_message: Message,
) -> None:
    """Отправляет медиа-карточку с клавиатурой. Падение на send_* → text-only."""
    try:
        if rendered.media_type == "photo":
            await bot.send_photo(chat_id, rendered.media_file_id, caption=caption, reply_markup=kb)
        elif rendered.media_type == "video":
            await bot.send_video(chat_id, rendered.media_file_id, caption=caption, reply_markup=kb)
        elif rendered.media_type == "gif":
            await bot.send_animation(
                chat_id, rendered.media_file_id, caption=caption, reply_markup=kb
            )
        else:
            await fallback_message.answer(caption, reply_markup=kb)
    except TelegramAPIError as exc:  # pragma: no cover — медиа не критично
        logger.warning("Failed to send candidate media: {}", exc)
        await fallback_message.answer(caption, reply_markup=kb)


def _badge_prefix(candidate_result: CandidateResult) -> str:
    """Возвращает текстовый префикс-бейдж по флагам близости города.

    Пустая строка для своего города (Stage 1) или когда city IS NULL.
    """
    if candidate_result.from_neighbor_city:
        return texts.CANDIDATE_BADGE_NEIGHBOR_CITY
    if candidate_result.from_other_region:
        return texts.CANDIDATE_BADGE_OTHER_REGION
    return ""


async def _show_candidate(
    message: Message,
    db_session: AsyncSession,
    bot: Bot,
    viewer_user_id: int,
    candidate_result: CandidateResult,
) -> None:
    """Шлёт карточку кандидата, отмечает просмотр и пишет аналитику.

    Запись `viewed_profiles` и аналитика делаются ПОСЛЕ успешной попытки
    отправить медиа — чтобы при ошибке отправки кандидат не «сгорел» из
    выдачи. Best-effort: ошибки записи viewed/аналитики не должны ломать UX.
    """
    candidate = candidate_result.profile
    rendered = await _render_candidate(db_session, candidate)
    if rendered is None:
        await message.answer(texts.NO_MORE_CANDIDATES)
        return

    badge = _badge_prefix(candidate_result)
    caption = truncate_caption(f"{badge}{texts.CANDIDATE_HEADER}\n{rendered.text}")
    kb = actions_kb(candidate.user_id)
    await _send_candidate_media(
        bot,
        message.chat.id,
        rendered,
        caption,
        kb,
        fallback_message=message,
    )

    # После показа — фиксируем просмотр и событие. add_viewed — upsert,
    # повторы безопасны.
    matching_repo = MatchingRepository(db_session)
    await matching_repo.add_viewed(viewer_id=viewer_user_id, target_id=candidate.user_id)
    await AnalyticsRepository(db_session).log_event(
        viewer_user_id,
        event_type=EventType.PROFILE_VIEWED,
        payload={"target_user_id": candidate.user_id},
    )


async def _show_next_candidate(
    message: Message,
    db_session: AsyncSession,
    bot: Bot,
    user: User,
) -> None:
    """Подгружает следующего кандидата (limit=1) и показывает или сообщает
    об отсутствии."""
    service = _build_matching_service(db_session)
    next_results = await service.get_next_candidates(user.id, limit=1)
    if not next_results:
        await message.answer(
            texts.NO_MORE_CANDIDATES,
            reply_markup=main_menu_kb(is_registered=True),
        )
        return
    await _show_candidate(message, db_session, bot, user.id, next_results[0])


def _build_candidate_input_media(
    rendered: RenderedProfile, caption: str
) -> InputMediaPhoto | InputMediaVideo | InputMediaAnimation | None:
    """Собирает InputMedia* для `edit_media` по типу медиа кандидата.

    `None` — если тип не медийный (карточка показывалась text-only).
    """
    if rendered.media_type == "photo":
        return InputMediaPhoto(media=rendered.media_file_id, caption=caption)
    if rendered.media_type == "video":
        return InputMediaVideo(media=rendered.media_file_id, caption=caption)
    if rendered.media_type == "gif":
        return InputMediaAnimation(media=rendered.media_file_id, caption=caption)
    return None


async def _no_more_candidates_inplace(message: Message) -> None:
    """Кандидаты кончились: удаляем карточку последней анкеты и шлём текст.

    `edit_caption` тут не годится — он оставил бы фото последней анкеты с
    подписью «анкеты закончились». Поэтому удаляем сообщение-карточку целиком
    и отправляем отдельное текстовое уведомление.
    """
    try:
        await message.delete()
    except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
        # Удалить не вышло (старое сообщение?) — хотя бы убираем кнопки.
        logger.warning("Failed to delete last candidate card: {}", exc)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    await message.answer(
        texts.NO_MORE_CANDIDATES,
        reply_markup=main_menu_kb(is_registered=True),
    )


async def _edit_to_next_candidate(
    message: Message,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Заменяет карточку текущего кандидата на следующего через `edit_media`.

    Используется для лайка/дизлайка/скипа: карточка редактируется на месте,
    чат не засоряется новыми сообщениями. Если кандидаты кончились — карточка
    гаснет. Просмотр и аналитика фиксируются после показа (как в `_show_candidate`).
    """
    service = _build_matching_service(db_session)
    next_results = await service.get_next_candidates(user.id, limit=1)
    if not next_results:
        await _no_more_candidates_inplace(message)
        return

    candidate_result = next_results[0]
    candidate = candidate_result.profile
    rendered = await _render_candidate(db_session, candidate)
    if rendered is None:
        await _no_more_candidates_inplace(message)
        return

    badge = _badge_prefix(candidate_result)
    caption = truncate_caption(f"{badge}{texts.CANDIDATE_HEADER}\n{rendered.text}")
    kb = actions_kb(candidate.user_id)
    media = _build_candidate_input_media(rendered, caption)

    shown = False
    if media is not None:
        try:
            await message.edit_media(media=media, reply_markup=kb)
            shown = True
        except TelegramAPIError as exc:  # pragma: no cover — telegram-сеть
            logger.warning("Failed to edit candidate card: {}", exc)
    if not shown:
        # Карточка была text-only (медиа не отправилось) или edit_media упал —
        # мягко деградируем к новому сообщению.
        await message.answer(caption, reply_markup=kb)

    matching_repo = MatchingRepository(db_session)
    await matching_repo.add_viewed(viewer_id=user.id, target_id=candidate.user_id)
    await AnalyticsRepository(db_session).log_event(
        user.id,
        event_type=EventType.PROFILE_VIEWED,
        payload={"target_user_id": candidate.user_id},
    )


async def _try_add_dislike(
    db_session: AsyncSession,
    *,
    from_user_id: int,
    to_user_id: int,
) -> bool:
    """Аналогично `_try_add_like` для Dislike."""
    try:
        async with db_session.begin_nested():
            await MatchingRepository(db_session).add_dislike(
                from_user_id=from_user_id,
                to_user_id=to_user_id,
            )
    except IntegrityError as exc:
        logger.warning(
            "duplicate dislike from_user_id={} to_user_id={}: {}",
            from_user_id,
            to_user_id,
            exc,
        )
        return False
    return True


def _moderation_error_text(reason: str | None) -> str:
    if reason == "link_detected":
        return texts.MODERATION_REJECTED_LINK
    return texts.MODERATION_REJECTED_STOP_WORD


# --------------------------- entry: «Искать своих» ---------------------------


@router.message(F.text == common_texts.BTN_SEARCH)
async def on_search(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Точка входа: пользователь нажал «Искать своих» в главном меню."""
    # На случай, если пользователь застрял в каком-то state — чистим.
    await state.clear()

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    if profile is None or not profile.is_completed:
        await message.answer(
            texts.NO_PROFILE_YET,
            reply_markup=main_menu_kb(is_registered=False),
        )
        return
    # Анкета ждёт ручную модерацию — не показываем чужие пока не одобрят.
    # Иначе пользователь, чьи материалы могут быть NSFW, видит и оценивает других.
    if profile.is_pending_review:
        await message.answer(texts.PROFILE_PENDING_REVIEW_BLOCKED)
        return

    service = _build_matching_service(db_session)
    candidate_results = await service.get_next_candidates(user.id, limit=20)
    if not candidate_results:
        await message.answer(texts.NO_CANDIDATES)
        return

    await _show_candidate(message, db_session, bot, user.id, candidate_results[0])


# --------------------------- callback: действия ---------------------------


@router.callback_query(MatchingActionCb.filter())
async def on_matching_action(
    callback: CallbackQuery,
    callback_data: MatchingActionCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Единый dispatcher для всех действий на карточке кандидата."""
    action = callback_data.action
    target_user_id = callback_data.target_user_id

    # Любое действие на карточке прерывает незавершённый ввод superlike-сообщения.
    # Иначе FSM-состояние «протекает»: текст на следующей карточке улетел бы как
    # лайк с сообщением старому кандидату.
    if await state.get_state() == MatchingStates.superlike_message.state:
        await state.clear()

    if action == "complain":
        await start_complaint_flow(
            callback,
            state,
            target_user_id=target_user_id,
            db_session=db_session,
        )
        return

    if action == "block":
        await start_block_flow(callback, target_user_id=target_user_id)
        return

    if callback.message is None:
        await callback.answer()
        return

    if action == "superlike":
        # Сохраняем контекст и переходим в режим ввода текста.
        await state.set_state(MatchingStates.superlike_message)
        await state.update_data(
            superlike_target_user_id=target_user_id,
            superlike_callback_message_id=callback.message.message_id,
        )
        await callback.answer()
        await callback.message.answer(
            texts.ASK_SUPERLIKE_MESSAGE,
            reply_markup=superlike_cancel_kb(),
        )
        return

    analytics_repo = AnalyticsRepository(db_session)

    if action == "like":
        service = _build_matching_service(db_session)
        outcome = await service.process_like(
            from_user_id=user.id,
            to_user_id=target_user_id,
            kind="like",
        )
        if outcome.like_recorded:
            await analytics_repo.log_event(
                user.id,
                event_type=EventType.LIKE,
                payload={"target_user_id": target_user_id},
            )
        if outcome.match_created:
            await analytics_repo.log_event(
                user.id,
                event_type=EventType.MATCH,
                payload={"match_id": outcome.match_id, "other_user_id": target_user_id},
            )
            await _send_match_notifications(
                bot,
                db_session,
                initiator_user=user,
                other_user_id=target_user_id,
                initial_message=outcome.initial_message,
            )
        await callback.answer()
        await _edit_to_next_candidate(callback.message, db_session, user)
        return

    if action == "dislike":
        wrote = await _try_add_dislike(db_session, from_user_id=user.id, to_user_id=target_user_id)
        if wrote:
            await analytics_repo.log_event(
                user.id,
                event_type=EventType.DISLIKE,
                payload={"target_user_id": target_user_id},
            )
        await callback.answer()
        await _edit_to_next_candidate(callback.message, db_session, user)
        return

    if action == "skip":
        # Скип — не решение: ни лайка, ни дизлайка. Анкета помечена просмотренной
        # при показе, поэтому уйдёт из выдачи и вернётся через view_cooldown_days
        # (по умолчанию 2 дня, настраивается) — «отложить на потом».
        # Дизлайк же исключает навсегда.
        await callback.answer()
        await _edit_to_next_candidate(callback.message, db_session, user)
        return

    # Неизвестный action — молча отвечаем, чтобы убрать спиннер.
    await callback.answer()


# --------------------------- superlike message ---------------------------


@router.message(Command("cancel"), StateFilter(MatchingStates.superlike_message))
async def cmd_cancel_superlike(message: Message, state: FSMContext) -> None:
    """`/cancel` во время ввода сообщения для superlike — выйти."""
    await state.clear()
    await message.answer(
        texts.SUPERLIKE_CANCELLED,
        reply_markup=main_menu_kb(is_registered=True),
    )


@router.callback_query(SuperlikeCancelCb.filter())
async def on_superlike_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Отмена» под запросом текста — выйти из режима лайка с сообщением."""
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.SUPERLIKE_CANCELLED)


@router.message(MatchingStates.superlike_message, F.text)
async def on_superlike_message(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(texts.ASK_SUPERLIKE_MESSAGE)
        return
    if len(text) > texts.SUPERLIKE_MESSAGE_MAX_LENGTH:
        await message.answer(texts.SUPERLIKE_MESSAGE_TOO_LONG)
        return

    data = await state.get_data()
    target_user_id = data.get("superlike_target_user_id")
    if target_user_id is None:
        # State протух / прямой вход — выходим без эффектов.
        await state.clear()
        await message.answer(texts.SUPERLIKE_CANCELLED)
        return

    moderation = ContentModerationService(ModerationRepository(db_session))
    result = await moderation.check_text(
        text,
        allow_links=False,
        target_kind="like_message",
        user_id=user.id,
    )
    if not result.approved:
        await message.answer(_moderation_error_text(result.reason))
        return

    service = _build_matching_service(db_session)
    outcome = await service.process_like(
        from_user_id=user.id,
        to_user_id=int(target_user_id),
        kind="superlike",
        message=text,
    )
    analytics_repo = AnalyticsRepository(db_session)
    if outcome.like_recorded:
        await analytics_repo.log_event(
            user.id,
            event_type=EventType.SUPERLIKE,
            payload={"target_user_id": int(target_user_id)},
        )
    if outcome.match_created:
        await analytics_repo.log_event(
            user.id,
            event_type=EventType.MATCH,
            payload={"match_id": outcome.match_id, "other_user_id": int(target_user_id)},
        )
        await _send_match_notifications(
            bot,
            db_session,
            initiator_user=user,
            other_user_id=int(target_user_id),
            initial_message=outcome.initial_message,
        )

    await state.clear()
    await message.answer(texts.SUPERLIKE_SENT)
    await _show_next_candidate(message, db_session, bot, user)
