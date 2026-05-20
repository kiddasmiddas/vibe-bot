"""Вспомогательные утилиты для админских хэндлеров."""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from loguru import logger

from app.bot.utils.render_profile import truncate_caption
from app.config import settings as app_settings
from app.db.models.user import User
from app.texts.admin import NOT_ADMIN

# `truncate_caption` живёт в app.bot.utils.render_profile (единый источник
# обрезки подписей медиа); реэкспортируем для обратной совместимости импортов.
__all__ = [
    "ensure_admin",
    "is_admin",
    "is_full_admin",
    "show_screen",
    "truncate_caption",
]


def is_full_admin(user: User) -> bool:
    """Полный администратор — по telegram_id из ADMIN_TELEGRAM_IDS.

    Только полный администратор может назначать и снимать модераторов.
    """
    return user.telegram_id in app_settings.admin_telegram_ids


def is_admin(user: User) -> bool:
    """Доступ к админ-панели: полный администратор ИЛИ модератор.

    Имя историческое — почти вся админка одинаково доступна и админам, и
    модераторам. Для строгой проверки «именно администратор» (управление
    модераторами) использовать `is_full_admin`.
    """
    return is_full_admin(user) or bool(user.is_moderator)


async def ensure_admin(message: Message, user: User) -> bool:
    """Если нет доступа к панели (не админ и не модератор) — игнорирует."""
    if not is_admin(user):
        await message.answer(NOT_ADMIN)
        return False
    return True


async def show_screen(
    message: Message,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    media_file_id: str | None = None,
    media_type: str | None = None,
    parse_mode: str = "HTML",
) -> Message:
    """Рендерит экран администратора, РЕДАКТИРУЯ существующее сообщение на месте.

    Логика переключения типов:
    - Оба сообщения текстовые → edit_text.
    - Оба медиа (и тип совпадает) → edit_media + edit_caption / edit_caption.
    - Тип изменился (текст→медиа, медиа→текст, фото→видео) →
      delete() старого + send нового; aiogram не поддерживает смену типа медиа.

    TelegramBadRequest «message is not modified» подавляется — это нормальная
    ситуация при повторном нажатии кнопки с тем же контентом.

    Возвращает финальный Message (исходный или новый, если пришлось пересылать).

    Параметры
    ---------
    message       : Message — сообщение, которое надо отредактировать.
    text          : str — текст или caption.
    reply_markup  : InlineKeyboardMarkup | None — клавиатура.
    media_file_id : str | None — file_id фото/видео/gif. None = текстовый экран.
    media_type    : str | None — 'photo' | 'video' | 'gif'. Обязателен если media_file_id задан.
    parse_mode    : str — по умолчанию 'HTML'.
    """
    is_media_target = bool(media_file_id and media_type)

    # Определяем, является ли текущее сообщение медиа-сообщением.
    is_media_current = bool(message.photo or message.video or message.animation or message.document)

    try:
        if is_media_target:
            caption = truncate_caption(text)
            assert media_file_id is not None and media_type is not None  # type narrowing
            if media_type == "photo":
                media_input: InputMediaPhoto | InputMediaVideo | InputMediaAnimation = (
                    InputMediaPhoto(media=media_file_id, caption=caption, parse_mode=parse_mode)
                )
            elif media_type == "video":
                media_input = InputMediaVideo(
                    media=media_file_id, caption=caption, parse_mode=parse_mode
                )
            else:  # gif / animation
                media_input = InputMediaAnimation(
                    media=media_file_id, caption=caption, parse_mode=parse_mode
                )

            if is_media_current:
                # Оба медиа — пробуем edit_media (меняет файл + caption сразу).
                try:
                    return await message.edit_media(media_input, reply_markup=reply_markup)
                except TelegramBadRequest as exc:
                    if "message is not modified" in str(exc):
                        return message
                    # Тип медиа изменился или файл недоступен — пересылаем.
                    raise
            else:
                # Текущее текстовое → нужно delete + send.
                raise _TypeSwitchNeeded

        else:
            # Целевой экран текстовый.
            if is_media_current:
                # Текущее медиа → delete + send.
                raise _TypeSwitchNeeded
            # Оба текстовых.
            try:
                return await message.edit_text(
                    text, reply_markup=reply_markup, parse_mode=parse_mode
                )
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return message
                raise

    except _TypeSwitchNeeded:
        pass
    except TelegramBadRequest as exc:
        # «message is not modified» уже обработан выше — сюда долетают реальные
        # ошибки edit (протухший file_id, сообщение слишком старое, смена типа
        # медиа). Логируем перед тем как уйти в fallback delete + send.
        logger.warning("show_screen: edit failed, falling back to delete+send: {}", exc)

    # Fallback: delete + send.
    try:
        await message.delete()
    except TelegramBadRequest:
        pass  # сообщение уже удалено или слишком старое — не критично

    if is_media_target:
        assert media_file_id is not None and media_type is not None
        caption = truncate_caption(text)
        if media_type == "photo":
            return await message.answer_photo(
                media_file_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup
            )
        elif media_type == "video":
            return await message.answer_video(
                media_file_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup
            )
        else:
            return await message.answer_animation(
                media_file_id, caption=caption, parse_mode=parse_mode, reply_markup=reply_markup
            )
    else:
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


class _TypeSwitchNeeded(Exception):
    """Внутренний сигнал: тип сообщения изменился, нужно delete + send."""
