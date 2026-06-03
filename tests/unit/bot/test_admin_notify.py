"""Юнит-тесты для уведомлений админам/модераторам о постах Ленты и анкетах."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError

from app.bot.utils.admin_notify import (
    _collect_recipient_ids,
    notify_admins_feed_post_pending,
    notify_admins_profile_pending,
)
from app.config import settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_ids(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    ids = [111, 222]
    monkeypatch.setattr(settings, "admin_telegram_ids", ids)
    return ids


def _make_mock_session(moderator_tg_ids: list[int]):
    """Возвращает AsyncMock сессии с заглушкой UserRepository.list_moderators."""
    mods = [SimpleNamespace(telegram_id=tg_id) for tg_id in moderator_tg_ids]
    mock_session = MagicMock()

    async def _list_moderators():
        return mods

    with patch("app.bot.utils.admin_notify.UserRepository") as MockRepo:
        MockRepo.return_value.list_moderators = _list_moderators
        yield mock_session, MockRepo


# ---------------------------------------------------------------------------
# _collect_recipient_ids
# ---------------------------------------------------------------------------


async def test_collect_ids_no_session_returns_env_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без db_session возвращаем только env-список."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [100, 200])
    result = await _collect_recipient_ids(None)
    assert result == {100, 200}


async def test_collect_ids_with_session_merges_moderators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """С db_session — объединяем env-ids и telegram_id модераторов."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [100])
    mods = [SimpleNamespace(telegram_id=300), SimpleNamespace(telegram_id=400)]
    mock_session = MagicMock()

    with patch("app.bot.utils.admin_notify.UserRepository") as MockRepo:
        MockRepo.return_value.list_moderators = AsyncMock(return_value=mods)
        result = await _collect_recipient_ids(mock_session)

    assert result == {100, 300, 400}


async def test_collect_ids_deduplicates_admin_who_is_also_moderator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если admin_telegram_id совпадает с telegram_id модератора — нет дубликата."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [100, 200])
    # Модератор 100 уже есть в env-списке
    mods = [SimpleNamespace(telegram_id=100), SimpleNamespace(telegram_id=300)]
    mock_session = MagicMock()

    with patch("app.bot.utils.admin_notify.UserRepository") as MockRepo:
        MockRepo.return_value.list_moderators = AsyncMock(return_value=mods)
        result = await _collect_recipient_ids(mock_session)

    assert result == {100, 200, 300}
    assert len(result) == 3  # не 4 — дубликат 100 схлопнулся


# ---------------------------------------------------------------------------
# notify_admins_feed_post_pending — без db_session (старое поведение)
# ---------------------------------------------------------------------------


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
    sent_ids = {c.kwargs["chat_id"] for c in bot.send_photo.await_args_list}
    assert sent_ids == set(admin_ids)
    for call in bot.send_photo.await_args_list:
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
    # Несмотря на падение для первого — второй всё равно получил пост.
    assert bot.send_photo.await_count == 2


# ---------------------------------------------------------------------------
# notify_admins_feed_post_pending — с db_session (новое поведение с модераторами)
# ---------------------------------------------------------------------------


async def test_feed_notify_with_moderators_sends_to_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если в БД есть 2 модератора, сообщение уходит и админам, и модераторам."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [111])
    mods = [SimpleNamespace(telegram_id=333), SimpleNamespace(telegram_id=444)]
    mock_session = MagicMock()
    bot = AsyncMock()

    with patch("app.bot.utils.admin_notify.UserRepository") as MockRepo:
        MockRepo.return_value.list_moderators = AsyncMock(return_value=mods)
        await notify_admins_feed_post_pending(
            bot,
            author_name="Автор",
            telegram_id=10,
            text="текст",
            media_type=None,
            media_file_id=None,
            db_session=mock_session,
        )

    # 1 admin + 2 модератора = 3 сообщения
    assert bot.send_message.await_count == 3
    sent_ids = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
    assert sent_ids == {111, 333, 444}


async def test_feed_notify_admin_is_also_moderator_no_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пользователь одновременно admin и moderator получает ровно одно сообщение."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [111, 222])
    # 111 — одновременно модератор
    mods = [SimpleNamespace(telegram_id=111)]
    mock_session = MagicMock()
    bot = AsyncMock()

    with patch("app.bot.utils.admin_notify.UserRepository") as MockRepo:
        MockRepo.return_value.list_moderators = AsyncMock(return_value=mods)
        await notify_admins_feed_post_pending(
            bot,
            author_name="Автор",
            telegram_id=10,
            text="текст",
            media_type=None,
            media_file_id=None,
            db_session=mock_session,
        )

    # 111 + 222 = 2, не 3
    assert bot.send_message.await_count == 2
    sent_ids = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
    assert sent_ids == {111, 222}


# ---------------------------------------------------------------------------
# notify_admins_profile_pending
# ---------------------------------------------------------------------------


async def test_profile_pending_sends_to_env_admins(admin_ids: list[int]) -> None:
    bot = AsyncMock()
    await notify_admins_profile_pending(
        bot,
        user_id=42,
        telegram_id=9000,
        nickname="Тестик",
    )
    assert bot.send_message.await_count == 2
    sent_ids = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
    assert sent_ids == set(admin_ids)
    for call in bot.send_message.await_args_list:
        assert "Тестик" in call.kwargs["text"]


async def test_profile_pending_includes_moderators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """С db_session уведомление уходит и модераторам."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [111])
    mods = [SimpleNamespace(telegram_id=555)]
    mock_session = MagicMock()
    bot = AsyncMock()

    with patch("app.bot.utils.admin_notify.UserRepository") as MockRepo:
        MockRepo.return_value.list_moderators = AsyncMock(return_value=mods)
        await notify_admins_profile_pending(
            bot,
            user_id=1,
            telegram_id=100,
            nickname="Ника",
            db_session=mock_session,
        )

    assert bot.send_message.await_count == 2
    sent_ids = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
    assert sent_ids == {111, 555}


async def test_profile_pending_no_admins_no_session_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "admin_telegram_ids", [])
    bot = AsyncMock()
    await notify_admins_profile_pending(bot, user_id=1, telegram_id=1, nickname="X")
    bot.send_message.assert_not_awaited()
