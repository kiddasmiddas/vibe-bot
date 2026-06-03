"""Smoke-тесты потока «Лента → карточка поста» (edit-based одиночная карточка с пагинацией).

Проверяет:
1. Вход в раздел pending (cb_feed_list_pending) → show_screen вызван 1 раз с feed_review_card_kb.
2. Пост с медиа — show_screen получает media_file_id и media_type.
3. Пост без медиа — show_screen вызван без media_file_id.
4. После hide (action=hide) → show_screen показывает следующий пост или REVIEW_EMPTY.
5. Skip (offset+1) → show_screen вызван с offset=1 для второго поста.
6. Пустая очередь → show_screen с текстом REVIEW_EMPTY.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.admin.feed import (
    cb_feed_list_pending,
    cb_frv_hide,
    cb_frv_skip,
)
from app.bot.keyboards.admin import AdminFeedReviewCb
from app.db.models.user import User
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import REVIEW_EMPTY

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db_session, telegram_id: int) -> User:
    return await UserRepository(db_session).create(telegram_id=telegram_id, username=None)


async def _make_feed_post(
    db_session,
    author_user_id: int,
    *,
    text: str = "Тестовый пост",
    is_pending: bool = True,
) -> object:
    """Создаёт активный пост в ленте."""
    repo = FeedRepository(db_session)
    post = await repo.create_post(
        author_user_id=author_user_id,
        author_name="TestAuthor",
        text=text,
        status="active",
        is_pending_review=is_pending,
    )
    await db_session.flush()
    await db_session.refresh(post)
    return post


async def _add_media(db_session, post_id: int, file_id: str, position: int = 0) -> None:
    repo = FeedRepository(db_session)
    await repo.add_photo(post_id=post_id, file_id=file_id, position=position)
    await db_session.flush()


def _make_admin_user(telegram_id: int = 111) -> User:
    user = User(telegram_id=telegram_id, username=None, is_banned=False, is_premium=False)
    user.id = telegram_id
    user.is_moderator = False
    return user


def _make_message() -> MagicMock:
    msg = MagicMock()
    msg.photo = None
    msg.video = None
    msg.animation = None
    msg.document = None
    msg.edit_text = AsyncMock(return_value=MagicMock())
    msg.edit_media = AsyncMock(return_value=MagicMock())
    msg.answer = AsyncMock(return_value=MagicMock())
    msg.answer_photo = AsyncMock(return_value=MagicMock())
    msg.delete = AsyncMock()
    return msg


def _make_callback(message: MagicMock | None = None) -> AsyncMock:
    cb = AsyncMock()
    cb.message = message or _make_message()
    cb.answer = AsyncMock()
    return cb


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cb_feed_list_pending_shows_first_card_with_media(db_session, monkeypatch) -> None:
    """Вход в раздел pending → show_screen вызван 1 раз с feed_review_card_kb и media_file_id."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_a = await _make_user(db_session, telegram_id=9001001)
    post_a = await _make_feed_post(db_session, user_a.id, text="Пост A с медиа")
    await _add_media(db_session, post_a.id, file_id="fake_photo_file_id", position=0)

    admin = _make_admin_user(111)
    callback = _make_callback()

    with patch("app.bot.handlers.admin.feed.show_screen", new=AsyncMock()) as mock_show:
        await cb_feed_list_pending(callback=callback, user=admin, db_session=db_session)

    mock_show.assert_awaited_once()
    call_kwargs = mock_show.call_args.kwargs
    # Карточка должна показываться с медиа.
    assert call_kwargs.get("media_file_id") == "fake_photo_file_id"
    assert call_kwargs.get("media_type") == "photo"
    assert call_kwargs.get("reply_markup") is not None
    # Для pending-статуса в карточке есть кнопки approve/delete с правильным post_id.
    markup = call_kwargs["reply_markup"]
    buttons_flat = [btn for row in markup.inline_keyboard for btn in row]
    cb_values = [btn.callback_data for btn in buttons_flat if btn.callback_data]
    approve_cb = AdminFeedReviewCb(
        action="approve", post_id=post_a.id, offset=0, status="pending"
    ).pack()
    assert approve_cb in cb_values, f"Кнопка approve с post_id={post_a.id} не найдена: {cb_values}"


