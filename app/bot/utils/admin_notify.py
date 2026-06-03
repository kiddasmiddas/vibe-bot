"""Уведомления администраторам/модераторам.

Шлёт сообщения каждому tg_id из `settings.admin_telegram_ids`, а также всем
активным модераторам из БД (если передана db_session). Ошибка отправки одному
получателю не блокирует остальных.
"""

from __future__ import annotations

from html import escape as _html_escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.user_repo import UserRepository
from app.texts import admin_notify as texts

# Telegram ограничивает caption у фото/анимации 1024 символами. Шаблон
# FEED_POST_PENDING_TEMPLATE добавляет ~200 символов служебного текста —
# обрезаем тело поста с запасом.
_FEED_CAPTION_TEXT_LIMIT = 800


async def _collect_recipient_ids(db_session: AsyncSession | None) -> set[int]:
    """Возвращает объединённый набор telegram_id для рассылки.

    Всегда включает env-список admin_telegram_ids. Если передана db_session —
    добавляет telegram_id всех активных (не забаненных) модераторов из БД.
    Дубликаты устраняются через set, поэтому пользователь-администратор,
    одновременно являющийся модератором, получает только одно сообщение.
    """
    recipient_ids: set[int] = set(settings.admin_telegram_ids)
    if db_session is not None:
        moderators = await UserRepository(db_session).list_moderators()
        for mod in moderators:
            recipient_ids.add(mod.telegram_id)
    return recipient_ids


async def _broadcast_to_admins(
    bot: Bot,
    text: str,
    *,
    db_session: AsyncSession | None = None,
) -> None:
    """Рассылает текст всем администраторам и (если db_session передана) модераторам."""
    recipient_ids = await _collect_recipient_ids(db_session)
    if not recipient_ids:
        logger.warning("admin notify skipped: no admins or moderators configured")
        return
    for admin_id in recipient_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except TelegramAPIError as exc:
            logger.error("failed to notify admin/moderator {}: {}", admin_id, exc)


async def notify_admins_profile_pending(
    bot: Bot,
    *,
    user_id: int,
    telegram_id: int,
    nickname: str,
    db_session: AsyncSession | None = None,
) -> None:
    """Уведомляет админов и модераторов, что анкета ушла на ручную модерацию медиа."""
    # User-supplied nickname экранируется — Bot работает с parse_mode=HTML
    # по умолчанию (см. DefaultBotProperties в main.py).
    text = texts.PROFILE_PENDING_TEMPLATE.format(
        nickname=_html_escape(nickname),
        user_id=user_id,
        telegram_id=telegram_id,
    )
    await _broadcast_to_admins(bot, text, db_session=db_session)


async def notify_admins_feed_post_pending(
    bot: Bot,
    *,
    author_name: str,
    telegram_id: int,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
    db_session: AsyncSession | None = None,
) -> None:
    """Уведомляет админов и модераторов, что пост Ленты ушёл на премодерацию.

    Шлёт всю карточку: первое фото поста с подписью (автор + текст).
    Если медиа нет — отправляет только текст. Ошибка отправки одному
    получателю не блокирует остальных.
    """
    recipient_ids = await _collect_recipient_ids(db_session)
    if not recipient_ids:
        logger.warning("admin notify skipped: no admins or moderators configured")
        return

    body = text.strip() if text and text.strip() else "(без текста)"
    if len(body) > _FEED_CAPTION_TEXT_LIMIT:
        body = body[:_FEED_CAPTION_TEXT_LIMIT] + "…"
    # User-supplied author_name и body экранируются — Bot работает с parse_mode=HTML
    # по умолчанию (см. DefaultBotProperties в main.py).
    caption = texts.FEED_POST_PENDING_TEMPLATE.format(
        author_name=_html_escape(author_name),
        telegram_id=telegram_id,
        text=_html_escape(body),
    )

    for admin_id in recipient_ids:
        try:
            if media_file_id and media_type == "gif":
                await bot.send_animation(chat_id=admin_id, animation=media_file_id, caption=caption)
            elif media_file_id:
                await bot.send_photo(chat_id=admin_id, photo=media_file_id, caption=caption)
            else:
                await bot.send_message(chat_id=admin_id, text=caption)
        except TelegramAPIError as exc:
            logger.error("failed to notify admin/moderator {} about feed post: {}", admin_id, exc)
