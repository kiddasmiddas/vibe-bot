"""Поток «Жалоба» (этап 5.1).

Запускается из карточки кандидата (matching.py) и из карточки входящего лайка
(matches.py) через публичный helper `start_complaint_flow`. Сам поток
управляется FSM-состоянием `ComplaintStates`.
"""

from __future__ import annotations

from html import escape as _html_escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.complaints import (
    ComplaintCommentCb,
    ComplaintReasonCb,
    comment_kb,
    reasons_kb,
)
from app.bot.states.complaints import ComplaintStates
from app.config import settings
from app.db.models.dictionaries import ComplaintReason
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.complaint_repo import ComplaintRepository
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from app.services.content_moderation_service import ContentModerationService
from app.texts import complaints as texts
from app.texts import matching as matching_texts

router = Router(name="complaints")


# --------------------------- public entry ---------------------------


async def start_complaint_flow(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    target_user_id: int,
    db_session: AsyncSession,
) -> None:
    """Запускает поток жалобы: спрашивает причину и переводит FSM.

    Вызывается из matching.py и matches.py по нажатию 🚩.
    Если пользователь уже в complaint-state с другим target — принудительно
    сбрасываем предыдущий flow, чтобы избежать гонок и спутанной записи
    жалобы (см. code-review этапа 5).
    """
    if callback.message is None:
        await callback.answer()
        return

    current_state = await state.get_state()
    if current_state in {
        ComplaintStates.choosing_reason.state,
        ComplaintStates.writing_comment.state,
    }:
        # Сбрасываем — старая клавиатура в чате перестанет работать
        # благодаря тому, что reason_id очистится.
        await state.clear()

    dict_repo = DictionaryRepository(db_session)
    kb = await reasons_kb(target_user_id=target_user_id, dict_repo=dict_repo)

    await state.set_state(ComplaintStates.choosing_reason)
    await state.update_data(complaint_target_user_id=target_user_id)
    await callback.answer()
    await callback.message.answer(texts.ASK_REASON, reply_markup=kb)


# --------------------------- helpers ---------------------------


async def _notify_admins_about_complaint(
    bot: Bot,
    *,
    complaint_id: int,
    from_user: User,
    target_user: User,
    from_nickname: str,
    target_nickname: str,
    reason_title: str,
    comment: str | None,
) -> None:
    """Шлёт уведомление о жалобе администраторам из env.

    Жалобы — чувствительные данные (никнеймы, tg-ссылки на участников), поэтому
    рассылаются только админам из `settings.admin_telegram_ids`, без модераторов.
    User-supplied поля экранируются — шаблон рендерится с parse_mode=HTML и
    содержит активные tg://-ссылки, инъекция HTML недопустима.
    """
    recipient_ids = list(settings.admin_telegram_ids)
    if not recipient_ids:
        logger.warning("complaint #{}: no admins configured to notify", complaint_id)
        return

    text = texts.ADMIN_NOTIFY_TEMPLATE.format(
        complaint_id=complaint_id,
        from_nickname=_html_escape(from_nickname),
        from_id=from_user.id,
        from_tg_id=from_user.telegram_id,
        target_nickname=_html_escape(target_nickname),
        target_id=target_user.id,
        target_tg_id=target_user.telegram_id,
        reason=_html_escape(reason_title),
        comment=_html_escape(comment or "—"),
    )
    for admin_id in recipient_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
        except TelegramAPIError as exc:
            logger.error(
                "Failed to notify admin {} about complaint #{}: {}",
                admin_id,
                complaint_id,
                exc,
            )


async def _save_complaint_and_notify(
    *,
    db_session: AsyncSession,
    bot: Bot,
    from_user: User,
    target_user_id: int,
    reason_id: int,
    comment: str | None,
) -> None:
    """Записывает жалобу, пишет аналитику и шлёт уведомление админам."""
    user_repo = UserRepository(db_session)
    target_user = await user_repo.get_by_id(target_user_id)
    if target_user is None:
        # Защита: target пропал между показом карточки и подтверждением. Лучше
        # упасть с понятным логом и НЕ создавать жалобу-сироту в БД.
        logger.error("complaint flow: target_user_id={} not found, aborting", target_user_id)
        return

    complaint_repo = ComplaintRepository(db_session)
    complaint = await complaint_repo.create(
        from_user_id=from_user.id,
        target_user_id=target_user_id,
        reason_id=reason_id,
        comment=comment,
    )

    await AnalyticsRepository(db_session).log_event(
        from_user.id,
        event_type=EventType.COMPLAINT_FILED,
        payload={
            "target_user_id": target_user_id,
            "reason_id": reason_id,
            "complaint_id": complaint.id,
        },
    )

    dict_repo = DictionaryRepository(db_session)
    reason = await dict_repo.get_by_id(ComplaintReason, reason_id)
    reason_title = reason.title if reason is not None else str(reason_id)

    profile_repo = ProfileRepository(db_session)
    from_profile = await profile_repo.get_by_user_id(from_user.id)
    target_profile = await profile_repo.get_by_user_id(target_user_id)

    from_nickname = from_profile.nickname if from_profile is not None else f"id={from_user.id}"
    target_nickname = (
        target_profile.nickname if target_profile is not None else f"id={target_user_id}"
    )

    await _notify_admins_about_complaint(
        bot,
        complaint_id=complaint.id,
        from_user=from_user,
        target_user=target_user,
        from_nickname=from_nickname,
        target_nickname=target_nickname,
        reason_title=reason_title,
        comment=comment,
    )


