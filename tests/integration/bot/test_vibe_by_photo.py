"""Integration tests Premium-фичи «Вайб по фото» (после редизайна модерации).

Покрывают:
- Premium gate (non-Premium юзер получает alert).
- Старт flow и переход в FSM-state vibe_by_photo_upload.
- Сбор фото (1..3, лимит на 4-м).
- Финализация:
  - запись создаётся в БД;
  - staging-чат получает фото БЕЗ inline-клавиатуры (архив);
  - каждый модератор получает в личку пару (Msg1=фото с заголовком,
    Msg2=пикер с пагинацией).
- Модератор кликает по вайбу → запись completed, profile.own_vibe_id обновлён,
  юзер получает уведомление.
- Модератор отклоняет → запись rejected, юзер получает REJECTED.
- Не-модератор/админ получает ADMIN_NOT_AUTHORIZED.
- Пагинация: action="page" редактирует Msg2 без новых сообщений.
- skip/prev: переход к соседнему pending-запросу.
- /admin → «Вайб по фото»: список pending-запросов рендерится.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot.handlers.admin.vibe_by_photo import (
    cb_vbp_queue_list,
    cb_vibe_by_photo_assign,
)
from app.bot.handlers.profile import (
    cb_edit_vibe_by_photo_done,
    cb_edit_vibe_by_photo_start,
)
from app.bot.handlers.registration import (
    cb_vibe_by_photo_done,
    cb_vibe_by_photo_start,
    on_vibe_by_photo_photo,
)
from app.bot.keyboards.admin import VibeByPhotoAssignCb
from app.bot.keyboards.registration import VibeByPhotoStartCb
from app.bot.states.profile_edit import ProfileEditStates
from app.bot.states.registration import RegistrationStates
from app.config import settings as app_settings
from app.db.models.dictionaries import Vibe
from app.db.models.vibe_by_photo import VibeByPhotoRequest
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.vibe_by_photo_repo import VibeByPhotoRepository
from app.texts import vibe_by_photo as vbp_texts

_STAGING_CHAT_ID = 998877


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Делаем env предсказуемым: staging chat фиксирован, admin_telegram_ids пуст.

    Пуш в личку модераторам идёт ТОЛЬКО к DB-юзерам с is_moderator=True
    (которые тесты создают явно через ``_make_user(..., is_moderator=True)``).
    Без этой очистки список адресатов был бы непредсказуем (env-зависим).
    """
    monkeypatch.setattr(app_settings, "media_staging_chat_id", _STAGING_CHAT_ID, raising=False)
    monkeypatch.setattr(app_settings, "admin_telegram_ids", [], raising=False)


def _fsm(storage: MemoryStorage, user_id: int = 999) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


async def _make_user(
    db_session,
    *,
    telegram_id: int,
    username: str | None = None,
    is_premium: bool = False,
    is_moderator: bool = False,
):
    user = await UserRepository(db_session).create(telegram_id=telegram_id, username=username)
    if is_premium:
        await UserRepository(db_session).update_premium(
            user.id, is_premium=True, premium_until=None
        )
    if is_moderator:
        from sqlalchemy import update as sa_update

        from app.db.models.user import User as UserModel

        await db_session.execute(
            sa_update(UserModel).where(UserModel.id == user.id).values(is_moderator=True)
        )
        await db_session.flush()
    await db_session.refresh(user)
    return user


def _mock_callback(user_id: int = 999) -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.bot = MagicMock()
    cb.bot.send_photo = AsyncMock()
    cb.bot.send_message = AsyncMock()
    cb.bot.send_media_group = AsyncMock()
    cb.message = MagicMock()
    cb.message.chat = MagicMock()
    cb.message.chat.id = 12345
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.bot = cb.bot
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    return cb


def _mock_message() -> MagicMock:
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 12345
    msg.answer = AsyncMock()
    msg.bot = MagicMock()
    msg.bot.send_photo = AsyncMock()
    msg.bot.send_message = AsyncMock()
    msg.bot.send_media_group = AsyncMock()
    return msg


# --------------------------- Premium gate ---------------------------


