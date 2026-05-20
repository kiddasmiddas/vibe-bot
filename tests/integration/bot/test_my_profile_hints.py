"""Интеграционные тесты: подсказка VIBES_NEED_REVIEW_HINT и сброс флага
vibes_need_review после редактирования вайбов.

Сценарии:
- on_my_profile при vibes_need_review=True → message.answer содержит VIBES_NEED_REVIEW_HINT.
- on_my_profile при vibes_need_review=False → VIBES_NEED_REVIEW_HINT НЕ отправляется.
- on_edit_vibe_pick_own (выбор вайба) → set_vibes_need_review(profile.id, False) применяется в БД.
- on_edit_vibe_done_desired (готово) → set_vibes_need_review(profile.id, False) применяется в БД.
- on_edit_vibe_any_desired (любой) → set_vibes_need_review(profile.id, False) применяется в БД.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.profile import (
    on_edit_vibe_any_desired,
    on_edit_vibe_done_desired,
    on_edit_vibe_pick_own,
    on_my_profile,
)
from app.bot.keyboards.registration import VibePickCb
from app.bot.states.profile_edit import ProfileEditStates
from app.db.models.dictionaries import Gender, Vibe
from app.db.models.profile import Profile
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import profile_edit as texts

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _mock_bot():
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


def _mock_message():
    message = MagicMock()
    message.text = None
    message.answer = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 12345
    bot = _mock_bot()
    message.bot = bot
    return message


def _mock_callback(user_id: int = 999):
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = _mock_message()
    cb.message.photo = None
    cb.message.edit_text = AsyncMock()
    cb.message.edit_media = AsyncMock()
    cb.message.delete = AsyncMock()
    cb.message.bot = _mock_bot()
    return cb


async def _seed_profile(
    db_session,
    telegram_id: int,
    *,
    vibes_need_review: bool = False,
) -> tuple:
    """Creates a completed profile with two seed vibes. Returns (user, profile, vibe_a)."""
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()

    # Use large number to avoid collisions with seed data (1..36) or other tests.
    vibe_a = Vibe(
        code=f"mv_va_{telegram_id}",
        title=f"VA{telegram_id}",
        number=20000 + telegram_id,
        image_file_id="file_a",
    )
    db_session.add(vibe_a)
    await db_session.flush()

    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user.id,
        nickname="HintUser",
        age=25,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=35,
        bio="test",
        own_vibe_id=vibe_a.id,
        main_media_type="photo",
        main_media_file_id="ph:hint_seed",
    )
    await repo.mark_completed(profile.id)

    if vibes_need_review:
        await repo.set_vibes_need_review(profile.id, True)

    await db_session.flush()
    await db_session.refresh(profile)
    return user, profile, vibe_a


# ---------------------------------------------------------------------------
# on_my_profile — hint visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_my_profile_sends_vibes_need_review_hint_when_flag_is_true(
    db_session, storage
) -> None:
    user, _profile, _vibe = await _seed_profile(
        db_session, telegram_id=70001, vibes_need_review=True
    )
    bot = _mock_bot()
    message = _mock_message()
    state = _fsm(storage)

    await on_my_profile(message, state, user, db_session, bot)

    answer_texts = [call.args[0] for call in message.answer.await_args_list]
    assert texts.VIBES_NEED_REVIEW_HINT in answer_texts


@pytest.mark.asyncio
async def test_on_my_profile_does_not_send_vibes_need_review_hint_when_flag_is_false(
    db_session, storage
) -> None:
    user, _profile, _vibe = await _seed_profile(
        db_session, telegram_id=70002, vibes_need_review=False
    )
    bot = _mock_bot()
    message = _mock_message()
    state = _fsm(storage)

    await on_my_profile(message, state, user, db_session, bot)

    answer_texts = [call.args[0] for call in message.answer.await_args_list]
    assert texts.VIBES_NEED_REVIEW_HINT not in answer_texts


# ---------------------------------------------------------------------------
# on_edit_vibe_pick_own — clears vibes_need_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_edit_vibe_pick_own_clears_vibes_need_review(db_session, storage) -> None:
    """Выбор вайба в single-select пикере (own) сбрасывает vibes_need_review в False."""
    user, profile, _vibe_a = await _seed_profile(
        db_session, telegram_id=70003, vibes_need_review=True
    )

    # Use a real vibe from seed (number=1, created during DB seed).
    seed_vibe = (await db_session.execute(select(Vibe).where(Vibe.number == 1))).scalar_one()

    state = _fsm(storage)
    await state.set_state(ProfileEditStates.edit_own_vibe)

    callback = _mock_callback(user_id=user.id)
    cb_data = VibePickCb(role="own", page=0, number=seed_vibe.number)

    await on_edit_vibe_pick_own(callback, cb_data, state, user, db_session, _mock_bot())

    refreshed = (
        await db_session.execute(select(Profile).where(Profile.id == profile.id))
    ).scalar_one()
    assert refreshed.vibes_need_review is False


# ---------------------------------------------------------------------------
# on_edit_vibe_done_desired — clears vibes_need_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_edit_vibe_done_desired_clears_vibes_need_review(db_session, storage) -> None:
    """«Готово» в desired_vibe пикере сбрасывает vibes_need_review в False."""
    user, profile, _vibe_a = await _seed_profile(
        db_session, telegram_id=70004, vibes_need_review=True
    )

    seed_vibe = (await db_session.execute(select(Vibe).where(Vibe.number == 1))).scalar_one()

    state = _fsm(storage)
    await state.set_state(ProfileEditStates.edit_desired_vibe)
    # Pre-populate FSM with a valid selection (number must correspond to a real vibe).
    await state.update_data(desired_vibe_numbers=[seed_vibe.number])

    callback = _mock_callback(user_id=user.id)

    await on_edit_vibe_done_desired(callback, state, user, db_session, _mock_bot())

    refreshed = (
        await db_session.execute(select(Profile).where(Profile.id == profile.id))
    ).scalar_one()
    assert refreshed.vibes_need_review is False


# ---------------------------------------------------------------------------
# on_edit_vibe_any_desired — clears vibes_need_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_edit_vibe_any_desired_clears_vibes_need_review(db_session, storage) -> None:
    """«Любой вайб» в desired_vibe пикере сбрасывает vibes_need_review в False."""
    user, profile, _vibe_a = await _seed_profile(
        db_session, telegram_id=70005, vibes_need_review=True
    )

    state = _fsm(storage)
    await state.set_state(ProfileEditStates.edit_desired_vibe)

    callback = _mock_callback(user_id=user.id)

    await on_edit_vibe_any_desired(callback, state, user, db_session, _mock_bot())

    refreshed = (
        await db_session.execute(select(Profile).where(Profile.id == profile.id))
    ).scalar_one()
    assert refreshed.vibes_need_review is False


# ---------------------------------------------------------------------------
# Bonus: after on_edit_vibe_any_desired desired_vibe_ids is empty in DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_edit_vibe_any_desired_clears_desired_vibe_ids(db_session, storage) -> None:
    """«Любой вайб» также очищает desired_vibe_ids, оставляя пустой список."""
    user, profile, _vibe_a = await _seed_profile(
        db_session, telegram_id=70006, vibes_need_review=False
    )
    # Seed some desired vibes first.
    seed_vibe = (await db_session.execute(select(Vibe).where(Vibe.number == 1))).scalar_one()
    await ProfileRepository(db_session).set_desired_vibe_ids(profile.id, [seed_vibe.id])
    await db_session.flush()

    state = _fsm(storage)
    await state.set_state(ProfileEditStates.edit_desired_vibe)
    callback = _mock_callback(user_id=user.id)

    await on_edit_vibe_any_desired(callback, state, user, db_session, _mock_bot())

    ids_after = await ProfileRepository(db_session).get_desired_vibe_ids(profile.id)
    assert ids_after == []