def _moderation_error_text(reason: str | None) -> str:
    # В комментарии жалобы ссылки разрешены (), поэтому
    # единственная возможная причина — стоп-слово.
    if reason == "link_detected":
        # Технически невозможно при allow_links=True, но на всякий случай.
        return matching_texts.MODERATION_REJECTED_LINK
    return texts.COMMENT_REJECTED_STOP_WORD


# --------------------------- handlers ---------------------------


@router.callback_query(ComplaintReasonCb.filter(), StateFilter(ComplaintStates.choosing_reason))
async def on_reason_picked(
    callback: CallbackQuery,
    callback_data: ComplaintReasonCb,
    state: FSMContext,
) -> None:
    """Пользователь выбрал причину — переходим к шагу ввода комментария."""
    if callback.message is None:
        await callback.answer()
        return

    await state.update_data(
        complaint_reason_id=callback_data.reason_id,
        complaint_target_user_id=callback_data.target_user_id,
    )
    await state.set_state(ComplaintStates.writing_comment)
    await callback.answer()
    await callback.message.answer(
        texts.ASK_COMMENT,
        reply_markup=comment_kb(target_user_id=callback_data.target_user_id),
    )


@router.message(StateFilter(ComplaintStates.writing_comment), F.text)
async def on_comment_text(
    message: Message,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Пользователь прислал комментарий. Модерация → сохранение."""
    text = (message.text or "").strip()
    data = await state.get_data()
    target_user_id = data.get("complaint_target_user_id")
    reason_id = data.get("complaint_reason_id")
    if target_user_id is None or reason_id is None:
        # State протух / прямой вход без контекста — выходим тихо.
        await state.clear()
        await message.answer(texts.COMPLAINT_CANCELLED)
        return

    if text:
        moderation = ContentModerationService(ModerationRepository(db_session))
        result = await moderation.check_text(
            text,
            allow_links=True,
            target_kind="complaint_comment",
            user_id=user.id,
        )
        if not result.approved:
            await message.answer(_moderation_error_text(result.reason))
            return

    await _save_complaint_and_notify(
        db_session=db_session,
        bot=bot,
        from_user=user,
        target_user_id=int(target_user_id),
        reason_id=int(reason_id),
        comment=text or None,
    )

    await state.clear()
    await message.answer(texts.COMPLAINT_SENT)
    # Ленивый импорт во избежание циклической зависимости с matching.py.
    from app.bot.handlers.matching import _show_next_candidate

    await _show_next_candidate(message, db_session, bot, user)


@router.callback_query(
    ComplaintCommentCb.filter(F.action == "skip"),
    StateFilter(ComplaintStates.writing_comment),
)
async def on_comment_skip(
    callback: CallbackQuery,
    callback_data: ComplaintCommentCb,
    state: FSMContext,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Пользователь решил не писать комментарий — сохраняем как есть."""
    if callback.message is None:
        await callback.answer()
        return

    data = await state.get_data()
    target_user_id = data.get("complaint_target_user_id") or callback_data.target_user_id
    reason_id = data.get("complaint_reason_id")
    if reason_id is None:
        await state.clear()
        await callback.answer()
        await callback.message.answer(texts.COMPLAINT_CANCELLED)
        return

    await _save_complaint_and_notify(
        db_session=db_session,
        bot=bot,
        from_user=user,
        target_user_id=int(target_user_id),
        reason_id=int(reason_id),
        comment=None,
    )

    await state.clear()
    await callback.answer()
    await callback.message.answer(texts.COMPLAINT_SENT)
    from app.bot.handlers.matching import _show_next_candidate

    await _show_next_candidate(callback.message, db_session, bot, user)


@router.callback_query(ComplaintCommentCb.filter(F.action == "cancel"))
async def on_complaint_cancel(
    callback: CallbackQuery,
    callback_data: ComplaintCommentCb,
    state: FSMContext,
) -> None:
    """Отмена жалобы на любом шаге."""
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(texts.COMPLAINT_CANCELLED)
