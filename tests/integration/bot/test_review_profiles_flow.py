"""Smoke-тесты потока «На проверке → Анкеты» (edit-based карточка с пагинацией).

Проверяет:
1. Вход в раздел (cb_review_profiles) → show_screen вызван с review_profile_card_kb, offset=0.
2. Approve → та же карточка редактируется на следующий профиль (offset тот же, очередь сдвинулась).
3. После одобрения последней анкеты → REVIEW_EMPTY.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.bot.handlers.admin.review import (
    cb_approve_profile_card,
    cb_review_profile_menu,
    cb_review_profile_skip,
    cb_review_profiles,
)
from app.bot.keyboards.admin import AdminReviewProfileCb
from app.db.models.dictionaries import Gender, Vibe
from app.db.models.user import User
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts.admin import REVIEW_EMPTY, REVIEW_MENU

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db_session, telegram_id: int, username: str | None = None) -> User:
    return await UserRepository(db_session).create(telegram_id=telegram_id, username=username)


async def _make_pending_profile(db_session, user_id: int, nickname: str):
    """Создаёт минимальный pending-профиль (is_pending_review=True, is_completed=True)."""
    gender = (await db_session.execute(select(Gender).limit(1))).scalar_one()
    vibe = (await db_session.execute(select(Vibe).limit(1))).scalar_one()
    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user_id,
        nickname=nickname,
        age=22,
        gender_id=gender.id,
        looking_for_age_min=18,
        looking_for_age_max=40,
        bio="bio text",
        own_vibe_id=vibe.id,
        main_media_type="photo",
        main_media_file_id="fake_file_id_" + nickname,
    )
    # Выставляем pending флаги вручную
    await repo.update(profile.id, is_pending_review=True, is_completed=True)
    await db_session.flush()
    await db_session.refresh(profile)
    return profile


def _make_admin_user(telegram_id: int = 111) -> User:
    user = User(telegram_id=telegram_id, username=None, is_banned=False, is_premium=False)
    user.id = telegram_id
    user.is_moderator = False
    return user


def _make_callback(message: MagicMock | None = None) -> AsyncMock:
    cb = AsyncMock()
    cb.message = message or _make_message()
    cb.answer = AsyncMock()
    return cb


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cb_review_profiles_shows_first_card(db_session, monkeypatch) -> None:
    """Вход в раздел → show_screen вызван ровно один раз с review_profile_card_kb, offset=0."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_a = await _make_user(db_session, telegram_id=8001001)
    user_b = await _make_user(db_session, telegram_id=8001002)
    profile_a = await _make_pending_profile(db_session, user_a.id, "PendingAlice")
    _profile_b = await _make_pending_profile(db_session, user_b.id, "PendingBob")

    admin = _make_admin_user(111)
    msg = _make_message()
    callback = _make_callback(msg)

    from app.bot.utils.render_profile import RenderedProfile

    fake_rendered = RenderedProfile(
        text="PendingAlice, 22",
        media_type="photo",
        media_file_id="fake_file_id_PendingAlice",
    )

    with patch(
        "app.bot.handlers.admin.review.build_rendered_profile",
        new=AsyncMock(return_value=fake_rendered),
    ):
        with patch("app.bot.handlers.admin.review.show_screen", new=AsyncMock()) as mock_show:
            await cb_review_profiles(callback=callback, user=admin, db_session=db_session)

    mock_show.assert_awaited_once()
    call_kwargs = mock_show.call_args
    # Первый позиционный аргумент — message
    assert call_kwargs.args[0] is msg
    # reply_markup должна содержать callback с profile_id=profile_a.id и offset=0
    markup = call_kwargs.kwargs.get("reply_markup")
    assert markup is not None
    buttons_flat = [btn for row in markup.inline_keyboard for btn in row]
    # Ищем кнопку approve с profile_id первого профиля
    approve_cb_str = AdminReviewProfileCb(
        action="approve", profile_id=profile_a.id, offset=0
    ).pack()
    cb_values = [btn.callback_data for btn in buttons_flat if btn.callback_data]
    assert approve_cb_str in cb_values, (
        f"Кнопка approve с profile_id={profile_a.id} и offset=0 не найдена: {cb_values}"
    )


def _async_mod_repo_cls() -> type:
    """Возвращает класс-заглушку: конструктор отдаёт AsyncMock (чтобы await работал)."""
    instance = AsyncMock()
    return MagicMock(return_value=instance)