@pytest.mark.asyncio
async def test_cb_feed_list_pending_shows_card_without_media(db_session, monkeypatch) -> None:
    """Пост без медиа → show_screen вызван без media_file_id."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_b = await _make_user(db_session, telegram_id=9002001)
    _post_b = await _make_feed_post(db_session, user_b.id, text="Пост без медиа")
    # Медиа НЕ добавляем.

    admin = _make_admin_user(111)
    callback = _make_callback()

    with patch("app.bot.handlers.admin.feed.show_screen", new=AsyncMock()) as mock_show:
        await cb_feed_list_pending(callback=callback, user=admin, db_session=db_session)

    mock_show.assert_awaited_once()
    call_kwargs = mock_show.call_args.kwargs
    # Без медиа.
    assert call_kwargs.get("media_file_id") is None
    assert call_kwargs.get("media_type") is None
    assert call_kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_cb_feed_list_pending_empty_queue(db_session, monkeypatch) -> None:
    """Пустая очередь → show_screen с REVIEW_EMPTY."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    # Не создаём постов.
    admin = _make_admin_user(111)
    callback = _make_callback()

    with patch("app.bot.handlers.admin.feed.show_screen", new=AsyncMock()) as mock_show:
        await cb_feed_list_pending(callback=callback, user=admin, db_session=db_session)

    mock_show.assert_awaited_once()
    text_arg = mock_show.call_args.kwargs.get("text")
    assert text_arg == REVIEW_EMPTY, f"Ожидали REVIEW_EMPTY, получили: {text_arg!r}"


@pytest.mark.asyncio
async def test_cb_frv_hide_advances_to_next_post(db_session, monkeypatch) -> None:
    """После hide текущего поста → show_screen показывает следующий пост."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_a = await _make_user(db_session, telegram_id=9003001)
    user_b = await _make_user(db_session, telegram_id=9003002)
    post_a = await _make_feed_post(db_session, user_a.id, text="Скрыть этот пост")
    post_b = await _make_feed_post(db_session, user_b.id, text="Следующий пост")

    admin = _make_admin_user(111)
    callback = _make_callback()
    callback_data = AdminFeedReviewCb(action="hide", post_id=post_a.id, offset=0, status="pending")

    with patch("app.bot.handlers.admin.feed.show_screen", new=AsyncMock()) as mock_show:
        await cb_frv_hide(
            callback=callback,
            callback_data=callback_data,
            user=admin,
            db_session=db_session,
        )

    # После hide post_a выбывает из pending-выборки. show_screen должен показать post_b.
    mock_show.assert_awaited_once()
    markup = mock_show.call_args.kwargs.get("reply_markup")
    assert markup is not None
    buttons_flat = [btn for row in markup.inline_keyboard for btn in row]
    cb_values = [btn.callback_data for btn in buttons_flat if btn.callback_data]
    approve_b_cb = AdminFeedReviewCb(
        action="approve", post_id=post_b.id, offset=0, status="pending"
    ).pack()
    assert approve_b_cb in cb_values, (
        f"Ожидали карточку post_b (id={post_b.id}), получили кнопки: {cb_values}"
    )


@pytest.mark.asyncio
async def test_cb_frv_hide_last_post_shows_empty(db_session, monkeypatch) -> None:
    """После hide последнего поста → REVIEW_EMPTY."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_only = await _make_user(db_session, telegram_id=9004001)
    post_only = await _make_feed_post(db_session, user_only.id, text="Единственный пост")

    admin = _make_admin_user(111)
    callback = _make_callback()
    callback_data = AdminFeedReviewCb(
        action="hide", post_id=post_only.id, offset=0, status="pending"
    )

    with patch("app.bot.handlers.admin.feed.show_screen", new=AsyncMock()) as mock_show:
        await cb_frv_hide(
            callback=callback,
            callback_data=callback_data,
            user=admin,
            db_session=db_session,
        )

    mock_show.assert_awaited_once()
    text_arg = mock_show.call_args.kwargs.get("text")
    assert text_arg == REVIEW_EMPTY, f"Ожидали REVIEW_EMPTY, получили: {text_arg!r}"


@pytest.mark.asyncio
async def test_cb_frv_skip_goes_to_offset_plus_one(db_session, monkeypatch) -> None:
    """Skip → show_screen рендерит второй пост (offset=1)."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_a = await _make_user(db_session, telegram_id=9005001)
    user_b = await _make_user(db_session, telegram_id=9005002)
    _post_a = await _make_feed_post(db_session, user_a.id, text="Первый пост")
    post_b = await _make_feed_post(db_session, user_b.id, text="Второй пост")

    admin = _make_admin_user(111)
    callback = _make_callback()
    # Кнопка Skip уже кодирует offset+1 в callback_data и текущий post_id.
    callback_data = AdminFeedReviewCb(action="skip", post_id=_post_a.id, offset=1, status="pending")

    with patch("app.bot.handlers.admin.feed.show_screen", new=AsyncMock()) as mock_show:
        await cb_frv_skip(
            callback=callback,
            callback_data=callback_data,
            user=admin,
            db_session=db_session,
        )

    mock_show.assert_awaited_once()
    markup = mock_show.call_args.kwargs.get("reply_markup")
    assert markup is not None
    buttons_flat = [btn for row in markup.inline_keyboard for btn in row]
    cb_values = [btn.callback_data for btn in buttons_flat if btn.callback_data]
    approve_b_cb = AdminFeedReviewCb(
        action="approve", post_id=post_b.id, offset=1, status="pending"
    ).pack()
    assert approve_b_cb in cb_values, (
        f"Ожидали карточку post_b (id={post_b.id}, offset=1), получили: {cb_values}"
    )
