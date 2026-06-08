"""Админский callback-handler: модератор выбирает вайб для запроса «Вайб по фото».

Сценарий:
1. Пользователь (Premium) нажал «Вайб по фото» в пикере own_vibe и прислал 1-3 фото.
2. Бот переотправил фото в MEDIA_STAGING_CHAT_ID с inline-клавиатурой ``vibe_by_photo_moderate_kb``.
3. Модератор (is_admin OR is_moderator) тапает на номер вайба или «Отклонить».
4. Этот handler разруливает оба варианта: при pick → сохраняет vibe в request,
   обновляет profile.own_vibe_id (если профиль уже есть) и шлёт юзеру результат;
   при reject → помечает запрос rejected и просит выбрать вайб вручную.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import VibeByPhotoAssignCb
from app.db.models.dictionaries import Vibe
from app.db.models.user import User
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.vibe_by_photo_repo import VibeByPhotoRepository
from app.services.access import is_admin_user
from app.texts import vibe_by_photo as texts

router = Router(name="admin_vibe_by_photo")


def _is_authorized(user: User) -> bool:
    """Модератор или администратор — единственная роль для приёма запроса."""
    return is_admin_user(user) or bool(user.is_moderator)


@router.callback_query(VibeByPhotoAssignCb.filter())
async def cb_vibe_by_photo_assign(
    callback: CallbackQuery,
    callback_data: VibeByPhotoAssignCb,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Единая точка для pick/reject модератора по запросу VBP."""
    if not _is_authorized(user):
        await callback.answer(texts.ADMIN_NOT_AUTHORIZED, show_alert=True)
        return

    repo = VibeByPhotoRepository(db_session)
    request = await repo.get_by_id(callback_data.request_id)
    if request is None:
        await callback.answer(texts.ADMIN_REQUEST_NOT_FOUND, show_alert=True)
        return
    if request.status != "pending":
        await callback.answer(texts.ADMIN_ALREADY_HANDLED, show_alert=True)
        return

    if callback_data.action == "reject":
        await _do_reject(callback, request_id=request.id, user=user, db_session=db_session, bot=bot)
        return

    if callback_data.action == "pick":
        await _do_assign(
            callback,
            request_id=request.id,
            vibe_number=callback_data.vibe_number,
            target_user_id=request.user_id,
            admin_user=user,
            db_session=db_session,
            bot=bot,
        )
        return

    await callback.answer()


async def _do_assign(
    callback: CallbackQuery,
    *,
    request_id: int,
    vibe_number: int,
    target_user_id: int,
    admin_user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Назначает выбранный вайб профилю пользователя и уведомляет его."""
    dict_repo = DictionaryRepository(db_session)
    vibes = await dict_repo.list_active(Vibe)
    vibe = next((v for v in vibes if v.number == vibe_number), None)
    if vibe is None:
        await callback.answer(texts.ADMIN_REQUEST_NOT_FOUND, show_alert=True)
        return

    repo = VibeByPhotoRepository(db_session)
    await repo.set_assigned(request_id, vibe_id=vibe.id, admin_user_id=admin_user.id)

    # Если у пользователя уже есть профиль (origin=profile_edit), сразу обновляем own_vibe_id.
    profile_repo = ProfileRepository(db_session)
    profile = await profile_repo.get_by_user_id(target_user_id)
    if profile is not None:
        await profile_repo.update(profile.id, own_vibe_id=vibe.id)
        await profile_repo.set_vibes_need_review(profile.id, False)

    # Узнаём telegram_id для уведомления.
    target_user = await UserRepository(db_session).get_by_id(target_user_id)
    if target_user is not None:
        try:
            await bot.send_message(
                chat_id=target_user.telegram_id,
                text=texts.RESULT_TEMPLATE.format(vibe_title=vibe.title),
            )
        except TelegramAPIError as exc:
            logger.warning(
                "vbp: failed to notify user {} about assigned vibe: {}",
                target_user.telegram_id,
                exc,
            )

    await callback.answer(
        texts.ADMIN_ASSIGNED_TEMPLATE.format(vibe_title=vibe.title, user_id=target_user_id),
        show_alert=False,
    )
    # Уберём клавиатуру у сообщения, чтобы повторно не нажимали.
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError as exc:
            logger.warning("vbp: failed to clear reply markup: {}", exc)


async def _do_reject(
    callback: CallbackQuery,
    *,
    request_id: int,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Помечает запрос как rejected и просит юзера выбрать вайб вручную."""
    repo = VibeByPhotoRepository(db_session)
    request = await repo.set_rejected(request_id, admin_user_id=user.id)
    if request is None:
        await callback.answer(texts.ADMIN_REQUEST_NOT_FOUND, show_alert=True)
        return

    target_user = await UserRepository(db_session).get_by_id(request.user_id)
    if target_user is not None:
        try:
            await bot.send_message(
                chat_id=target_user.telegram_id,
                text=texts.REJECTED,
            )
        except TelegramAPIError as exc:
            logger.warning(
                "vbp: failed to notify user {} about rejection: {}",
                target_user.telegram_id,
                exc,
            )

    await callback.answer(
        texts.ADMIN_REJECTED_TEMPLATE.format(request_id=request_id),
        show_alert=False,
    )
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError as exc:
            logger.warning("vbp: failed to clear reply markup on reject: {}", exc)


__all__ = ["router"]
