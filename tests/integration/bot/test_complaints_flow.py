"""Интеграционные тесты потока «Жалоба» (этап 5.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.complaints import (
    on_comment_skip,
    on_comment_text,
    on_complaint_cancel,
    on_reason_picked,
    start_complaint_flow,
)
from app.bot.keyboards.complaints import ComplaintCommentCb, ComplaintReasonCb
from app.bot.states.complaints import ComplaintStates
from app.db.models.dictionaries import ComplaintReason
from app.db.models.moderation import Complaint
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository


def _state() -> FSMContext:
    """Свежий FSMContext с MemoryStorage — без Redis."""
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=1, user_id=1),
    )


def _callback() -> AsyncMock:
    cb = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _message(text: str = "") -> AsyncMock:
    msg = AsyncMock()
    msg.text = text
    msg.answer = AsyncMock()
    return msg


async def _make_user(db_session, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


async def _make_profile(db_session, user_id: int, nickname: str):
    """Минимальный профиль, чтобы _save_complaint_and_notify подтянул nickname."""
    from app.db.models.dictionaries import Gender, Vibe

    male = await DictionaryRepository(db_session).get_by_code(Gender, "male")
    vibe = (await db_session.execute(select(Vibe).limit(1))).scalar_one()
    repo = ProfileRepository(db_session)
    profile = await repo.create(
        user_id=user_id,
        nickname=nickname,
        age=25,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=60,
        bio="bio",
        own_vibe_id=vibe.id,
        main_media_type="photo",
        main_media_file_id="placeholder",
    )
    return profile


@pytest.mark.asyncio
async def test_start_complaint_sets_state_and_shows_reasons(db_session) -> None:
    state = _state()
    cb = _callback()
    await start_complaint_flow(cb, state, target_user_id=555, db_session=db_session)
    assert (await state.get_state()) == ComplaintStates.choosing_reason.state
    data = await state.get_data()
    assert data["complaint_target_user_id"] == 555
    cb.message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_pick_reason_advances_to_writing_comment(db_session) -> None:
    state = _state()
    await state.set_state(ComplaintStates.choosing_reason)
    cb = _callback()
    reason = await DictionaryRepository(db_session).get_by_code(ComplaintReason, "spam")
    await on_reason_picked(
        callback=cb,
        callback_data=ComplaintReasonCb(reason_id=reason.id, target_user_id=555),
        state=state,
    )
    assert (await state.get_state()) == ComplaintStates.writing_comment.state
    data = await state.get_data()
    assert data["complaint_reason_id"] == reason.id


@pytest.mark.asyncio
async def test_comment_text_saves_complaint(db_session) -> None:
    a = await _make_user(db_session, telegram_id=70101)
    b = await _make_user(db_session, telegram_id=70102)
    await _make_profile(db_session, a.id, "Alice")
    await _make_profile(db_session, b.id, "Bob")
    reason = await DictionaryRepository(db_session).get_by_code(ComplaintReason, "spam")

    state = _state()
    await state.set_state(ComplaintStates.writing_comment)
    await state.update_data(complaint_reason_id=reason.id, complaint_target_user_id=b.id)

    msg = _message("шлёт спам и рекламу")
    await on_comment_text(
        message=msg,
        state=state,
        user=a,
        db_session=db_session,
        bot=AsyncMock(),
    )
    await db_session.flush()

    complaints = list(
        (await db_session.execute(select(Complaint).where(Complaint.from_user_id == a.id)))
        .scalars()
        .all()
    )
    assert len(complaints) == 1
    assert complaints[0].target_user_id == b.id
    assert complaints[0].status == "new"
    assert complaints[0].comment == "шлёт спам и рекламу"


@pytest.mark.asyncio
async def test_skip_comment_saves_without_text(db_session) -> None:
    a = await _make_user(db_session, telegram_id=70111)
    b = await _make_user(db_session, telegram_id=70112)
    await _make_profile(db_session, a.id, "A2")
    await _make_profile(db_session, b.id, "B2")
    reason = await DictionaryRepository(db_session).get_by_code(ComplaintReason, "other")

    state = _state()
    await state.set_state(ComplaintStates.writing_comment)
    await state.update_data(complaint_reason_id=reason.id, complaint_target_user_id=b.id)

    cb = _callback()
    await on_comment_skip(
        callback=cb,
        callback_data=ComplaintCommentCb(action="skip", target_user_id=b.id),
        state=state,
        user=a,
        db_session=db_session,
        bot=AsyncMock(),
    )
    await db_session.flush()

    complaint = (
        await db_session.execute(select(Complaint).where(Complaint.from_user_id == a.id))
    ).scalar_one()
    assert complaint.comment is None


@pytest.mark.asyncio
async def test_complaint_cancel_clears_state(db_session) -> None:
    a = await _make_user(db_session, telegram_id=70121)
    state = _state()
    await state.set_state(ComplaintStates.writing_comment)
    await state.update_data(complaint_reason_id=1, complaint_target_user_id=999)
    cb = _callback()
    await on_complaint_cancel(
        callback=cb,
        callback_data=ComplaintCommentCb(action="cancel", target_user_id=999),
        state=state,
    )
    assert (await state.get_state()) is None
    # Жалоба не записана.
    complaints = list(
        (await db_session.execute(select(Complaint).where(Complaint.from_user_id == a.id)))
        .scalars()
        .all()
    )
    assert complaints == []


@pytest.mark.asyncio
async def test_comment_with_stop_word_rejected(db_session) -> None:
    """Комментарий со стоп-словом не сохраняется, state остаётся."""
    a = await _make_user(db_session, telegram_id=70131)
    b = await _make_user(db_session, telegram_id=70132)
    await _make_profile(db_session, a.id, "A3")
    await _make_profile(db_session, b.id, "B3")
    reason = await DictionaryRepository(db_session).get_by_code(ComplaintReason, "insult")

    # Добавим стоп-слово.
    await ModerationRepository(db_session).add_stop_word(
        pattern="badword_unique_test", kind="word", category="hate_speech", admin_id=None
    )
    await db_session.flush()

    state = _state()
    await state.set_state(ComplaintStates.writing_comment)
    await state.update_data(complaint_reason_id=reason.id, complaint_target_user_id=b.id)

    msg = _message("ты badword_unique_test полный")
    await on_comment_text(
        message=msg,
        state=state,
        user=a,
        db_session=db_session,
        bot=AsyncMock(),
    )
    # State не сброшен — повтор шага.
    assert (await state.get_state()) == ComplaintStates.writing_comment.state
    # Complaint не создан.
    complaints = list(
        (await db_session.execute(select(Complaint).where(Complaint.from_user_id == a.id)))
        .scalars()
        .all()
    )
    assert complaints == []


@pytest.mark.asyncio
async def test_admin_notification_sent_to_configured_admin(db_session, monkeypatch) -> None:
    """settings.admin_telegram_ids → bot.send_message вызван для каждого admin_id."""
    from app.config import settings as app_settings

    a = await _make_user(db_session, telegram_id=70201)
    b = await _make_user(db_session, telegram_id=70202)
    await _make_profile(db_session, a.id, "From")
    await _make_profile(db_session, b.id, "Target")
    reason = await DictionaryRepository(db_session).get_by_code(ComplaintReason, "spam")

    monkeypatch.setattr(app_settings, "admin_telegram_ids", [555111, 555222])

    state = _state()
    await state.set_state(ComplaintStates.writing_comment)
    await state.update_data(complaint_reason_id=reason.id, complaint_target_user_id=b.id)

    bot = AsyncMock()
    cb = _callback()
    await on_comment_skip(
        callback=cb,
        callback_data=ComplaintCommentCb(action="skip", target_user_id=b.id),
        state=state,
        user=a,
        db_session=db_session,
        bot=bot,
    )
    # Каждому из двух админов отправилось.
    chat_ids = [call.kwargs.get("chat_id") for call in bot.send_message.call_args_list]
    assert set(chat_ids) == {555111, 555222}
