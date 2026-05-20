"""Раздел «Жалобы» админки (10.4) — медиа-карточки, пагинация."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminComplaintActionCb,
    AdminMenuCb,
    admin_back_home_kb,
    complaint_card_kb,
    complaint_list_kb,
)
from app.bot.utils.render_profile import build_rendered_profile
from app.db.models.dictionaries import ComplaintReason
from app.db.models.user import User
from app.db.repositories.complaint_repo import ComplaintRepository, ComplaintWithDetails
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import (
    COMPLAINTS_CARD_CAPTION,
    COMPLAINTS_CARD_NO_PROFILE,
    COMPLAINTS_EMPTY,
    COMPLAINTS_NOT_FOUND,
    COMPLAINTS_REASON_UNKNOWN,
    COMPLAINTS_REJECTED,
    COMPLAINTS_RESOLVED,
    COMPLAINTS_SELECT_STATUS,
    COMPLAINTS_TARGET_BANNED,
)

router = Router(name="admin.complaints")

_STATUS_MAP = {
    "list_new": "new",
    "list_resolved": "resolved",
    "list_rejected": "rejected",
}

# Сколько жалоб подгружаем за один запрос (1 = одна карточка за раз).
_PAGE_SIZE = 1


def _fmt_username(username: str | None, *, fallback: str = "") -> str:
    """Форматирует @username или возвращает fallback."""
    if username:
        return f"@{username}"
    return fallback


async def _get_reason_title(db_session: AsyncSession, reason_id: int) -> str:
    """Возвращает читаемый заголовок причины жалобы или строку-id как fallback."""
    repo = DictionaryRepository(db_session)
    reason = await repo.get_by_id(ComplaintReason, reason_id)
    if reason is None:
        return COMPLAINTS_REASON_UNKNOWN.format(reason_id=reason_id)
    return reason.title


def _build_caption(
    detail: ComplaintWithDetails,
    *,
    profile_text: str | None,
    reason_title: str,
    page: int,
    total: int,
) -> str:
    """Собирает caption для карточки жалобы.

    Если profile_text задан — отображаем полный текст анкеты. Иначе — только
    идентификатор нарушителя.
    """
    reporter_username = _fmt_username(
        detail.reporter.username,
        fallback=f"id={detail.reporter.telegram_id}",
    )
    comment = detail.complaint.comment or "—"
    complaint_id = detail.complaint.id

    if profile_text is not None:
        violator_username_part = _fmt_username(detail.violator.username)
        if violator_username_part:
            # Вставляем @username сразу после первой строки (никнейм + возраст).
            lines = profile_text.splitlines()
            if lines:
                lines[0] = f"{lines[0]} ({violator_username_part})"
            profile_text = "\n".join(lines)
        return COMPLAINTS_CARD_CAPTION.format(
            profile_text=profile_text,
            complaint_id=complaint_id,
            page=page,
            total=total,
            reporter_username=reporter_username,
            reason=reason_title,
            comment=comment,
        )

    violator_username_part = (
        f" ({_fmt_username(detail.violator.username)})" if detail.violator.username else ""
    )
    return COMPLAINTS_CARD_NO_PROFILE.format(
        violator_id=detail.violator.id,
        violator_username_part=violator_username_part,
        complaint_id=complaint_id,
        page=page,
        total=total,
        reporter_username=reporter_username,
        reason=reason_title,
        comment=comment,
    )


async def _show_complaint_card(
    callback: CallbackQuery,
    db_session: AsyncSession,
    *,
    offset: int,
    status: str,
) -> None:
    """Подгружает одну жалобу по offset и рендерит её карточкой."""
    if not callback.message:
        return

    repo = ComplaintRepository(db_session)
    # count_with_details согласован с list_with_details (те же INNER JOIN),
    # поэтому total и offset считаются по одному набору.
    total = await repo.count_with_details(status)

    if total == 0:
        await show_screen(
            callback.message, text=COMPLAINTS_EMPTY, reply_markup=admin_back_home_kb()
        )
        return

    # Если offset вышел за пределы — возвращаемся к последней.
    offset = min(offset, total - 1)

    details = await repo.list_with_details(status=status, offset=offset, limit=_PAGE_SIZE)
    if not details:
        await show_screen(
            callback.message, text=COMPLAINTS_EMPTY, reply_markup=admin_back_home_kb()
        )
        return

    detail = details[0]
    reason_title = await _get_reason_title(db_session, detail.complaint.reason_id)
    page = offset + 1

    kb = complaint_card_kb(
        complaint_id=detail.complaint.id,
        offset=offset,
        status=status,
    )

    # Попытка отрендерить анкету нарушителя.
    rendered = None
    if detail.violator_profile is not None:
        rendered = await build_rendered_profile(db_session, detail.violator_profile)

    if rendered is not None:
        caption = _build_caption(
            detail,
            profile_text=rendered.text,
            reason_title=reason_title,
            page=page,
            total=total,
        )
        await show_screen(
            callback.message,
            text=caption,
            reply_markup=kb,
            media_file_id=rendered.media_file_id,
            media_type=rendered.media_type,
            parse_mode="HTML",
        )
    else:
        # Нет анкеты или рендер не удался — текстовый экран.
        caption = _build_caption(
            detail,
            profile_text=None,
            reason_title=reason_title,
            page=page,
            total=total,
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


@router.callback_query(AdminMenuCb.filter(F.action == "complaints"))
async def cb_complaints_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(
            callback.message,
            text=COMPLAINTS_SELECT_STATUS,
            reply_markup=complaint_list_kb(),
        )


@router.callback_query(
    AdminComplaintActionCb.filter(F.action.in_({"list_new", "list_resolved", "list_rejected"}))
)
async def cb_complaints_list(
    callback: CallbackQuery,
    callback_data: AdminComplaintActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return

    status = _STATUS_MAP.get(callback_data.action, "new")
    await callback.answer()
    await _show_complaint_card(callback, db_session, offset=0, status=status)


@router.callback_query(AdminComplaintActionCb.filter(F.action == "card"))
async def cb_complaint_card_navigate(
    callback: CallbackQuery,
    callback_data: AdminComplaintActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Навигация «Назад» к предыдущей карточке (offset уменьшается в клавиатуре)."""
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_complaint_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminComplaintActionCb.filter(F.action == "skip"))
async def cb_complaint_skip(
    callback: CallbackQuery,
    callback_data: AdminComplaintActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Пропустить: перейти к следующей жалобе без изменения статуса текущей."""
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    await _show_complaint_card(
        callback, db_session, offset=callback_data.offset, status=callback_data.status
    )


@router.callback_query(AdminComplaintActionCb.filter(F.action == "reject"))
async def cb_reject_complaint(
    callback: CallbackQuery,
    callback_data: AdminComplaintActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    repo = ComplaintRepository(db_session)
    complaint = await repo.get_by_id(callback_data.complaint_id)
    if not complaint:
        await callback.answer(COMPLAINTS_NOT_FOUND, show_alert=True)
        return
    await repo.reject(callback_data.complaint_id, moderator_user_id=user.id)
    logger.info("admin {} rejected complaint {}", user.id, callback_data.complaint_id)
    await callback.answer()
    if callback.message:
        result_text = COMPLAINTS_REJECTED.format(id=callback_data.complaint_id)
        await show_screen(callback.message, text=result_text, reply_markup=admin_back_home_kb())


@router.callback_query(AdminComplaintActionCb.filter(F.action == "ban_target"))
async def cb_ban_target(
    callback: CallbackQuery,
    callback_data: AdminComplaintActionCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    complaint_repo = ComplaintRepository(db_session)
    complaint = await complaint_repo.get_by_id(callback_data.complaint_id)
    if not complaint:
        await callback.answer(COMPLAINTS_NOT_FOUND, show_alert=True)
        return
    user_repo = UserRepository(db_session)
    await user_repo.set_banned(complaint.target_user_id, banned=True)
    await complaint_repo.resolve(callback_data.complaint_id, moderator_user_id=user.id)
    logger.info(
        "admin {} banned user {} via complaint {}",
        user.id,
        complaint.target_user_id,
        complaint.id,
    )
    await callback.answer(COMPLAINTS_TARGET_BANNED, show_alert=True)
    if callback.message:
        result_text = COMPLAINTS_RESOLVED.format(id=callback_data.complaint_id)
        await show_screen(callback.message, text=result_text, reply_markup=admin_back_home_kb())
