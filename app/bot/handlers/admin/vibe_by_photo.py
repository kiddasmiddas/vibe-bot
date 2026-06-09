"""Админский хэндлер «Вайб по фото».

Поток (после редизайна):
1. Юзер (Premium) нажал «Вайб по фото» в пикере own_vibe и прислал 1-3 фото.
2. Bot создаёт VibeByPhotoRequest, отправляет фото в staging-чат КАК АРХИВ
   (без кнопок), и каждому модератору в личку — пару сообщений:
   Msg1 = «анкета» (фото + заголовок), Msg2 = пикер вайбов с пагинацией
   3×3 + skip/prev/reject.
3. Модератор нажимает:
   - номер вайба → request assigned, юзер получает результат, чат
     автоматически продолжается следующим pending-запросом;
   - «❌ Отклонить» → request rejected, юзер просят выбрать вайб вручную;
   - «‹/›» → пагинация страниц 1/4..4/4 внутри запроса (edit text+kb);
   - «↩️ К прошлой» → шлёт пару для предыдущего pending;
   - «⏭ Пропустить» → шлёт пару для следующего pending.
4. Тот же экран открывается из /admin → «🖼 Вайб по фото» → тап по элементу
   списка → пара сообщений с этим request_id.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    VBP_PAGE_SIZE,
    VBP_TOTAL_PAGES,
    AdminMenuCb,
    VibeByPhotoAssignCb,
    VibeByPhotoQueueCb,
    vibe_by_photo_moderate_kb,
    vibe_by_photo_notification_kb,
    vibe_by_photo_queue_kb,
)
from app.db.models.dictionaries import Vibe
from app.db.models.user import User
from app.db.models.vibe_by_photo import VibeByPhotoRequest
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


# --------------------------------------------------------------------------- #
# Render helpers — переиспользуются и при первичной отправке (из registration)
# и при навигации (skip/prev/open-from-queue).
# --------------------------------------------------------------------------- #


async def _build_request_header_caption(
    request: VibeByPhotoRequest, *, db_session: AsyncSession
) -> str:
    """Строит HTML-caption для Msg1 (анкета): шапка + блок профиля, если есть."""
    from html import escape as _html_escape

    target_user = await UserRepository(db_session).get_by_id(request.user_id)
    if target_user is not None:
        username = target_user.username or ""
        username_display = f"@{_html_escape(username)}" if username else "(нет)"
    else:
        username_display = "(удалён)"

    profile_block = texts.ADMIN_REQUEST_PROFILE_BLOCK_NO_PROFILE
    if request.profile_id is not None:
        profile_repo = ProfileRepository(db_session)
        profile = await profile_repo.get_by_id(request.profile_id)
        if profile is not None:
            dict_repo = DictionaryRepository(db_session)
            vibes = await dict_repo.list_active(Vibe)
            current_vibe = next((v for v in vibes if v.id == profile.own_vibe_id), None)
            profile_block = texts.ADMIN_REQUEST_PROFILE_BLOCK_TEMPLATE.format(
                nickname=_html_escape(profile.nickname),
                age=profile.age,
                city=_html_escape(profile.city or "—"),
                current_vibe=_html_escape(current_vibe.title if current_vibe else "—"),
            )

    return texts.ADMIN_REQUEST_HEADER_TEMPLATE.format(
        request_id=request.id,
        user_id=request.user_id,
        username=username_display,
        origin=request.origin,
        profile_block=profile_block,
    )


def _picker_text(request_id: int, page: int) -> str:
    return texts.ADMIN_PICK_VIBE_HEADER_TEMPLATE.format(
        request_id=request_id,
        page_num=page + 1,
        total_pages=VBP_TOTAL_PAGES,
    )


def _picker_kb(request_id: int, page: int) -> InlineKeyboardMarkup:
    return vibe_by_photo_moderate_kb(
        request_id=request_id,
        page=page,
        page_size=VBP_PAGE_SIZE,
        total_pages=VBP_TOTAL_PAGES,
        page_prev_text=texts.ADMIN_BTN_PAGE_PREV,
        page_next_text=texts.ADMIN_BTN_PAGE_NEXT,
        prev_request_text=texts.ADMIN_BTN_PREV_REQUEST,
        skip_request_text=texts.ADMIN_BTN_SKIP_REQUEST,
        reject_text=texts.ADMIN_BTN_REJECT,
    )


async def send_request_pair(
    bot: Bot,
    *,
    chat_id: int,
    db_session: AsyncSession,
    request: VibeByPhotoRequest,
    page: int = 0,
) -> None:
    """Шлёт пару сообщений в chat_id: Msg1=фото с заголовком, Msg2=пикер.

    Используется из registration.py при создании запроса (рассылка модераторам)
    и из текущего модуля при skip/prev/open-from-queue.

    Если у запроса 0 фото — не шлём пикер (модератору нечего оценивать),
    логируем error и тихо выходим. dispatch_vbp_request валидирует, что file_ids
    непуст, так что это защитный кейс (например, повреждённый storage).
    """
    photo_file_ids = VibeByPhotoRepository.get_photo_file_ids(request)
    if not photo_file_ids:
        logger.error(
            "vbp: request {} has no photos — skipping picker dispatch to chat {}",
            request.id,
            chat_id,
        )
        return

    caption = await _build_request_header_caption(request, db_session=db_session)

    try:
        if len(photo_file_ids) >= 2:
            media = [
                InputMediaPhoto(
                    media=fid,
                    caption=caption if idx == 0 else None,
                    parse_mode="HTML" if idx == 0 else None,
                )
                for idx, fid in enumerate(photo_file_ids)
            ]
            await bot.send_media_group(chat_id=chat_id, media=media)
        else:
            # len == 1 — гарантировано early-return'ом на пустом списке выше.
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file_ids[0],
                caption=caption,
                parse_mode="HTML",
            )
    except TelegramAPIError as exc:
        logger.warning(
            "vbp: failed to send Msg1 for request {} to chat {}: {}",
            request.id,
            chat_id,
            exc,
        )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=_picker_text(request.id, page),
            reply_markup=_picker_kb(request.id, page),
        )
    except TelegramAPIError as exc:
        logger.warning(
            "vbp: failed to send Msg2 picker for request {} to chat {}: {}",
            request.id,
            chat_id,
            exc,
        )


# --------------------------------------------------------------------------- #
# Callback handler — основной маршрутизатор действий модератора.
# --------------------------------------------------------------------------- #


@router.callback_query(VibeByPhotoAssignCb.filter())
async def cb_vibe_by_photo_assign(
    callback: CallbackQuery,
    callback_data: VibeByPhotoAssignCb,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Единая точка для всех действий модератора в пикере «Вайб по фото»."""
    if not _is_authorized(user):
        await callback.answer(texts.ADMIN_NOT_AUTHORIZED, show_alert=True)
        return

    action = callback_data.action

    if action == "noop":
        await callback.answer()
        return

    if action == "page":
        await _do_page(callback, request_id=callback_data.request_id, page=callback_data.page)
        return

    if action == "skip":
        await _do_navigate(
            callback,
            current_request_id=callback_data.request_id,
            db_session=db_session,
            bot=bot,
            direction="next",
        )
        return

    if action == "prev":
        await _do_navigate(
            callback,
            current_request_id=callback_data.request_id,
            db_session=db_session,
            bot=bot,
            direction="prev",
        )
        return

    repo = VibeByPhotoRepository(db_session)
    request = await repo.get_by_id(callback_data.request_id)
    if request is None:
        await callback.answer(texts.ADMIN_REQUEST_NOT_FOUND, show_alert=True)
        return
    if request.status != "pending":
        await callback.answer(texts.ADMIN_ALREADY_HANDLED, show_alert=True)
        return

    if action == "reject":
        await _do_reject(
            callback,
            request=request,
            admin_user=user,
            db_session=db_session,
            bot=bot,
        )
        return

    if action == "pick":
        await _do_assign(
            callback,
            request=request,
            vibe_number=callback_data.vibe_number,
            admin_user=user,
            db_session=db_session,
            bot=bot,
        )
        return

    await callback.answer()


