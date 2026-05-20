"""Интеграционные тесты финализации регистрации (этап 3.3).

Хэндлеры `on_main_media` / `on_main_media_wrong_type` вызываются напрямую с
MemoryStorage и реальной БД (фикстура `db_session`). NudeNet-модель в dev-окружении
недоступна → ContentModerationService возвращает `manual_review` для photo/gif
и видео всегда уходит в manual_review.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.registration import on_main_media, on_main_media_wrong_type
from app.bot.states.registration import RegistrationStates
from app.db.models.dictionaries import Fandom, Gender, Interest, Vibe
from app.db.models.profile import Profile
from app.db.repositories.user_repo import UserRepository
from app.texts import registration as texts


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _photo_message(file_id: str = "ph:abc") -> MagicMock:
    message = MagicMock()
    message.text = None
    photo_size = MagicMock()
    photo_size.file_id = file_id
    photo_size.file_size = 100_000  # 100 КБ — под лимитом 5 МБ
    message.photo = [photo_size]
    message.video = None
    message.animation = None
    message.answer = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 12345
    message.bot = MagicMock()
    return message


def _video_message(file_id: str = "vid:abc") -> MagicMock:
    message = MagicMock()
    message.text = None
    message.photo = None
    video = MagicMock()
    video.file_id = file_id
    message.video = video
    message.animation = None
    message.answer = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 12345
    message.bot = MagicMock()
    return message


def _text_message(text: str) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.photo = None
    message.video = None
    message.animation = None
    message.answer = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 12345
    message.bot = MagicMock()
    return message


def _mock_bot(image_bytes: bytes = b"\x89PNG\r\n\x1a\nfakepng") -> MagicMock:
    bot = MagicMock()

    async def _download(file_id, destination):  # type: ignore[no-untyped-def]
        destination.write(image_bytes)

    bot.download = AsyncMock(side_effect=_download)
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    bot.send_message = AsyncMock()  # для уведомления админов о pending-анкете
    return bot


async def _seed_state(state: FSMContext, db_session) -> None:
    """Заполняет FSM-data так, как было бы после всех предыдущих шагов."""
    genders = list(
        (await db_session.execute(select(Gender).where(Gender.is_active.is_(True)))).scalars().all()
    )
    fandoms = list(
        (await db_session.execute(select(Fandom).where(Fandom.is_active.is_(True)))).scalars().all()
    )
    interests = list(
        (await db_session.execute(select(Interest).where(Interest.is_active.is_(True))))
        .scalars()
        .all()
    )
    vibes = list(
        (await db_session.execute(select(Vibe).where(Vibe.is_active.is_(True)))).scalars().all()
    )

    assert genders, "seed genders missing"
    assert fandoms, "seed fandoms missing"
    assert vibes, "seed vibes missing"

    await state.update_data(
        nickname="VibeyOne",
        age=22,
        gender_id=genders[0].id,
        looking_for_gender_ids=[g.id for g in genders[:1]],
        la_min=18,
        la_max=30,
        bio="Чай и манга",
        fandom_ids=[fandoms[0].id],
        desired_fandom_ids=[fandoms[0].id],
        interest_ids=[interests[0].id] if interests else [],
        own_vibe_id=vibes[0].id,
        desired_vibe_ids=[vibes[-1].id],
    )


async def _make_user(db_session, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


@pytest.mark.asyncio
async def test_full_registration_flow_creates_profile(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.main_media)
    user = await _make_user(db_session, telegram_id=7001)
    await _seed_state(state, db_session)

    bot = _mock_bot()
    message = _photo_message()

    await on_main_media(message, state, user, db_session, bot)

    # NudeNet недоступен в dev → manual_review → is_pending_review=True.
    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert profile.is_completed is True
    assert profile.is_pending_review is True
    assert profile.main_media_type == "photo"
    assert profile.main_media_file_id == "ph:abc"
    assert profile.nickname == "VibeyOne"

    # state очищен после успешной финализации.
    assert await state.get_state() is None

    # Пользователь увидел сообщение про ручную модерацию.
    answered_texts = [call.args[0] for call in message.answer.await_args_list]
    assert texts.PROFILE_PENDING_REVIEW_OK in answered_texts


@pytest.mark.asyncio
async def test_wrong_type_message_not_finalized(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.main_media)
    user = await _make_user(db_session, telegram_id=7002)
    await _seed_state(state, db_session)

    message = _text_message("просто текст")
    await on_main_media_wrong_type(message)

    message.answer.assert_awaited_once_with(texts.MEDIA_WRONG_TYPE)
    # state остаётся на main_media.
    assert await state.get_state() == RegistrationStates.main_media.state
    # Профиль в БД не создан.
    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one_or_none()
    assert profile is None


@pytest.mark.asyncio
async def test_video_always_pending_review(db_session, storage) -> None:
    state = _fsm(storage)
    await state.set_state(RegistrationStates.main_media)
    user = await _make_user(db_session, telegram_id=7003)
    await _seed_state(state, db_session)

    bot = _mock_bot()
    message = _video_message()

    await on_main_media(message, state, user, db_session, bot)

    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert profile.is_pending_review is True
    assert profile.main_media_type == "video"
    assert profile.main_media_file_id == "vid:abc"
    # bot.download для video не вызывался (видео не качается).
    bot.download.assert_not_awaited()
