"""Юнит-тесты для уведомлений админам о постах Ленты на премодерации."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError

from app.bot.utils.admin_notify import notify_admins_feed_post_pending
from app.config import settings


@pytest.fixture
def admin_ids(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    ids = [111, 222]
    monkeypatch.setattr(settings, "admin_telegram_ids", ids)
    return ids


async def test_notify_with_photo_sends_card_to_all_admins(admin_ids: list[int]) -> None:
    bot = AsyncMock()
    await notify_admins_feed_post_pending(
        bot,
        author_name="Мира",
        telegram_id=999,
        text="Привет, лента!",
        media_type="photo",
        media_file_id="file_abc",
    )
    assert bot.send_photo.await_count == 2
    for call, admin_id in zip(bot.send_photo.await_args_list, admin_ids, strict=True):
        assert call.kwargs["chat_id"] == admin_id
        assert call.kwargs["photo"] == "file_abc"
        assert "Мира" in call.kwargs["caption"]
        assert "Привет, лента!" in call.kwargs["caption"]
    bot.send_message.assert_not_awaited()
    bot.send_animation.assert_not_awaited()


async def test_notify_with_gif_uses_send_animation(admin_ids: list[int]) -> None:
    bot = AsyncMock()
    await notify_admins_feed_post_pending(
        bot,
        author_name="Юна",
        telegram_id=1,
        text="гифка",
        media_type="gif",
        media_file_id="anim_xyz",
    )
    assert bot.send_animation.await_count == 2
    bot.send_photo.assert_not_awaited()


async def test_notify_without_media_sends_text(admin_ids: list[int]) -> None:
    bot = AsyncMock()
    await notify_admins_feed_post_pending(
        bot,
        author_name="Айка",
        telegram_id=2,
        text="только текст",
        media_type=None,
        media_file_id=None,
    )
    assert bot.send_message.await_count == 2
    bot.send_photo.assert_not_awaited()


async def test_notify_truncates_long_text_within_caption_limit(admin_ids: list[int]) -> None:
    bot = AsyncMock()
    await notify_admins_feed_post_pending(
        bot,
        author_name="X",
        telegram_id=3,
        text="а" * 2000,
        media_type="photo",
        media_file_id="f",
    )
    caption = bot.send_photo.await_args_list[0].kwargs["caption"]
    # Telegram-лимит caption — 1024 символа.
    assert len(caption) <= 1024
    # Обрезается только тело поста, служебный хвост шаблона — на месте.
    assert caption.endswith("одобрить или скрыть.")


async def test_notify_no_admins_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_telegram_ids", [])
    bot = AsyncMock()
    await notify_admins_feed_post_pending(
        bot,
        author_name="X",
        telegram_id=1,
        text="t",
        media_type=None,
        media_file_id=None,
    )
    bot.send_message.assert_not_awaited()
    bot.send_photo.assert_not_awaited()


async def test_notify_one_admin_failure_does_not_block_others(admin_ids: list[int]) -> None:
    bot = AsyncMock()
    bot.send_photo = AsyncMock(side_effect=[TelegramAPIError(method=None, message="boom"), None])
    await notify_admins_feed_post_pending(
        bot,
        author_name="X",
        telegram_id=1,
        text="t",
        media_type="photo",
        media_file_id="f",
    )
    # Несмотря на падение для первого админа — второй всё равно получил пост.
    assert bot.send_photo.await_count == 2