async def _do_page(callback: CallbackQuery, *, request_id: int, page: int) -> None:
    """Переключение страницы вайбов внутри текущего запроса."""
    if callback.message is None:
        await callback.answer()
        return
    page = max(0, min(page, VBP_TOTAL_PAGES - 1))
    try:
        await callback.message.edit_text(
            text=_picker_text(request_id, page),
            reply_markup=_picker_kb(request_id, page),
        )
    except TelegramAPIError as exc:
        logger.warning("vbp: failed to edit picker page for request {}: {}", request_id, exc)
    await callback.answer()


async def _do_navigate(
    callback: CallbackQuery,
    *,
    current_request_id: int,
    db_session: AsyncSession,
    bot: Bot,
    direction: str,
) -> None:
    """skip / prev — переход к соседнему pending-запросу.

    Старую клавиатуру отключаем (edit_reply_markup→None), новую пару шлём ниже.
    """
    if callback.message is None:
        # Без сообщения нечего ни редактировать, ни слать; отвечаем callback,
        # чтобы клиент не висел со спиннером.
        await callback.answer()
        return

    repo = VibeByPhotoRepository(db_session)
    neighbor = await repo.get_neighbor_pending(current_request_id, direction=direction)
    if neighbor is None:
        msg = texts.ADMIN_NO_NEXT_REQUEST if direction == "next" else texts.ADMIN_NO_PREV_REQUEST
        await callback.answer(msg, show_alert=False)
        return

    await _disable_current_picker(callback)
    await send_request_pair(
        bot,
        chat_id=callback.message.chat.id,
        db_session=db_session,
        request=neighbor,
        page=0,
    )
    await callback.answer()


