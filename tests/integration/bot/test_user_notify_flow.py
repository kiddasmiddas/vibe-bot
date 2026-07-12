"""Интеграция пуш-уведомлений: notify_like_received / notify_post_commented_bg.

Telegram (Bot) и Redis замоканы, БД настоящая. async_session_factory в фоновом
коммент-пуше подменяется на сессию теста, чтобы видеть незакоммиченные данные.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.utils import user_notify as notify_module
from app.bot.utils.user_notify import notify_like_received, notify_post_commented_bg
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import notifications as texts


class _FakeRedis:
    """In-memory Redis c поддержкой set(nx=True) для окна кулдауна."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value, ex: int | None = None, nx: bool = False):  # type: ignore[no-untyped-def]
        if nx and key in self._store:
            return None
        self._store[key] = str(value)
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        cur = int(self._store.get(key, "0")) + 1
        self._store[key] = str(cur)
        return cur

    async def expire(self, key: str, ttl: int) -> bool:
        return True


@pytest.fixture
def notif_redis(monkeypatch) -> _FakeRedis:  # type: ignore[no-untyped-def]
    redis = _FakeRedis()
    monkeypatch.setattr(notify_module, "get_redis", lambda: redis)
    return redis


def _mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


# --------------------------- лайк-пуши ---------------------------


@pytest.mark.asyncio
async def test_like_push_sent_once_then_throttled(db_session, notif_redis) -> None:
    user = await UserRepository(db_session).create(telegram_id=96001)
    bot = _mock_bot()

    await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")
    await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")

    assert bot.send_message.await_count == 1
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 96001
    assert kwargs["text"] == texts.LIKE_PUSH_ONE
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_like_push_aggregates_after_cooldown(db_session, notif_redis) -> None:
    user = await UserRepository(db_session).create(telegram_id=96002)
    bot = _mock_bot()

    for _ in range(3):
        await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")
    # Кулдаун «истёк» — следующий лайк приносит накопленное.
    notif_redis._store.pop(f"notif:like:cd:{user.id}")
    await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")

    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args.kwargs["text"] == texts.LIKE_PUSH_MANY.format(n=3)


@pytest.mark.asyncio
async def test_superlike_push_bypasses_cooldown_and_escapes(db_session, notif_redis) -> None:
    user = await UserRepository(db_session).create(telegram_id=96003)
    bot = _mock_bot()

    # Обычный лайк занял окно...
    await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")
    # ...суперлайк всё равно пушится, текст экранирован.
    await notify_like_received(
        bot,
        db_session,
        to_user_id=user.id,
        kind="superlike",
        superlike_message="привет <3 & до связи",
    )

    assert bot.send_message.await_count == 2
    text = bot.send_message.await_args.kwargs["text"]
    assert "привет &lt;3 &amp; до связи" in text


@pytest.mark.asyncio
async def test_no_push_for_banned_or_missing_user(db_session, notif_redis) -> None:
    banned = await UserRepository(db_session).create(telegram_id=96004)
    banned.is_banned = True
    await db_session.flush()
    bot = _mock_bot()

    await notify_like_received(bot, db_session, to_user_id=banned.id, kind="like")
    await notify_like_received(bot, db_session, to_user_id=999_999_999, kind="like")

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_push_when_disabled_by_admin(db_session, notif_redis) -> None:
    user = await UserRepository(db_session).create(telegram_id=96005)
    await SettingsRepository(db_session).set("notif_like_cooldown_hours", "0")
    bot = _mock_bot()

    await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_error_does_not_raise(db_session, notif_redis) -> None:
    """Заблокировавший бота получатель (Forbidden) не роняет обработчик лайка."""
    from aiogram.exceptions import TelegramForbiddenError

    user = await UserRepository(db_session).create(telegram_id=96006)
    bot = _mock_bot()
    bot.send_message.side_effect = TelegramForbiddenError(
        method=MagicMock(), message="bot was blocked by the user"
    )

    await notify_like_received(bot, db_session, to_user_id=user.id, kind="like")


# --------------------------- коммент-пуши ---------------------------


@pytest.fixture
def patched_session_factory(db_session, monkeypatch):  # type: ignore[no-untyped-def]
    """Подменяет async_session_factory в user_notify на сессию теста."""

    @asynccontextmanager
    async def _factory():
        yield db_session

    monkeypatch.setattr(notify_module, "async_session_factory", _factory)


async def _make_post(db_session, *, author_tg: int) -> tuple[int, int]:
    """Создаёт автора и активный пост, возвращает (post_id, author_user_id)."""
    from datetime import UTC, datetime, timedelta

    author = await UserRepository(db_session).create(telegram_id=author_tg)
    post = await FeedRepository(db_session).create_post(
        author_user_id=author.id,
        author_name="Автор",
        text="пост",
        status="active",
        published_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=48),
    )
    return post.id, author.id


@pytest.mark.asyncio
async def test_comment_push_sent_to_author(
    db_session, notif_redis, patched_session_factory
) -> None:
    post_id, _ = await _make_post(db_session, author_tg=97001)
    commenter = await UserRepository(db_session).create(telegram_id=97002)
    bot = _mock_bot()

    await notify_post_commented_bg(
        bot,
        post_id=post_id,
        commenter_user_id=commenter.id,
        preview_text="крутой пост <3",
        has_media=False,
    )

    assert bot.send_message.await_count == 1
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 97001
    assert "крутой пост &lt;3" in kwargs["text"]
    assert kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_comment_push_skips_self_comment(
    db_session, notif_redis, patched_session_factory
) -> None:
    post_id, author_id = await _make_post(db_session, author_tg=97003)
    bot = _mock_bot()

    await notify_post_commented_bg(
        bot,
        post_id=post_id,
        commenter_user_id=author_id,
        preview_text="сам себе",
        has_media=False,
    )

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_comment_push_sent_for_every_comment(
    db_session, notif_redis, patched_session_factory
) -> None:
    """Без агрегации: каждый комментарий — отдельный пуш сразу по факту."""
    post_id, _ = await _make_post(db_session, author_tg=97004)
    commenter = await UserRepository(db_session).create(telegram_id=97005)
    bot = _mock_bot()

    for text in ("раз", "два", "три"):
        await notify_post_commented_bg(
            bot,
            post_id=post_id,
            commenter_user_id=commenter.id,
            preview_text=text,
            has_media=False,
        )

    assert bot.send_message.await_count == 3
    assert "три" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_comment_push_disabled_by_toggle(
    db_session, notif_redis, patched_session_factory
) -> None:
    post_id, _ = await _make_post(db_session, author_tg=97008)
    commenter = await UserRepository(db_session).create(telegram_id=97009)
    await SettingsRepository(db_session).set("notif_comment_push_enabled", "0")
    bot = _mock_bot()

    await notify_post_commented_bg(
        bot,
        post_id=post_id,
        commenter_user_id=commenter.id,
        preview_text="тихо",
        has_media=False,
    )

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_comment_push_media_only_preview(
    db_session, notif_redis, patched_session_factory
) -> None:
    post_id, _ = await _make_post(db_session, author_tg=97006)
    commenter = await UserRepository(db_session).create(telegram_id=97007)
    bot = _mock_bot()

    await notify_post_commented_bg(
        bot,
        post_id=post_id,
        commenter_user_id=commenter.id,
        preview_text=None,
        has_media=True,
    )

    assert texts.COMMENT_PREVIEW_MEDIA in bot.send_message.await_args.kwargs["text"]