@pytest.mark.asyncio
async def test_cb_vibe_by_photo_start_blocks_non_premium(db_session, storage) -> None:
    """Не-Premium юзер получает alert и не уходит в FSM-state."""
    user = await _make_user(db_session, telegram_id=70001, is_premium=False)
    state = _fsm(storage, user_id=user.telegram_id)
    await state.set_state(RegistrationStates.own_vibe)

    cb = _mock_callback(user_id=user.telegram_id)
    cb_data = VibeByPhotoStartCb(origin="registration")

    await cb_vibe_by_photo_start(cb, cb_data, state, user, db_session)

    cb.answer.assert_awaited_once_with(vbp_texts.NOT_PREMIUM, show_alert=True)
    assert await state.get_state() == RegistrationStates.own_vibe.state


@pytest.mark.asyncio
async def test_cb_vibe_by_photo_start_premium_enters_upload_state(db_session, storage) -> None:
    """Premium-юзер уходит в FSM-state vibe_by_photo_upload и видит ASK_PHOTOS."""
    user = await _make_user(db_session, telegram_id=70002, is_premium=True)
    state = _fsm(storage, user_id=user.telegram_id)
    await state.set_state(RegistrationStates.own_vibe)

    cb = _mock_callback(user_id=user.telegram_id)
    cb.message.answer = AsyncMock()
    cb_data = VibeByPhotoStartCb(origin="registration")

    await cb_vibe_by_photo_start(cb, cb_data, state, user, db_session)

    assert await state.get_state() == RegistrationStates.vibe_by_photo_upload.state
    cb.message.answer.assert_awaited_once()
    data = await state.get_data()
    assert data["vbp_origin"] == "registration"


# --------------------------- Photo accumulation ---------------------------


@pytest.mark.asyncio
async def test_on_vibe_by_photo_photo_accumulates(db_session, storage) -> None:
    """Каждое присланное фото попадает в FSM data; на 4-м — лимит."""
    user = await _make_user(db_session, telegram_id=70003, is_premium=True)
    state = _fsm(storage, user_id=user.telegram_id)
    await state.set_state(RegistrationStates.vibe_by_photo_upload)
    await state.update_data(vbp_origin="registration")

    msg = _mock_message()
    msg.photo = [MagicMock(file_id="f1", file_size=100_000)]

    await on_vibe_by_photo_photo(msg, state, user, db_session)
    data = await state.get_data()
    assert data["vbp_photo_file_ids"] == ["f1"]

    msg.photo = [MagicMock(file_id="f2", file_size=100_000)]
    await on_vibe_by_photo_photo(msg, state, user, db_session)
    data = await state.get_data()
    assert data["vbp_photo_file_ids"] == ["f1", "f2"]

    msg.photo = [MagicMock(file_id="f3", file_size=100_000)]
    await on_vibe_by_photo_photo(msg, state, user, db_session)
    data = await state.get_data()
    assert data["vbp_photo_file_ids"] == ["f1", "f2", "f3"]

    msg.photo = [MagicMock(file_id="f4", file_size=100_000)]
    await on_vibe_by_photo_photo(msg, state, user, db_session)
    data = await state.get_data()
    assert data["vbp_photo_file_ids"] == ["f1", "f2", "f3"]
    msg.answer.assert_any_await(vbp_texts.PHOTO_MAX_REACHED)


# --------------------- Финализация: staging + push модам ---------------------