async def _disable_current_picker(callback: CallbackQuery) -> None:
    """Снимает клавиатуру с текущего Msg2 — чтобы по нему больше не кликали."""
    if callback.message is None:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.warning("vbp: failed to clear reply markup: {}", exc)


async def _auto_advance(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    bot: Bot,
    excluded_request_id: int,
) -> None:
    """После pick/reject — auto-advance к следующему pending; если пусто, шлёт notice."""
    repo = VibeByPhotoRepository(db_session)
    # «Следующий» относительно обработанного. Если соседа сверху нет (мы
    # обработали последний по created_at) — пробуем самый старый. Исключаем
    # обработанный id явно — на случай если он попадёт в pending-запрос
    # повторно через identity-map при rollback или иной race.
    next_pending = await repo.get_neighbor_pending(excluded_request_id, direction="next")
    if next_pending is None:
        next_pending = await repo.get_first_pending(excluded_id=excluded_request_id)

    if callback.message is None:
        return

    if next_pending is None:
        try:
            await callback.message.answer(text=texts.ADMIN_QUEUE_EMPTY_AFTER_ACTION)
        except TelegramAPIError as exc:
            logger.warning("vbp: failed to send queue-empty notice: {}", exc)
        return

    await send_request_pair(
        bot,
        chat_id=callback.message.chat.id,
        db_session=db_session,
        request=next_pending,
        page=0,
    )


