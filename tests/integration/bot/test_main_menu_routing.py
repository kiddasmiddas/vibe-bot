from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.handlers.common import cmd_start
from app.db.models.dictionaries import Gender, Vibe
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import common as texts


async def _seed_user(db_session, *, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


async def _seed_profile(db_session, user, *, is_completed: bool):
    # Берём пол из seed-миграции и создаём пару вайбов специально для теста.
    from sqlalchemy import select

    male = (await db_session.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_a = Vibe(code="t_vibe_a", title="A", number=8001, image_file_id="a")
    vibe_b = Vibe(code="t_vibe_b", title="B", number=8002, image_file_id="b")
    db_session.add_all([vibe_a, vibe_b])
    await db_session.flush()

    profile = await ProfileRepository(db_session).create(
        user_id=user.id,
        nickname="Nick",
        age=22,
        gender_id=male.id,
        looking_for_age_min=18,
        looking_for_age_max=30,
        bio="hi",
        own_vibe_id=vibe_a.id,
        main_media_type="photo",
        main_media_file_id="file_x",
    )
    if is_completed:
        await ProfileRepository(db_session).mark_completed(profile.id)
        await db_session.flush()
    return profile


def _flatten(markup) -> list[str]:
    return [btn.text for row in markup.keyboard for btn in row]


@pytest.mark.asyncio
async def test_cmd_start_registered_user_sees_full_menu(db_session) -> None:
    user = await _seed_user(db_session, telegram_id=1001)
    await _seed_profile(db_session, user, is_completed=True)

    message = MagicMock()
    message.answer = AsyncMock()

    await cmd_start(message, user, db_session)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert args[0] == texts.WELCOME
    markup = kwargs["reply_markup"]
    assert _flatten(markup) == [
        texts.BTN_MY_PROFILE,
        texts.BTN_SEARCH,
        texts.BTN_LIKES_MATCHES,
        texts.BTN_MINIAPP,
        texts.BTN_PREMIUM,
        texts.BTN_SUPPORT,
    ]


@pytest.mark.asyncio
async def test_cmd_start_user_without_profile_sees_create_button(db_session) -> None:
    user = await _seed_user(db_session, telegram_id=1002)

    message = MagicMock()
    message.answer = AsyncMock()

    await cmd_start(message, user, db_session)

    markup = message.answer.call_args.kwargs["reply_markup"]
    assert _flatten(markup) == [texts.BTN_CREATE_PROFILE]


@pytest.mark.asyncio
async def test_cmd_start_user_with_incomplete_profile_sees_create_button(db_session) -> None:
    user = await _seed_user(db_session, telegram_id=1003)
    await _seed_profile(db_session, user, is_completed=False)

    message = MagicMock()
    message.answer = AsyncMock()

    await cmd_start(message, user, db_session)

    markup = message.answer.call_args.kwargs["reply_markup"]
    assert _flatten(markup) == [texts.BTN_CREATE_PROFILE]
