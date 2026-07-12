"""Пуш-уведомления пользователям: лайки анкеты и комментарии к постам Ленты.

Отправка — только после решения `NotificationThrottle` (агрегация с кулдауном,
fail-open при недоступном Redis). Любая ошибка отправки логируется и не
прерывает основной сценарий: пуш — побочный эффект, не транзакция.

`notify_post_commented_bg` запускается из API-процесса fire-and-forget
(`spawn_notify_post_commented`), поэтому открывает СВОЮ сессию БД — сессия
запроса к моменту выполнения фоновой задачи уже закрыта.
"""

from __future__ import annotations

import asyncio
from html import escape as _html_escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.matching import MatchesMenuCb
from app.cache import get_redis
from app.config import settings
from app.db.base import async_session_factory
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.notification_service import NotificationThrottle
from app.texts import notifications as texts

_COMMENT_PREVIEW_MAX = 80


def _build_throttle(db_session: AsyncSession) -> NotificationThrottle:
    # SettingsRepository без redis — DB-direct: сбой Redis не ломает чтение
    # настроек, а правки админа применяются без ожидания TTL кэша.
    return NotificationThrottle(settings_repo=SettingsRepository(db_session), redis=get_redis())


def _view_likes_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_VIEW_LIKES, callback_data=MatchesMenuCb(section="incoming"))
    return builder.as_markup()


async def notify_like_received(
    bot: Bot,
    db_session: AsyncSession,
    *,
    to_user_id: int,
    kind: str,
    superlike_message: str | None = None,
) -> None:
    """Пуш получателю лайка. Вызывать ТОЛЬКО когда мэтча не случилось.

    При мэтче уходит мэтч-уведомление (`_send_match_notifications`) —
    дублировать его лайк-пушем нельзя.
    """
    user = await UserRepository(db_session).get_by_id(to_user_id)
    if user is None or user.is_banned:
        return

    throttle = _build_throttle(db_session)
    if kind == "superlike":
        if not await throttle.register_superlike(to_user_id):
            return
        # Текст суперлайка прошёл контент-модерацию до записи лайка,
        # но экранируем как любой пользовательский ввод (parse_mode=HTML).
        if superlike_message:
            text = texts.SUPERLIKE_PUSH_WITH_MESSAGE.format(message=_html_escape(superlike_message))
        else:
            text = texts.SUPERLIKE_PUSH
    else:
        pushed_count = await throttle.register_like(to_user_id)
        if pushed_count is None:
            return
        if pushed_count == 1:
            text = texts.LIKE_PUSH_ONE
        else:
            text = texts.LIKE_PUSH_MANY.format(n=pushed_count)

    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=text,
            reply_markup=_view_likes_kb(),
        )
    except TelegramAPIError as exc:
        logger.warning("like push to user_id={} failed: {}", to_user_id, exc)


def _open_post_kb(post_id: int) -> InlineKeyboardMarkup | None:
    """web_app-кнопка на страницу поста в Mini App; без MINIAPP_URL кнопки нет."""
    base = settings.miniapp_url.rstrip("/")
    if not base:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_OPEN_POST, web_app=WebAppInfo(url=f"{base}/feed/{post_id}"))
    return builder.as_markup()


async def notify_post_commented_bg(
    bot: Bot,
    *,
    post_id: int,
    commenter_user_id: int,
    preview_text: str | None,
    has_media: bool,
) -> None:
    """Фоновый пуш автору поста о новом комментарии (вызов из API-процесса).

    Без агрегации: один пуш на каждый комментарий сразу по факту
    (решение клиента 2026-07; выключается тумблером в /admin → Уведомления).
    """
    try:
        async with async_session_factory() as session:
            post = await FeedRepository(session).get_by_id(post_id)
            if post is None or post.author_user_id is None:
                return
            if post.author_user_id == commenter_user_id:
                return
            author = await UserRepository(session).get_by_id(post.author_user_id)
            if author is None or author.is_banned:
                return
            author_chat_id = author.telegram_id
            if not await _build_throttle(session).comments_enabled():
                return

        preview = (preview_text or "").strip() or (texts.COMMENT_PREVIEW_MEDIA if has_media else "")
        if len(preview) > _COMMENT_PREVIEW_MAX:
            preview = preview[: _COMMENT_PREVIEW_MAX - 1] + "…"
        text = texts.COMMENT_PUSH_ONE.format(preview=_html_escape(preview))

        # У API-шного Bot нет DefaultBotProperties → parse_mode задаём явно,
        # иначе экранированные сущности уйдут пользователю литералом.
        await bot.send_message(
            chat_id=author_chat_id,
            text=text,
            reply_markup=_open_post_kb(post_id),
            parse_mode="HTML",
        )
    except TelegramAPIError as exc:
        logger.warning("comment push for post_id={} failed: {}", post_id, exc)
    except Exception as exc:
        logger.error("comment push for post_id={} crashed: {}", post_id, exc)


# Сильные ссылки на фоновые таски: без них asyncio может собрать таску GC
# до завершения (https://docs.python.org/3/library/asyncio-task.html#creating-tasks).
_bg_tasks: set[asyncio.Task[None]] = set()


def spawn_notify_post_commented(
    bot: Bot,
    *,
    post_id: int,
    commenter_user_id: int,
    preview_text: str | None,
    has_media: bool,
) -> None:
    """Fire-and-forget обёртка для вызова из API-хэндлера (ответ не ждёт пуша)."""
    task = asyncio.create_task(
        notify_post_commented_bg(
            bot,
            post_id=post_id,
            commenter_user_id=commenter_user_id,
            preview_text=preview_text,
            has_media=has_media,
        )
    )
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
