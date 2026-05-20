"""Интеграционные тесты раздела «Искать своих» (этап 4.2).

Хэндлеры вызываются напрямую с MemoryStorage и реальной БД (фикстура
`db_session`). aiogram-объекты замоканы через MagicMock/AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.matching import (
    on_matching_action,
    on_search,
    on_superlike_message,
)
from app.bot.keyboards.matching import MatchingActionCb
from app.bot.states.matching import MatchingStates
from app.db.models.dictionaries import Gender, Vibe
from app.db.models.matching import Dislike, Like
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import matching as texts


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _mock_message(text: str | None = None) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    # Карусель анкет редактирует/удаляет карточку на месте — мокаем эти методы.
    message.edit_media = AsyncMock()
    message.edit_caption = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    message.delete = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 12345
    message.message_id = 7777
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    message.bot = bot
    return message


def _mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    return bot


def _mock_callback(user_id: int = 999) -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = _mock_message()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    return cb


async def _vibes_pair(db_session, telegram_id: int) -> tuple[Vibe, Vibe]:
    """Создаёт пару уникальных вайбов для теста (number-коллизии — больно)."""
    vibe_a = Vibe(
        code=f"m_va_{telegram_id}",
        title="VA",
        number=20000 + telegram_id,
        image_file_id="a",
    )
    vibe_b = Vibe(
        code=f"m_vb_{telegram_id}",
        title="VB",
        number=21000 + telegram_id,
        image_file_id="b",
    )
    db_session.add_all([vibe_a, vibe_b])
    await db_session.flush()
    return vibe_a, vibe_b


async def _make_compatible_pair(db_session, telegram_id_a: int, telegram_id_b: int):
    """Два пользователя с симметрично совместимыми анкетами (одинаковые vibes,
    одинаковый пол, ищут друг друга)."""
    user_a = await UserRepository(db_session).create(telegram_id=telegram_id_a)
    user_b = await UserRepository(db_session).create(telegram_id=telegram_id_b)

    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_a, _vibe_b = await _vibes_pair(db_session, telegram_id_a)

    repo = ProfileRepository(db_session)
    for user in (user_a, user_b):
        profile = await repo.create(
            user_id=user.id,
            nickname=f"User{user.telegram_id}",
            age=22,
            gender_id=male.id,
            looking_for_age_min=18,
            looking_for_age_max=30,
            bio="hi",
            own_vibe_id=vibe_a.id,
            main_media_type="photo",
            main_media_file_id=f"ph:seed:{user.telegram_id}",
        )
        await repo.set_looking_for_genders(profile.id, [male.id])
        await repo.mark_completed(profile.id)
    await db_session.flush()

    profile_a = await repo.get_by_user_id(user_a.id)
    profile_b = await repo.get_by_user_id(user_b.id)
    return (user_a, profile_a), (user_b, profile_b)


async def _make_single_user_with_profile(db_session, telegram_id: int):
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_a, _vibe_b = await _vibes_pair(db_session, telegram_id)
    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user.id,
        nickname="Solo",
        age=22,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=30,
        bio="alone",
        own_vibe_id=vibe_a.id,
        main_media_type="photo",
        main_media_file_id="ph:solo",
    )
    await repo.set_looking_for_genders(profile.id, [male.id])
    await repo.mark_completed(profile.id)
    await db_session.flush()
    await db_session.refresh(profile)
    return user, profile


# --------------------------- tests ---------------------------


@pytest.mark.asyncio
async def test_search_with_no_profile_shows_message(db_session, storage) -> None:
    user = await UserRepository(db_session).create(telegram_id=90001)
    state = _fsm(storage)
    bot = _mock_bot()
    message = _mock_message()

    await on_search(message, state, user, db_session, bot)

    answered = [call.args[0] for call in message.answer.await_args_list]
    assert texts.NO_PROFILE_YET in answered


@pytest.mark.asyncio
async def test_search_with_no_candidates_shows_message(db_session, storage) -> None:
    user, _profile = await _make_single_user_with_profile(db_session, telegram_id=90002)
    state = _fsm(storage)
    bot = _mock_bot()
    message = _mock_message()

    await on_search(message, state, user, db_session, bot)

    answered = [call.args[0] for call in message.answer.await_args_list]
    assert texts.NO_CANDIDATES in answered


@pytest.mark.asyncio
async def test_like_writes_to_db_and_shows_next(db_session, storage) -> None:
    (user_a, _), (user_b, _) = await _make_compatible_pair(db_session, 90010, 90011)
    state = _fsm(storage)
    bot = _mock_bot()

    callback = _mock_callback(user_id=user_a.id)
    cd = MatchingActionCb(action="like", target_user_id=user_b.id)

    await on_matching_action(callback, cd, state, user_a, db_session, bot)

    likes = list(
        (
            await db_session.execute(
                select(Like).where(Like.from_user_id == user_a.id, Like.to_user_id == user_b.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(likes) == 1
    assert likes[0].kind == "like"


@pytest.mark.asyncio
async def test_dislike_writes_to_db(db_session, storage) -> None:
    (user_a, _), (user_b, _) = await _make_compatible_pair(db_session, 90020, 90021)
    state = _fsm(storage)
    bot = _mock_bot()

    callback = _mock_callback(user_id=user_a.id)
    cd = MatchingActionCb(action="dislike", target_user_id=user_b.id)

    await on_matching_action(callback, cd, state, user_a, db_session, bot)

    dislikes = list(
        (
            await db_session.execute(
                select(Dislike).where(
                    Dislike.from_user_id == user_a.id, Dislike.to_user_id == user_b.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(dislikes) == 1


@pytest.mark.asyncio
async def test_duplicate_like_handled_gracefully(db_session, storage) -> None:
    (user_a, _), (user_b, _) = await _make_compatible_pair(db_session, 90030, 90031)
    state = _fsm(storage)
    bot = _mock_bot()

    cd = MatchingActionCb(action="like", target_user_id=user_b.id)

    callback1 = _mock_callback(user_id=user_a.id)
    await on_matching_action(callback1, cd, state, user_a, db_session, bot)

    # Повторный лайк — UNIQUE-конфликт должен быть проглочен.
    callback2 = _mock_callback(user_id=user_a.id)
    await on_matching_action(callback2, cd, state, user_a, db_session, bot)

    # Запись в БД одна.
    likes = list(
        (
            await db_session.execute(
                select(Like).where(Like.from_user_id == user_a.id, Like.to_user_id == user_b.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(likes) == 1
    # Пользователю не отдали никакой alert-ошибки.
    callback2.answer.assert_awaited()


@pytest.mark.asyncio
async def test_skip_writes_no_decision(db_session, storage) -> None:
    """Скип — не решение: ни лайка, ни дизлайка не пишется.

    Анкета помечается просмотренной (как и при показе) и вернётся в выдачу
    через view_cooldown_days; дизлайк же исключал бы её навсегда.
    """
    (user_a, _), (user_b, _) = await _make_compatible_pair(db_session, 90080, 90081)
    state = _fsm(storage)
    bot = _mock_bot()

    callback = _mock_callback(user_id=user_a.id)
    cd = MatchingActionCb(action="skip", target_user_id=user_b.id)
    await on_matching_action(callback, cd, state, user_a, db_session, bot)

    likes = list(
        (await db_session.execute(select(Like).where(Like.from_user_id == user_a.id)))
        .scalars()
        .all()
    )
    dislikes = list(
        (await db_session.execute(select(Dislike).where(Dislike.from_user_id == user_a.id)))
        .scalars()
        .all()
    )
    assert likes == []
    assert dislikes == []
    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_superlike_message_too_long_repeats_step(db_session, storage) -> None:
    user_a = await UserRepository(db_session).create(telegram_id=90040)
    user_b = await UserRepository(db_session).create(telegram_id=90041)
    state = _fsm(storage)
    await state.set_state(MatchingStates.superlike_message)
    await state.update_data(superlike_target_user_id=user_b.id)

    bot = _mock_bot()
    long_text = "a" * (texts.SUPERLIKE_MESSAGE_MAX_LENGTH + 1)
    message = _mock_message(text=long_text)

    await on_superlike_message(message, state, user_a, db_session, bot)

    answered = [call.args[0] for call in message.answer.await_args_list]
    assert texts.SUPERLIKE_MESSAGE_TOO_LONG in answered
    # state остался.
    assert await state.get_state() == MatchingStates.superlike_message.state
    # Лайков нет.
    likes = list(
        (await db_session.execute(select(Like).where(Like.from_user_id == user_a.id)))
        .scalars()
        .all()
    )
    assert likes == []


@pytest.mark.asyncio
async def test_superlike_with_link_rejected(db_session, storage) -> None:
    user_a = await UserRepository(db_session).create(telegram_id=90050)
    user_b = await UserRepository(db_session).create(telegram_id=90051)
    state = _fsm(storage)
    await state.set_state(MatchingStates.superlike_message)
    await state.update_data(superlike_target_user_id=user_b.id)

    bot = _mock_bot()
    message = _mock_message(text="привет, заходи https://evil.com сюда")

    await on_superlike_message(message, state, user_a, db_session, bot)

    answered = [call.args[0] for call in message.answer.await_args_list]
    assert texts.MODERATION_REJECTED_LINK in answered
    # state остался — пользователь может попробовать ещё раз.
    assert await state.get_state() == MatchingStates.superlike_message.state
    likes = list(
        (await db_session.execute(select(Like).where(Like.from_user_id == user_a.id)))
        .scalars()
        .all()
    )
    assert likes == []


@pytest.mark.asyncio
async def test_complain_action_starts_flow(db_session, storage) -> None:
    """Кнопка 🚩 запускает поток жалобы: state=choosing_reason, спрашивают причину."""
    from app.bot.states.complaints import ComplaintStates
    from app.texts import complaints as complaint_texts

    user_a = await UserRepository(db_session).create(telegram_id=90060)
    user_b = await UserRepository(db_session).create(telegram_id=90061)
    state = _fsm(storage)
    bot = _mock_bot()

    callback = _mock_callback(user_id=user_a.id)
    cd = MatchingActionCb(action="complain", target_user_id=user_b.id)

    await on_matching_action(callback, cd, state, user_a, db_session, bot)

    assert await state.get_state() == ComplaintStates.choosing_reason.state
    answered = [call.args[0] for call in callback.message.answer.await_args_list]
    assert complaint_texts.ASK_REASON in answered