@pytest.mark.asyncio
async def test_done_creates_request_and_dispatches_to_staging_and_moderators(
    db_session, storage
) -> None:
    """`Готово`:
    - создаёт VibeByPhotoRequest со status=pending;
    - шлёт фото в staging БЕЗ inline-клавиатуры;
    - пушит пару (фото+пикер) в личку каждому модератору из DB.
    """
    user = await _make_user(db_session, telegram_id=70004, username="alice", is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70005, is_moderator=True)
    state = _fsm(storage, user_id=user.telegram_id)
    await state.set_state(RegistrationStates.vibe_by_photo_upload)
    await state.update_data(vbp_photo_file_ids=["abc", "def"], vbp_origin="registration")

    cb = _mock_callback(user_id=user.telegram_id)
    bot = cb.bot

    await cb_vibe_by_photo_done(cb, state, user, db_session, bot)

    rows = (
        (
            await db_session.execute(
                select(VibeByPhotoRequest).where(VibeByPhotoRequest.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    req = rows[0]
    assert req.status == "pending"
    assert req.origin == "registration"

    # ВСЕ вызовы send_photo НЕ должны нести reply_markup (staging — архив).
    for call in bot.send_photo.await_args_list:
        assert call.kwargs.get("reply_markup") is None

    # Staging получил 2 фото (по числу file_ids), первое — с caption.
    staging_calls = [
        c for c in bot.send_photo.await_args_list if c.kwargs.get("chat_id") == _STAGING_CHAT_ID
    ]
    assert len(staging_calls) == 2
    assert staging_calls[0].kwargs.get("caption") is not None
    assert str(req.id) in staging_calls[0].kwargs["caption"]
    assert staging_calls[1].kwargs.get("caption") is None

    # Модератору в личку улетел media_group (2 фотки) + send_message с пикером.
    bot.send_media_group.assert_awaited_once()
    media_call = bot.send_media_group.await_args
    assert media_call.kwargs["chat_id"] == moderator.telegram_id

    # Пикер (Msg2): send_message с reply_markup и текстом, упоминающим request.
    picker_calls = [
        c
        for c in bot.send_message.await_args_list
        if c.kwargs.get("chat_id") == moderator.telegram_id
    ]
    assert len(picker_calls) == 1
    assert picker_calls[0].kwargs.get("reply_markup") is not None
    assert str(req.id) in picker_calls[0].kwargs["text"]


# --------------------------- Модератор: pick ---------------------------


@pytest.mark.asyncio
async def test_admin_pick_vibe_assigns_and_notifies_user(db_session, storage) -> None:
    """Модератор кликает на номер вайба → completed, profile.own_vibe_id обновлён,
    юзеру уходит уведомление с названием вайба.
    """
    target_user = await _make_user(db_session, telegram_id=70010, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70011, is_moderator=True)

    initial_vibe = (await db_session.execute(select(Vibe).where(Vibe.number == 1))).scalar_one()
    profile_repo = ProfileRepository(db_session)
    profile = await profile_repo.create(
        user_id=target_user.id,
        nickname="alice",
        age=20,
        gender_id=1,
        looking_for_age_min=18,
        looking_for_age_max=30,
        bio="hi",
        own_vibe_id=initial_vibe.id,
        main_media_type="photo",
        main_media_file_id="placeholder",
    )
    await db_session.flush()

    repo = VibeByPhotoRepository(db_session)
    request = await repo.create_request(
        user_id=target_user.id,
        origin="profile_edit",
        photo_file_ids=["foo"],
        profile_id=profile.id,
    )
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="pick", request_id=request.id, vibe_number=5)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    updated = await repo.get_by_id(request.id)
    assert updated is not None
    assert updated.status == "completed"
    target_vibe = (await db_session.execute(select(Vibe).where(Vibe.number == 5))).scalar_one()
    assert updated.assigned_vibe_id == target_vibe.id
    assert updated.assigned_by_admin_id == moderator.id

    fresh_profile = await profile_repo.get_by_id(profile.id)
    assert fresh_profile is not None
    assert fresh_profile.own_vibe_id == target_vibe.id

    # Уведомление таргет-юзеру.
    notif_calls = [
        c
        for c in bot.send_message.await_args_list
        if c.kwargs.get("chat_id") == target_user.telegram_id
    ]
    assert len(notif_calls) == 1
    assert target_vibe.title in notif_calls[0].kwargs["text"]

    # Старая клавиатура снята.
    cb.message.edit_reply_markup.assert_awaited()


@pytest.mark.asyncio
async def test_admin_pick_auto_advances_to_next_pending(db_session, storage) -> None:
    """После pick'а очередь авто-продолжается следующим pending в чате модератора."""
    target_a = await _make_user(db_session, telegram_id=70060, is_premium=True)
    target_b = await _make_user(db_session, telegram_id=70061, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70062, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    req_a = await repo.create_request(
        user_id=target_a.id, origin="registration", photo_file_ids=["a"]
    )
    req_b = await repo.create_request(
        user_id=target_b.id, origin="registration", photo_file_ids=["b"]
    )
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="pick", request_id=req_a.id, vibe_number=2)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    # Из чата модератора должна выйти пара для req_b (фото + пикер).
    picker_calls = [
        c
        for c in bot.send_message.await_args_list
        if c.kwargs.get("reply_markup") is not None and str(req_b.id) in c.kwargs.get("text", "")
    ]
    assert len(picker_calls) == 1


@pytest.mark.asyncio
async def test_admin_pick_queue_empty_after(db_session, storage) -> None:
    """Когда после pick'а pending'ов больше нет — модератору приходит уведомление."""
    target = await _make_user(db_session, telegram_id=70070, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70071, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    req = await repo.create_request(user_id=target.id, origin="registration", photo_file_ids=["x"])
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="pick", request_id=req.id, vibe_number=2)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    cb.message.answer.assert_any_await(text=vbp_texts.ADMIN_QUEUE_EMPTY_AFTER_ACTION)


# --------------------------- Модератор: reject ---------------------------


@pytest.mark.asyncio
async def test_admin_reject_marks_rejected_and_notifies_user(db_session, storage) -> None:
    target_user = await _make_user(db_session, telegram_id=70020, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70021, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    request = await repo.create_request(
        user_id=target_user.id, origin="registration", photo_file_ids=["x"]
    )
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="reject", request_id=request.id)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    updated = await repo.get_by_id(request.id)
    assert updated is not None
    assert updated.status == "rejected"
    assert updated.assigned_by_admin_id == moderator.id

    notif_calls = [
        c
        for c in bot.send_message.await_args_list
        if c.kwargs.get("chat_id") == target_user.telegram_id
    ]
    assert len(notif_calls) == 1
    assert notif_calls[0].kwargs["text"] == vbp_texts.REJECTED


# --------------------------- Модератор: not authorized ---------------------------


@pytest.mark.asyncio
async def test_admin_callback_blocks_non_moderator(db_session, storage) -> None:
    """Обычный юзер (не модератор и не админ) получает alert."""
    target_user = await _make_user(db_session, telegram_id=70030, is_premium=True)
    intruder = await _make_user(db_session, telegram_id=70031, is_moderator=False)

    repo = VibeByPhotoRepository(db_session)
    request = await repo.create_request(
        user_id=target_user.id, origin="registration", photo_file_ids=["x"]
    )
    await db_session.flush()

    cb = _mock_callback(user_id=intruder.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="pick", request_id=request.id, vibe_number=3)

    await cb_vibe_by_photo_assign(cb, cb_data, intruder, db_session, bot)

    cb.answer.assert_awaited_once_with(vbp_texts.ADMIN_NOT_AUTHORIZED, show_alert=True)
    fresh = await repo.get_by_id(request.id)
    assert fresh is not None
    assert fresh.status == "pending"


# --------------------------- Пагинация вайбов внутри запроса ---------------------------


@pytest.mark.asyncio
async def test_admin_page_action_edits_picker(db_session, storage) -> None:
    """action='page' — переключает страницу пикера через edit_text."""
    target = await _make_user(db_session, telegram_id=70040, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70041, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    req = await repo.create_request(user_id=target.id, origin="registration", photo_file_ids=["x"])
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="page", request_id=req.id, page=2)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    cb.message.edit_text.assert_awaited_once()
    # Текст содержит индикатор страницы 3/4.
    edit_kwargs = cb.message.edit_text.await_args.kwargs
    assert "3/4" in edit_kwargs["text"]


# --------------------------- skip / prev навигация ---------------------------


@pytest.mark.asyncio
async def test_admin_skip_navigates_to_next_pending(db_session, storage) -> None:
    target_a = await _make_user(db_session, telegram_id=70050, is_premium=True)
    target_b = await _make_user(db_session, telegram_id=70051, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70052, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    req_a = await repo.create_request(
        user_id=target_a.id, origin="registration", photo_file_ids=["a"]
    )
    req_b = await repo.create_request(
        user_id=target_b.id, origin="registration", photo_file_ids=["b"]
    )
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="skip", request_id=req_a.id)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    cb.message.edit_reply_markup.assert_awaited()  # старая клавиатура снята
    # Новая пара для req_b прилетела в чат модератора.
    picker_calls = [
        c
        for c in bot.send_message.await_args_list
        if c.kwargs.get("reply_markup") is not None and str(req_b.id) in c.kwargs.get("text", "")
    ]
    assert len(picker_calls) == 1
    # Статус req_a не меняется.
    fresh = await repo.get_by_id(req_a.id)
    assert fresh is not None and fresh.status == "pending"


@pytest.mark.asyncio
async def test_admin_skip_when_no_next_shows_toast(db_session, storage) -> None:
    target = await _make_user(db_session, telegram_id=70080, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70081, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    req = await repo.create_request(user_id=target.id, origin="registration", photo_file_ids=["x"])
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    cb_data = VibeByPhotoAssignCb(action="skip", request_id=req.id)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    cb.answer.assert_any_await(vbp_texts.ADMIN_NO_NEXT_REQUEST, show_alert=False)


@pytest.mark.asyncio
async def test_admin_prev_navigates_to_previous_pending(db_session, storage) -> None:
    target_a = await _make_user(db_session, telegram_id=70090, is_premium=True)
    target_b = await _make_user(db_session, telegram_id=70091, is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70092, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    req_a = await repo.create_request(
        user_id=target_a.id, origin="registration", photo_file_ids=["a"]
    )
    req_b = await repo.create_request(
        user_id=target_b.id, origin="registration", photo_file_ids=["b"]
    )
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    bot = cb.bot
    # Симулируем что мод сейчас на req_b, идёт «↩️ К прошлой» → должны увидеть req_a.
    cb_data = VibeByPhotoAssignCb(action="prev", request_id=req_b.id)

    await cb_vibe_by_photo_assign(cb, cb_data, moderator, db_session, bot)

    picker_calls = [
        c
        for c in bot.send_message.await_args_list
        if c.kwargs.get("reply_markup") is not None and str(req_a.id) in c.kwargs.get("text", "")
    ]
    assert len(picker_calls) == 1


# --------------------------- /admin → Вайб по фото ---------------------------


@pytest.mark.asyncio
async def test_admin_queue_list_renders(db_session, storage) -> None:
    target = await _make_user(db_session, telegram_id=70100, username="bob", is_premium=True)
    moderator = await _make_user(db_session, telegram_id=70101, is_moderator=True)

    repo = VibeByPhotoRepository(db_session)
    await repo.create_request(user_id=target.id, origin="profile_edit", photo_file_ids=["x", "y"])
    await db_session.flush()

    cb = _mock_callback(user_id=moderator.telegram_id)
    cb.message.edit_text = AsyncMock()
    await cb_vbp_queue_list(cb, moderator, db_session)

    cb.message.edit_text.assert_awaited()
    body = cb.message.edit_text.await_args.kwargs["text"]
    assert "Найдено: 1" in body
    assert "@bob" in body
    assert "profile_edit" in body


@pytest.mark.asyncio
async def test_admin_queue_list_empty(db_session, storage) -> None:
    moderator = await _make_user(db_session, telegram_id=70110, is_moderator=True)

    cb = _mock_callback(user_id=moderator.telegram_id)
    cb.message.edit_text = AsyncMock()
    await cb_vbp_queue_list(cb, moderator, db_session)

    body = cb.message.edit_text.await_args.kwargs["text"]
    assert vbp_texts.ADMIN_QUEUE_EMPTY in body


# --------------------------- profile_edit flow ---------------------------


@pytest.mark.asyncio
async def test_cb_edit_vibe_by_photo_start_premium(db_session, storage) -> None:
    """Из edit_own_vibe Premium-юзер уходит в profile_edit vibe_by_photo_upload."""
    user = await _make_user(db_session, telegram_id=70140, is_premium=True)
    state = _fsm(storage, user_id=user.telegram_id)
    await state.set_state(ProfileEditStates.edit_own_vibe)

    cb = _mock_callback(user_id=user.telegram_id)
    cb_data = VibeByPhotoStartCb(origin="profile_edit")

    await cb_edit_vibe_by_photo_start(cb, cb_data, state, user, db_session)

    assert await state.get_state() == ProfileEditStates.vibe_by_photo_upload.state
    data = await state.get_data()
    assert data["vbp_origin"] == "profile_edit"


@pytest.mark.asyncio
async def test_cb_edit_vibe_by_photo_done_creates_request(db_session, storage) -> None:
    """Финализация из profile_edit → создаётся запись с origin=profile_edit."""
    user = await _make_user(db_session, telegram_id=70141, username="bob", is_premium=True)
    state = _fsm(storage, user_id=user.telegram_id)
    await state.set_state(ProfileEditStates.vibe_by_photo_upload)
    await state.update_data(vbp_photo_file_ids=["only_one"], vbp_origin="profile_edit")

    cb = _mock_callback(user_id=user.telegram_id)
    bot = cb.bot

    await cb_edit_vibe_by_photo_done(cb, state, user, db_session, bot)

    rows = (
        (
            await db_session.execute(
                select(VibeByPhotoRequest).where(VibeByPhotoRequest.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].origin == "profile_edit"
    assert rows[0].status == "pending"
    assert await state.get_state() is None
