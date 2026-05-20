"""Уведомления администраторам/модераторам.

Шлёт сообщения каждому tg_id из `settings.admin_telegram_ids`. Ошибка
отправки одному админу не блокирует остальных.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from loguru import logger

from app.config import settings
from app.texts import admin_notify as texts

# Telegram ограничивает caption у фото/анимации 1024 символами. Шаблон
# FEED_POST_PENDING_TEMPLATE добавляет ~200 символов служебного текста —
# обрезаем тело поста с запасом.
_FEED_CAPTION_TEXT_LIMIT = 800


async def _broadcast_to_admins(bot: Bot, text: str) -> None:
    """Рассылает текст всем сконфигурированным админам."""
    admin_ids = settings.admin_telegram_ids
    if not admin_ids:
        logger.warning("admin notify skipped: no admins configured")
        return
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except TelegramAPIError as exc:
            logger.error("failed to notify admin {}: {}", admin_id, exc)


async def notify_admins_profile_pending(
    bot: Bot,
    *,
    user_id: int,
    telegram_id: int,
    nickname: str,
) -> None:
    """Уведомляет админов, что анкета пользователя ушла на ручную модерацию медиа."""
    text = texts.PROFILE_PENDING_TEMPLATE.format(
        nickname=nickname,
        user_id=user_id,
        telegram_id=telegram_id,
    )
    await _broadcast_to_admins(bot, text)


async def notify_admins_feed_post_pending(
    bot: Bot,
    *,
    author_name: str,
    telegram_id: int,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
) -> None:
    """Уведомляет админов, что пост Ленты ушёл на премодерацию.

    Шлёт всю карточку: первое фото поста подписью с автором и текстом.
    Если медиа нет — отправляет только текст. Ошибка отправки одному
    админу не блокирует остальных.
    """
    admin_ids = settings.admin_telegram_ids
    if not admin_ids:
        logger.warning("admin notify skipped: no admins configured")
        return

    body = text.strip() if text and text.strip() else "(без текста)"
    if len(body) > _FEED_CAPTION_TEXT_LIMIT:
        body = body[:_FEED_CAPTION_TEXT_LIMIT] + "…"
    caption = texts.FEED_POST_PENDING_TEMPLATE.format(
        author_name=author_name,
        telegram_id=telegram_id,
        text=body,
    )

    for admin_id in admin_ids:
        try:
            if media_file_id and media_type == "gif":
                await bot.send_animation(chat_id=admin_id, animation=media_file_id, caption=caption)
            elif media_file_id:
                await bot.send_photo(chat_id=admin_id, photo=media_file_id, caption=caption)
            else:
                await bot.send_message(chat_id=admin_id, text=caption)
        except TelegramAPIError as exc:
            logger.error("failed to notify admin {} about feed post: {}", admin_id, exc)
