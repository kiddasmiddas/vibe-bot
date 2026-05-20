"""Интеграционные тесты Premium-фич в анкете: музыка и кружок (Этап 8).

Хэндлеры вызываются напрямую с MemoryStorage и реальной тестовой БД.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.profile import (
    on_music_received,
    on_music_wrong_type,
    on_profile_edit_dispatch,
    on_video_note_got_video,
    on_video_note_received,
    on_video_note_wrong_type,
)
from app.bot.keyboards.profile_edit import ProfileEditCb
from app.bot.states.profile_edit import ProfileEditStates
from app.bot.utils.render_profile import send_premium_media
from app.db.models.dictionaries import Gender, Vibe
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import premium_media as pm_texts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _fsm(storage: MemoryStorage, user_id: int = 1) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_animation = AsyncMock()
    bot.send_audio = AsyncMock()
    bot.send_video_note = AsyncMock()
    return bot


def _mock_message(
    *,
    audio_file_id: str | None = None,
    video_note_file_id: str | None = None,
    has_video: bool = False,
    text: str | None = "some text",
) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.answer = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = 9999

    if audio_file_id is not None:
        audio = MagicMock()
        audio.file_id = audio_file_id
        msg.audio = audio
        msg.video_note = None
        msg.video = None
        msg.photo = None
    elif video_note_file_id is not None:
        vn = MagicMock()
        vn.file_id = video_note_file_id
        msg.video_note = vn
        msg.audio = None
        msg.video = None
        msg.photo = None
    elif has_video:
        video = MagicMock()
        video.file_id = "video:123"
        msg.video = video
        msg.video_note = None
        msg.audio = None
        msg.photo = None
    else:
        msg.audio = None
        msg.video_note = None
        msg.video = None
        msg.photo = None

    return msg


def _mock_callback(action: str, user_id: int = 1) -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = _mock_message(audio_file_id=None)
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.data = ProfileEditCb(action=action).pack()
    return cb


async def _seed_profile(
    db_session,
    *,
    telegram_id: int,
    is_premium: bool = False,
    music_file_id: str | None = None,
    video_note_file_id: str | None = None,
) -> tuple:
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    if is_premium:
        until = datetime.now(tz=UTC) + timedelta(days=30)
        await UserRepository(db_session).update_premium(
            user.id, is_premium=True, premium_until=until
        )
        await db_session.flush()
        await db_session.refresh(user)

    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_a = Vibe(
        code=f"pm_va_{telegram_id}",
        title="VA",
        number=50000 + telegram_id,
        image_file_id="a",
    )
    vibe_b = Vibe(
        code=f"pm_vb_{telegram_id}",
        title="VB",
        number=51000 + telegram_id,
        image_file_id="b",
    )
    db_session.add_all([vibe_a, vibe_b])
    await db_session.flush()

    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user.id,
        nickname="TestUser",
        age=25,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=35,
        bio="bio text",
        own_vibe_id=vibe_a.id,
        main_media_type="photo",
        main_media_file_id="ph:test",
        music_file_id=music_file_id,
        video_note_file_id=video_note_file_id,
    )
    await repo.mark_completed(profile.id)
    await db_session.flush()
    await db_session.refresh(profile)
    return user, profile


# ---------------------------------------------------------------------------
# Premium gate: add_music
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_music_non_premium_shows_need_premium(db_session, storage) -> None:
    """Не-premium юзер нажимает «Добавить музыку» — show_alert NEED_PREMIUM, FSM не активирован."""
    user, _profile = await _seed_profile(db_session, telegram_id=91001, is_premium=False)
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("add_music", user_id=user.id)
    cb_data = ProfileEditCb(action="add_music")

    await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    callback.answer.assert_awaited_once_with(pm_texts.NEED_PREMIUM, show_alert=True)
    current = await state.get_state()
    assert current is None


@pytest.mark.asyncio
async def test_add_music_premium_activates_fsm(db_session, storage) -> None:
    """Premium юзер нажимает «Добавить музыку» — FSM в waiting_music, инструкция выведена."""
    user, _profile = await _seed_profile(db_session, telegram_id=91002, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("add_music", user_id=user.id)
    cb_data = ProfileEditCb(action="add_music")

    await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    current = await state.get_state()
    assert current == ProfileEditStates.waiting_music.state
    callback.message.answer.assert_awaited_once()
    text_sent = callback.message.answer.call_args.args[0]
    assert "TgSoundBot" in text_sent


# ---------------------------------------------------------------------------
# waiting_music: wrong type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_music_wrong_type_shows_waiting_audio(db_session, storage) -> None:
    """В состоянии waiting_music присылает текст → ответ содержит MUSIC_WAITING_AUDIO."""
    user, _profile = await _seed_profile(db_session, telegram_id=91003, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    await state.set_state(ProfileEditStates.waiting_music)

    message = _mock_message(text="some text")

    await on_music_wrong_type(message)

    message.answer.assert_awaited_once_with(pm_texts.MUSIC_WAITING_AUDIO)


# ---------------------------------------------------------------------------
# waiting_music: audio received
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_music_received_saves_file_id(db_session, storage) -> None:
    """Premium юзер в waiting_music присылает audio → file_id сохранён, FSM сброшен."""
    user, profile = await _seed_profile(db_session, telegram_id=91004, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    await state.set_state(ProfileEditStates.waiting_music)
    bot = _mock_bot()
    message = _mock_message(audio_file_id="audio:xyz")

    with patch("app.bot.handlers.profile.send_premium_media", new_callable=AsyncMock):
        await on_music_received(message, state, user, db_session, bot)

    current = await state.get_state()
    assert current is None

    await db_session.refresh(profile)
    assert profile.music_file_id == "audio:xyz"
    message.answer.assert_awaited()
    texts_sent = [call.args[0] for call in message.answer.call_args_list]
    assert any(pm_texts.MUSIC_SAVED in t for t in texts_sent)


# ---------------------------------------------------------------------------
# Remove music
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_music_clears_field(db_session, storage) -> None:
    """Premium юзер нажимает «Убрать музыку» → поле music_file_id = None."""
    user, profile = await _seed_profile(
        db_session, telegram_id=91005, is_premium=True, music_file_id="audio:old"
    )
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("remove_music", user_id=user.id)
    cb_data = ProfileEditCb(action="remove_music")

    with patch("app.bot.handlers.profile.send_premium_media", new_callable=AsyncMock):
        await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    await db_session.refresh(profile)
    assert profile.music_file_id is None
    # Обработчик отвечает answer() без тоста при удалении, затем рендерит карточку.
    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_remove_music_non_premium_blocked(db_session, storage) -> None:
    """Не-premium юзер нажимает remove_music → show_alert NEED_PREMIUM."""
    user, profile = await _seed_profile(
        db_session, telegram_id=91006, is_premium=False, music_file_id="audio:old"
    )
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("remove_music", user_id=user.id)
    cb_data = ProfileEditCb(action="remove_music")

    await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    callback.answer.assert_awaited_once_with(pm_texts.NEED_PREMIUM, show_alert=True)
    await db_session.refresh(profile)
    assert profile.music_file_id == "audio:old"


# ---------------------------------------------------------------------------
# Premium gate: add_video_note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_video_note_non_premium_blocked(db_session, storage) -> None:
    """Не-premium юзер нажимает «Добавить кружок» → show_alert NEED_PREMIUM."""
    user, _profile = await _seed_profile(db_session, telegram_id=91007, is_premium=False)
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("add_video_note", user_id=user.id)
    cb_data = ProfileEditCb(action="add_video_note")

    await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    callback.answer.assert_awaited_once_with(pm_texts.NEED_PREMIUM, show_alert=True)
    current = await state.get_state()
    assert current is None


@pytest.mark.asyncio
async def test_add_video_note_premium_activates_fsm(db_session, storage) -> None:
    """Premium юзер нажимает «Добавить кружок» — FSM в waiting_video_note, инструкция выведена."""
    user, _profile = await _seed_profile(db_session, telegram_id=91008, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("add_video_note", user_id=user.id)
    cb_data = ProfileEditCb(action="add_video_note")

    await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    current = await state.get_state()
    assert current == ProfileEditStates.waiting_video_note.state
    callback.message.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# waiting_video_note: wrong types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_note_wrong_type_text(db_session, storage) -> None:
    """В waiting_video_note присылает текст → VIDEO_NOTE_WAITING."""
    user, _profile = await _seed_profile(db_session, telegram_id=91009, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    await state.set_state(ProfileEditStates.waiting_video_note)

    message = _mock_message(text="text")
    await on_video_note_wrong_type(message)

    message.answer.assert_awaited_once_with(pm_texts.VIDEO_NOTE_WAITING)


@pytest.mark.asyncio
async def test_video_note_got_regular_video(db_session, storage) -> None:
    """В waiting_video_note присылает обычное видео → VIDEO_NOTE_WRONG_TYPE."""
    user, _profile = await _seed_profile(db_session, telegram_id=91010, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    await state.set_state(ProfileEditStates.waiting_video_note)

    message = _mock_message(has_video=True)
    await on_video_note_got_video(message)

    message.answer.assert_awaited_once_with(pm_texts.VIDEO_NOTE_WRONG_TYPE)


# ---------------------------------------------------------------------------
# waiting_video_note: video_note received
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_note_received_saves_file_id(db_session, storage) -> None:
    """Premium юзер в waiting_video_note присылает video_note → file_id сохранён, FSM сброшен."""
    user, profile = await _seed_profile(db_session, telegram_id=91011, is_premium=True)
    state = _fsm(storage, user_id=user.id)
    await state.set_state(ProfileEditStates.waiting_video_note)
    bot = _mock_bot()
    message = _mock_message(video_note_file_id="vn:abc")

    with patch("app.bot.handlers.profile.send_premium_media", new_callable=AsyncMock):
        await on_video_note_received(message, state, user, db_session, bot)

    current = await state.get_state()
    assert current is None

    await db_session.refresh(profile)
    assert profile.video_note_file_id == "vn:abc"
    message.answer.assert_awaited()
    texts_sent = [call.args[0] for call in message.answer.call_args_list]
    assert any(pm_texts.VIDEO_NOTE_SAVED in t for t in texts_sent)


# ---------------------------------------------------------------------------
# Remove video_note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_video_note_clears_field(db_session, storage) -> None:
    """Premium юзер нажимает «Убрать кружок» → поле video_note_file_id = None."""
    user, profile = await _seed_profile(
        db_session, telegram_id=91012, is_premium=True, video_note_file_id="vn:old"
    )
    state = _fsm(storage, user_id=user.id)
    bot = _mock_bot()
    callback = _mock_callback("remove_video_note", user_id=user.id)
    cb_data = ProfileEditCb(action="remove_video_note")

    with patch("app.bot.handlers.profile.send_premium_media", new_callable=AsyncMock):
        await on_profile_edit_dispatch(callback, cb_data, state, user, db_session, bot)

    await db_session.refresh(profile)
    assert profile.video_note_file_id is None
    # Обработчик отвечает answer() без тоста при удалении, затем рендерит карточку.
    callback.answer.assert_awaited()


# ---------------------------------------------------------------------------
# send_premium_media utility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_premium_media_sends_audio(db_session) -> None:
    """send_premium_media с music_file_id → bot.send_audio вызван."""
    _user, profile = await _seed_profile(
        db_session, telegram_id=91013, music_file_id="audio:test123"
    )
    bot = _mock_bot()

    await send_premium_media(bot, 9999, profile, db_session, with_premium_media=True)

    bot.send_audio.assert_awaited_once_with(9999, "audio:test123")
    bot.send_video_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_premium_media_sends_video_note(db_session) -> None:
    """send_premium_media с video_note_file_id → bot.send_video_note вызван."""
    _user, profile = await _seed_profile(
        db_session, telegram_id=91014, video_note_file_id="vn:test456"
    )
    bot = _mock_bot()

    await send_premium_media(bot, 9999, profile, db_session, with_premium_media=True)

    bot.send_video_note.assert_awaited_once_with(9999, "vn:test456")
    bot.send_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_premium_media_with_premium_media_false_skips(db_session) -> None:
    """send_premium_media с with_premium_media=False → ничего не отправляется."""
    _user, profile = await _seed_profile(
        db_session,
        telegram_id=91015,
        music_file_id="audio:x",
        video_note_file_id="vn:x",
    )
    bot = _mock_bot()

    await send_premium_media(bot, 9999, profile, db_session, with_premium_media=False)

    bot.send_audio.assert_not_awaited()
    bot.send_video_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_premium_media_invalid_audio_clears_db(db_session) -> None:
    """TelegramAPIError при отправке аудио → warning лог + music_file_id = None в БД."""
    _user, profile = await _seed_profile(
        db_session, telegram_id=91016, music_file_id="audio:invalid"
    )
    bot = _mock_bot()
    bot.send_audio = AsyncMock(
        side_effect=TelegramAPIError(method=MagicMock(), message="Bad file_id")
    )

    await send_premium_media(bot, 9999, profile, db_session, with_premium_media=True)

    await db_session.refresh(profile)
    assert profile.music_file_id is None


@pytest.mark.asyncio
async def test_send_premium_media_invalid_video_note_clears_db(db_session) -> None:
    """TelegramAPIError при отправке кружка → warning лог + video_note_file_id = None в БД."""
    _user, profile = await _seed_profile(
        db_session, telegram_id=91017, video_note_file_id="vn:invalid"
    )
    bot = _mock_bot()
    bot.send_video_note = AsyncMock(
        side_effect=TelegramAPIError(method=MagicMock(), message="Bad file_id")
    )

    await send_premium_media(bot, 9999, profile, db_session, with_premium_media=True)

    await db_session.refresh(profile)
    assert profile.video_note_file_id is None