@pytest.mark.asyncio
async def test_cb_approve_shows_next_profile(db_session, monkeypatch) -> None:
    """После одобрения первой анкеты — карточка обновляется на следующую."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)
    monkeypatch.setattr("app.bot.handlers.admin.review.ModerationRepository", _async_mod_repo_cls())

    user_a = await _make_user(db_session, telegram_id=8002001)
    user_b = await _make_user(db_session, telegram_id=8002002)
    profile_a = await _make_pending_profile(db_session, user_a.id, "NextAlice")
    profile_b = await _make_pending_profile(db_session, user_b.id, "NextBob")

    admin = _make_admin_user(111)
    msg = _make_message()
    callback = _make_callback(msg)

    callback_data = AdminReviewProfileCb(action="approve", profile_id=profile_a.id, offset=0)

    from app.bot.utils.render_profile import RenderedProfile

    fake_rendered = RenderedProfile(
        text="NextBob, 22",
        media_type="photo",
        media_file_id="fake_file_id_NextBob",
    )

    with patch(
        "app.bot.handlers.admin.review.build_rendered_profile",
        new=AsyncMock(return_value=fake_rendered),
    ):
        with patch("app.bot.handlers.admin.review.show_screen", new=AsyncMock()) as mock_show:
            await cb_approve_profile_card(
                callback=callback,
                callback_data=callback_data,
                user=admin,
                db_session=db_session,
            )

    # После одобрения profile_a из очереди исчезает, остался profile_b.
    # show_screen должен быть вызван ровно один раз с карточкой profile_b.
    mock_show.assert_awaited_once()
    markup = mock_show.call_args.kwargs.get("reply_markup")
    assert markup is not None
    buttons_flat = [btn for row in markup.inline_keyboard for btn in row]
    approve_cb_str = AdminReviewProfileCb(
        action="approve", profile_id=profile_b.id, offset=0
    ).pack()
    cb_values = [btn.callback_data for btn in buttons_flat if btn.callback_data]
    assert approve_cb_str in cb_values, (
        f"Ожидали approve для profile_b (id={profile_b.id}), получили: {cb_values}"
    )


@pytest.mark.asyncio
async def test_approve_last_profile_shows_empty(db_session, monkeypatch) -> None:
    """После одобрения последней анкеты в очереди показывается экран REVIEW_EMPTY."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)
    monkeypatch.setattr("app.bot.handlers.admin.review.ModerationRepository", _async_mod_repo_cls())

    user_single = await _make_user(db_session, telegram_id=8003001)
    profile_single = await _make_pending_profile(db_session, user_single.id, "OnlyOne")

    admin = _make_admin_user(111)
    msg = _make_message()
    callback = _make_callback(msg)

    callback_data = AdminReviewProfileCb(action="approve", profile_id=profile_single.id, offset=0)

    with patch("app.bot.handlers.admin.review.show_screen", new=AsyncMock()) as mock_show:
        await cb_approve_profile_card(
            callback=callback,
            callback_data=callback_data,
            user=admin,
            db_session=db_session,
        )

    mock_show.assert_awaited_once()
    text_arg = mock_show.call_args.kwargs.get("text")
    assert text_arg == REVIEW_EMPTY, f"Ожидали REVIEW_EMPTY, получили: {text_arg!r}"


@pytest.mark.asyncio
async def test_cb_review_profile_skip_increments_offset(db_session, monkeypatch) -> None:
    """Skip переходит к следующей карточке по offset из callback_data."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    user_a = await _make_user(db_session, telegram_id=8004001)
    user_b = await _make_user(db_session, telegram_id=8004002)
    _profile_a = await _make_pending_profile(db_session, user_a.id, "SkipAlice")
    profile_b = await _make_pending_profile(db_session, user_b.id, "SkipBob")

    admin = _make_admin_user(111)
    msg = _make_message()
    callback = _make_callback(msg)
    # Кнопка Skip уже кодирует offset+1 в callback_data.
    callback_data = AdminReviewProfileCb(action="skip", profile_id=0, offset=1)

    from app.bot.utils.render_profile import RenderedProfile

    fake_rendered = RenderedProfile(
        text="SkipBob, 22",
        media_type="photo",
        media_file_id="fake_file_id_SkipBob",
    )

    with patch(
        "app.bot.handlers.admin.review.build_rendered_profile",
        new=AsyncMock(return_value=fake_rendered),
    ):
        with patch("app.bot.handlers.admin.review.show_screen", new=AsyncMock()) as mock_show:
            await cb_review_profile_skip(
                callback=callback,
                callback_data=callback_data,
                user=admin,
                db_session=db_session,
            )

    mock_show.assert_awaited_once()
    markup = mock_show.call_args.kwargs.get("reply_markup")
    buttons_flat = [btn for row in markup.inline_keyboard for btn in row]
    approve_cb_str = AdminReviewProfileCb(
        action="approve", profile_id=profile_b.id, offset=1
    ).pack()
    cb_values = [btn.callback_data for btn in buttons_flat if btn.callback_data]
    assert approve_cb_str in cb_values, (
        f"Ожидали approve для profile_b (id={profile_b.id}, offset=1), получили: {cb_values}"
    )


@pytest.mark.asyncio
async def test_cb_review_profile_menu_shows_review_menu(monkeypatch) -> None:
    """Кнопка «В меню» возвращает на экран REVIEW_MENU."""
    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111]
    monkeypatch.setattr("app.bot.handlers.admin._helpers.app_settings", fake_settings)

    admin = _make_admin_user(111)
    msg = _make_message()
    callback = _make_callback(msg)

    with patch("app.bot.handlers.admin.review.show_screen", new=AsyncMock()) as mock_show:
        await cb_review_profile_menu(callback=callback, user=admin)

    mock_show.assert_awaited_once()
    text_arg = mock_show.call_args.kwargs.get("text")
    assert text_arg == REVIEW_MENU