async def _do_assign(
    callback: CallbackQuery,
    *,
    request: VibeByPhotoRequest,
    vibe_number: int,
    admin_user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Назначает выбранный вайб профилю + уведомляет юзера + auto-advance."""
    dict_repo = DictionaryRepository(db_session)
    vibes = await dict_repo.list_active(Vibe)
    vibe = next((v for v in vibes if v.number == vibe_number), None)
    if vibe is None:
        await callback.answer(texts.ADMIN_REQUEST_NOT_FOUND, show_alert=True)
        return

    repo = VibeByPhotoRepository(db_session)
    updated = await repo.set_assigned(request.id, vibe_id=vibe.id, admin_user_id=admin_user.id)
    if updated is None:
        # TOCTOU: между прочтением request.status и UPDATE другой модератор
        # уже обработал запрос. Не уведомляем юзера повторно и не
        # обновляем профиль — это сделал «победитель» гонки.
        await callback.answer(texts.ADMIN_ALREADY_HANDLED, show_alert=True)
        return

    # Профиль обновляем по request.profile_id (тот, который модератор видел),
    # с fallback на get_by_user_id если snapshot отсутствует (origin=registration).
    profile_repo = ProfileRepository(db_session)
    profile = None
    if request.profile_id is not None:
        profile = await profile_repo.get_by_id(request.profile_id)
    if profile is None:
        profile = await profile_repo.get_by_user_id(request.user_id)
    if profile is not None:
        await profile_repo.update(profile.id, own_vibe_id=vibe.id)
        await profile_repo.set_vibes_need_review(profile.id, False)

    target_user = await UserRepository(db_session).get_by_id(request.user_id)
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
        texts.ADMIN_ASSIGNED_TEMPLATE.format(vibe_title=vibe.title, user_id=request.user_id),
        show_alert=False,
    )
    await _disable_current_picker(callback)
    await _auto_advance(callback, db_session=db_session, bot=bot, excluded_request_id=request.id)


async def _do_reject(
    callback: CallbackQuery,
    *,
    request: VibeByPhotoRequest,
    admin_user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Помечает запрос как rejected, шлёт юзеру REJECTED, auto-advance."""
    repo = VibeByPhotoRepository(db_session)
    updated = await repo.set_rejected(request.id, admin_user_id=admin_user.id)
    if updated is None:
        # TOCTOU: другой модератор уже обработал.
        await callback.answer(texts.ADMIN_ALREADY_HANDLED, show_alert=True)
        return

    target_user = await UserRepository(db_session).get_by_id(request.user_id)
    if target_user is not None:
        try:
            await bot.send_message(chat_id=target_user.telegram_id, text=texts.REJECTED)
        except TelegramAPIError as exc:
            logger.warning(
                "vbp: failed to notify user {} about rejection: {}",
                target_user.telegram_id,
                exc,
            )

    await callback.answer(
        texts.ADMIN_REJECTED_TEMPLATE.format(request_id=request.id),
        show_alert=False,
    )
    await _disable_current_picker(callback)
    await _auto_advance(callback, db_session=db_session, bot=bot, excluded_request_id=request.id)


# --------------------------------------------------------------------------- #
# /admin → «Вайб по фото»: список pending и открытие конкретного запроса.
# --------------------------------------------------------------------------- #


@router.callback_query(AdminMenuCb.filter(F.action == "vbp_queue"))
async def cb_vbp_queue_list(
    callback: CallbackQuery,
    user: User,
    db_session: AsyncSession,
) -> None:
    """Раздел «🖼 Вайб по фото» в /admin: рендер списка pending-запросов.

    Каждый элемент — кнопка с request_id и username. Тап → открывается
    Msg1+Msg2 в личке через ``cb_vibe_by_photo_queue``.
    """
    if not _is_authorized(user):
        await callback.answer(texts.ADMIN_NOT_AUTHORIZED, show_alert=True)
        return

    repo = VibeByPhotoRepository(db_session)
    pending = await repo.list_pending(limit=30)
    user_repo = UserRepository(db_session)

    items: list[tuple[int, str]] = []
    body_lines: list[str] = [texts.ADMIN_QUEUE_TITLE, ""]
    if not pending:
        body_lines.append(texts.ADMIN_QUEUE_EMPTY)
    else:
        body_lines.append(texts.ADMIN_QUEUE_FOUND_TEMPLATE.format(count=len(pending)))
        body_lines.append("")
        for req in pending:
            target_user = await user_repo.get_by_id(req.user_id)
            username = (
                f"@{target_user.username}"
                if target_user is not None and target_user.username
                else f"id={req.user_id}"
            )
            photos_count = len(VibeByPhotoRepository.get_photo_file_ids(req))
            body_lines.append(
                texts.ADMIN_QUEUE_ITEM_TEMPLATE.format(
                    request_id=req.id,
                    username=username,
                    photos_count=photos_count,
                    origin=req.origin,
                )
            )
            items.append(
                (
                    req.id,
                    texts.ADMIN_QUEUE_BTN_OPEN_TEMPLATE.format(
                        request_id=req.id, username=username
                    ),
                )
            )

    from app.texts.admin import ADMIN_MENU_BTN_HOME

    kb = vibe_by_photo_queue_kb(items, home_text=ADMIN_MENU_BTN_HOME)

    if callback.message is not None:
        try:
            await callback.message.edit_text(
                text="\n".join(body_lines), reply_markup=kb, parse_mode="HTML"
            )
        except TelegramAPIError as exc:
            logger.warning("vbp queue: edit_text failed, trying answer: {}", exc)
            await callback.message.answer(
                text="\n".join(body_lines), reply_markup=kb, parse_mode="HTML"
            )
    await callback.answer()


@router.callback_query(VibeByPhotoQueueCb.filter())
async def cb_vibe_by_photo_queue(
    callback: CallbackQuery,
    callback_data: VibeByPhotoQueueCb,
    user: User,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    """Открыть конкретный запрос из списка очереди /admin."""
    if not _is_authorized(user):
        await callback.answer(texts.ADMIN_NOT_AUTHORIZED, show_alert=True)
        return

    if callback_data.action != "open":
        await callback.answer()
        return

    repo = VibeByPhotoRepository(db_session)
    request = await repo.get_by_id(callback_data.request_id)
    if request is None or request.status != "pending":
        await callback.answer(texts.ADMIN_REQUEST_NOT_FOUND, show_alert=True)
        return

    if callback.message is None:
        await callback.answer()
        return

    await send_request_pair(
        bot,
        chat_id=callback.message.chat.id,
        db_session=db_session,
        request=request,
        page=0,
    )
    await callback.answer()


async def dispatch_vbp_request(
    bot: Bot,
    *,
    db_session: AsyncSession,
    user: User,
    file_ids: list[str],
    origin: str,
) -> VibeByPhotoRequest:
    """Создаёт запрос в БД, кидает фото в staging-архив (без кнопок), шлёт
    каждому модератору в личку пару «фото + пикер».

    Используется из registration.py и profile.py — обе точки входа в
    Premium-фичу «Вайб по фото».
    """
    from html import escape as _html_escape

    from app.config import settings as app_settings

    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    profile_id = profile.id if profile is not None else None

    repo = VibeByPhotoRepository(db_session)
    request = await repo.create_request(
        user_id=user.id,
        origin=origin,
        photo_file_ids=file_ids,
        profile_id=profile_id,
    )
    # repo.create_request уже сделал flush — повторно не нужно.

    # 1) Staging-архив (без кнопок).
    username = user.username or ""
    username_display = f"@{_html_escape(username)}" if username else "(нет)"
    staging_caption = texts.STAGING_CAPTION_TEMPLATE.format(
        request_id=request.id,
        user_id=user.id,
        username=username_display,
        origin=origin,
    )
    staging_chat_id = app_settings.media_staging_chat_id
    if staging_chat_id is not None:
        for idx, fid in enumerate(file_ids):
            try:
                await bot.send_photo(
                    chat_id=staging_chat_id,
                    photo=fid,
                    caption=staging_caption if idx == 0 else None,
                )
            except TelegramAPIError as exc:
                logger.warning("vbp: failed to send photo to staging chat: {}", exc)

    # 2) Уведомление модераторам в личку — короткий ping + кнопка «Открыть очередь».
    #    Сам пикер вайбов открывается уже из /admin → 🖼 Вайб по фото; так
    #    модератор не получает 5+ сообщений на каждый запрос и решает, когда
    #    «нырять» в модерацию.
    notified_chat_ids: set[int] = set()
    for admin_tg_id in app_settings.admin_telegram_ids:
        notified_chat_ids.add(admin_tg_id)
    db_moderators = await UserRepository(db_session).list_moderators()
    for moderator in db_moderators:
        notified_chat_ids.add(moderator.telegram_id)

    if not notified_chat_ids:
        logger.warning(
            "vbp: no admins/moderators configured — request {} stays only in DB",
            request.id,
        )

    notification_text = texts.ADMIN_NEW_REQUEST_NOTIFICATION_TEMPLATE.format(
        request_id=request.id,
        user_id=user.id,
        username=username_display,
        origin=origin,
    )
    notification_kb = vibe_by_photo_notification_kb(
        open_queue_text=texts.ADMIN_NEW_REQUEST_BTN_OPEN_QUEUE
    )

    for chat_id in notified_chat_ids:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=notification_text,
                reply_markup=notification_kb,
                parse_mode="HTML",
            )
        # Ловим Exception, а не только TelegramAPIError: один таймаут/сетевой
        # сбой к одному модератору не должен абортить рассылку остальным
        # (и тем более — откатывать уже созданную запись).
        except Exception as exc:
            logger.warning(
                "vbp: failed to notify moderator {} about request {}: {}",
                chat_id,
                request.id,
                exc,
            )

    return request


__all__ = ["dispatch_vbp_request", "router", "send_request_pair"]
