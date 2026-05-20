"""Интеграционные тесты раздела «Моя анкета» (этап 3.4).

Хэндлеры зовутся напрямую с MemoryStorage и реальной БД (фикстура `db_session`).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.profile import (
    on_edit_nickname,
    on_my_profile,
    on_profile_edit_dispatch,
)
from app.bot.keyboards.profile_edit import ProfileEditCb
from app.bot.states.profile_edit import ProfileEditStates
from app.db.models.dictionaries import Gender, Vibe
from app.db.models.matching import Like
from app.db.models.profile import Profile
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import profile_edit as texts


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _mock_message(text: str | None = None):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 12345
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    message.bot = bot
    return message


def _mock_bot():
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    return bot


def _mock_callback(user_id: int = 999):
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = _mock_message()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    return cb


async def _seed_profile(db_session, telegram_id: int) -> tuple:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_a = Vibe(
        code=f"pe_va_{telegram_id}",
        title="VA",
        number=11000 + telegram_id,
        image_file_id="a",
    )
    vibe_b = Vibe(
        code=f"pe_vb_{telegram_id}",
        title="VB",
        number=12000 + telegram_id,
        image_file_id="b",
    )
    db_session.add_all([vibe_a, vibe_b])
    await db_session.flush()

    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user.id,
        nickname="OldNick",
        age=22,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=30,
        bio="hi",
        own_vibe_id=vibe_a.id,
        main_media_type="photo",
        main_media_file_id="ph:seed",
    )
    await repo.mark_completed(profile.id)
    await db_session.flush()
    await db_session.refresh(profile)
    return user, profile


@pytest.mark.asyncio
async def test_show_my_profile_renders_card(db_session, storage) -> None:
    user, _profile = await _seed_profile(db_session, telegram_id=80001)
    state = _fsm(storage)
    bot = _mock_bot()
    message = _mock_message()

    await on_my_profile(message, state, user, db_session, bot)

    bot.send_photo.assert_awaited()
    args, kwargs = bot.send_photo.call_args
    caption = kwargs.get("caption") or (args[2] if len(args) >= 3 else "")
    assert "OldNick" in caption
    assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_edit_nickname_updates_db(db_session, storage) -> None:
    user, _profile = await _seed_profile(db_session, telegram_id=80002)
    state = _fsm(storage)
    await state.set_state(ProfileEditStates.edit_nickname)

    bot = _mock_bot()
    message = _mock_message(text="NewName")

    await on_edit_nickname(message, state, user, db_session, bot)

    refreshed = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert refreshed.nickname == "NewName"
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_edit_nickname_with_link_rejected(db_session, storage) -> None:
    user, _profile = await _seed_profile(db_session, telegram_id=80003)
    state = _fsm(storage)
    await state.set_state(ProfileEditStates.edit_nickname)

    bot = _mock_bot()
    message = _mock_message(text="Hello https://evil.com")

    await on_edit_nickname(message, state, user, db_session, bot)

    refreshed = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert refreshed.nickname == "OldNick"
    # state остаётся
    assert await state.get_state() == ProfileEditStates.edit_nickname.state


@pytest.mark.asyncio
async def test_toggle_hidden_flips_value(db_session, storage) -> None:
    user, _profile = await _seed_profile(db_session, telegram_id=80004)
    state = _fsm(storage)
    bot = _mock_bot()
    callback = _mock_callback(user_id=user.id)

    cd = ProfileEditCb(action="toggle_hidden")
    await on_profile_edit_dispatch(callback, cd, state, user, db_session, bot)

    refreshed = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert refreshed.is_hidden is True

    # Второй вызов → False.
    callback2 = _mock_callback(user_id=user.id)
    await on_profile_edit_dispatch(callback2, cd, state, user, db_session, bot)
    await db_session.refresh(refreshed)
    assert refreshed.is_hidden is False


@pytest.mark.asyncio
async def test_delete_flow_confirms_and_wipes(db_session, storage) -> None:
    user, _profile = await _seed_profile(db_session, telegram_id=80005)
    other = await UserRepository(db_session).create(telegram_id=80006)

    # Создадим лайк, чтобы убедиться, что соц-данные сносятся.
    await MatchingRepository(db_session).add_like(user.id, other.id, kind="like")
    await db_session.flush()

    state = _fsm(storage)
    await state.set_state(ProfileEditStates.confirm_delete)

    bot = _mock_bot()
    callback = _mock_callback(user_id=user.id)
    cd = ProfileEditCb(action="confirm_delete")

    user_id = user.id
    await on_profile_edit_dispatch(callback, cd, state, user, db_session, bot)
    await db_session.flush()

    # Профиль удалён.
    profile_after = (
        await db_session.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    assert profile_after is None

    # Лайк удалён.
    likes_after = (await db_session.execute(select(Like).where(Like.from_user_id == user_id))).all()
    assert likes_after == []

    # User НЕ забанен — аккаунт остаётся с пользователем, можно создать анкету заново.
    await db_session.refresh(user)
    assert user.is_banned is False

    # state очищен.
    assert await state.get_state() is None
    # Пользователь увидел сообщение об удалении.
    answered = [c.args[0] for c in callback.message.answer.await_args_list]
    assert texts.PROFILE_DELETED_OK in answered
