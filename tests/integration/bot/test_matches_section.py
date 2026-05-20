"""Интеграционные тесты раздела «Мои лайки / мэтчи» (этап 4.3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.matches import (
    IncomingLikeActionCb,
    MatchPageCb,
    cb_incoming_like_action,
    cb_match_page,
    on_my_likes_matches,
)
from app.db.models.dictionaries import Gender, Vibe
from app.db.models.matching import Match
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import matching as texts


def _mock_message() -> MagicMock:
    message = MagicMock()
    message.answer = AsyncMock()
    message.edit_media = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    message.delete = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 11111
    message.message_id = 22222
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    bot.send_message = AsyncMock()
    message.bot = bot
    return message


def _mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


def _mock_callback() -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = _mock_message()
    return cb


async def _vibes_pair(db_session, telegram_id: int) -> tuple[Vibe, Vibe]:
    vibe_a = Vibe(
        code=f"ms43_va_{telegram_id}",
        title="VA",
        number=70000 + telegram_id,
        image_file_id="a",
    )
    vibe_b = Vibe(
        code=f"ms43_vb_{telegram_id}",
        title="VB",
        number=71000 + telegram_id,
        image_file_id="b",
    )
    db_session.add_all([vibe_a, vibe_b])
    await db_session.flush()
    return vibe_a, vibe_b


async def _make_user_with_profile(db_session, telegram_id: int):
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_a, _vibe_b = await _vibes_pair(db_session, telegram_id)
    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user.id,
        nickname=f"User{telegram_id}",
        age=22,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=30,
        bio="hi",
        own_vibe_id=vibe_a.id,
        main_media_type="photo",
        main_media_file_id=f"ph:{telegram_id}",
    )
    await repo.set_looking_for_genders(profile.id, [male.id])
    await repo.mark_completed(profile.id)
    await db_session.flush()
    return user, profile


@pytest.mark.asyncio
async def test_my_likes_matches_no_profile(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=70001)
    message = _mock_message()
    await on_my_likes_matches(message, user, db_session)
    answered = [call.args[0] for call in message.answer.await_args_list]
    assert texts.NO_PROFILE_YET in answered


@pytest.mark.asyncio
async def test_my_likes_matches_menu_renders_counts(db_session) -> None:
    me, _ = await _make_user_with_profile(db_session, telegram_id=70010)
    liker_a, _ = await _make_user_with_profile(db_session, telegram_id=70011)
    liker_b, _ = await _make_user_with_profile(db_session, telegram_id=70012)
    matched_user, _ = await _make_user_with_profile(db_session, telegram_id=70013)

    # 2 входящих лайка
    repo = MatchingRepository(db_session)
    await repo.add_like(from_user_id=liker_a.id, to_user_id=me.id, kind="like")
    await repo.add_like(from_user_id=liker_b.id, to_user_id=me.id, kind="like")
    # 1 мэтч
    await repo.create_match(user_a_id=me.id, user_b_id=matched_user.id)
    await db_session.flush()

    message = _mock_message()
    await on_my_likes_matches(message, me, db_session)

    # Кнопки в reply_markup отражают (2) и (1).
    last_call = message.answer.await_args_list[-1]
    kb = last_call.kwargs["reply_markup"]
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("(2)" in t for t in button_texts)
    assert any("(1)" in t for t in button_texts)


@pytest.mark.asyncio
async def test_like_back_creates_match(db_session) -> None:
    me, _ = await _make_user_with_profile(db_session, telegram_id=70020)
    liker, _ = await _make_user_with_profile(db_session, telegram_id=70021)

    repo = MatchingRepository(db_session)
    await repo.add_like(from_user_id=liker.id, to_user_id=me.id, kind="like")
    await db_session.flush()

    bot = _mock_bot()
    callback = _mock_callback()
    cd = IncomingLikeActionCb(action="like_back", liker_user_id=liker.id, index=0)
    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=me.id, user_id=me.id))
    await cb_incoming_like_action(callback, cd, state, me, db_session, bot)

    matches = list((await db_session.execute(select(Match))).scalars().all())
    pair = sorted([me.id, liker.id])
    found = [m for m in matches if m.user_a_id == pair[0] and m.user_b_id == pair[1]]
    assert len(found) == 1
    # Уведомления отправлены обоим (через bot.send_message).
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_incoming_like_next_edits_card_in_place(db_session) -> None:
    """Навигация «Дальше» по входящим лайкам редактирует карточку на месте
    (`edit_media`), а не шлёт новое сообщение."""
    me, _ = await _make_user_with_profile(db_session, telegram_id=70030)
    liker_a, _ = await _make_user_with_profile(db_session, telegram_id=70031)
    liker_b, _ = await _make_user_with_profile(db_session, telegram_id=70032)

    repo = MatchingRepository(db_session)
    await repo.add_like(from_user_id=liker_a.id, to_user_id=me.id, kind="like")
    await repo.add_like(from_user_id=liker_b.id, to_user_id=me.id, kind="like")
    await db_session.flush()

    bot = _mock_bot()
    callback = _mock_callback()
    cd = IncomingLikeActionCb(action="next", liker_user_id=liker_a.id, index=0)
    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=me.id, user_id=me.id))
    await cb_incoming_like_action(callback, cd, state, me, db_session, bot)

    callback.message.edit_media.assert_awaited_once()
    callback.message.bot.send_photo.assert_not_awaited()


@pytest.mark.asyncio
async def test_match_next_edits_card_in_place(db_session) -> None:
    """Навигация «Дальше» по мэтчам редактирует карточку на месте."""
    me, _ = await _make_user_with_profile(db_session, telegram_id=70040)
    m1, _ = await _make_user_with_profile(db_session, telegram_id=70041)
    m2, _ = await _make_user_with_profile(db_session, telegram_id=70042)

    repo = MatchingRepository(db_session)
    await repo.create_match(user_a_id=me.id, user_b_id=m1.id)
    await repo.create_match(user_a_id=me.id, user_b_id=m2.id)
    await db_session.flush()

    bot = _mock_bot()
    callback = _mock_callback()
    cd = MatchPageCb(action="next", index=0)
    await cb_match_page(callback, cd, me, db_session, bot)

    callback.message.edit_media.assert_awaited_once()
    bot.send_photo.assert_not_awaited()
