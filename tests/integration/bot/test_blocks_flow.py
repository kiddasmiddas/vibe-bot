"""Интеграционные тесты потока «Блокировка» (этап 5.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.bot.handlers.blocks import on_block_cancel, on_block_confirm, start_block_flow
from app.bot.keyboards.blocks import BlockConfirmCb
from app.db.models.matching import Block
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.user_repo import UserRepository


async def _two_users(db_session):
    a = await UserRepository(db_session).create(telegram_id=70001, username="a")
    b = await UserRepository(db_session).create(telegram_id=70002, username="b")
    return a, b


def _callback() -> AsyncMock:
    cb = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.answer = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_start_block_flow_asks_confirmation(db_session) -> None:
    cb = _callback()
    await start_block_flow(cb, target_user_id=999)
    cb.message.answer.assert_called_once()
    # В reply_markup должна быть наша подтверждающая клавиатура.
    kwargs = cb.message.answer.call_args.kwargs
    assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_block_confirm_writes_to_db(db_session) -> None:
    a, b = await _two_users(db_session)
    cb = _callback()
    await on_block_confirm(
        callback=cb,
        callback_data=BlockConfirmCb(action="confirm", target_user_id=b.id),
        user=a,
        db_session=db_session,
        bot=AsyncMock(),
    )
    await db_session.flush()
    blocks = list(
        (await db_session.execute(select(Block).where(Block.blocker_user_id == a.id)))
        .scalars()
        .all()
    )
    assert len(blocks) == 1
    assert blocks[0].blocked_user_id == b.id


@pytest.mark.asyncio
async def test_duplicate_block_is_graceful(db_session) -> None:
    """Повторный блок той же пары не должен валить flow."""
    a, b = await _two_users(db_session)
    # Уже есть блок.
    await MatchingRepository(db_session).add_block(blocker_id=a.id, blocked_id=b.id)
    await db_session.flush()

    cb = _callback()
    await on_block_confirm(
        callback=cb,
        callback_data=BlockConfirmCb(action="confirm", target_user_id=b.id),
        user=a,
        db_session=db_session,
        bot=AsyncMock(),
    )
    # Первое сообщение — BLOCKED_OK. Второе — переход к следующему кандидату
    # (NO_MORE_CANDIDATES в тесте без кандидатов). Главное — handler не упал.
    assert cb.message.answer.call_count >= 1
    first_call_text = cb.message.answer.call_args_list[0].args[0]
    assert "заблокирован" in first_call_text.lower()


@pytest.mark.asyncio
async def test_block_cancel_does_not_write(db_session) -> None:
    a, b = await _two_users(db_session)
    cb = _callback()
    await on_block_cancel(
        callback=cb,
        callback_data=BlockConfirmCb(action="cancel", target_user_id=b.id),
    )
    await db_session.flush()
    blocks = list(
        (await db_session.execute(select(Block).where(Block.blocker_user_id == a.id)))
        .scalars()
        .all()
    )
    assert blocks == []


@pytest.mark.asyncio
async def test_blocked_user_excluded_from_matching(db_session) -> None:
    """После блока заблокированный пользователь не возвращается get_excluded_user_ids."""
    a, b = await _two_users(db_session)
    repo = MatchingRepository(db_session)
    excluded_before = await repo.get_excluded_user_ids(a.id)
    assert b.id not in excluded_before

    await repo.add_block(blocker_id=a.id, blocked_id=b.id)
    await db_session.flush()

    excluded_after = await repo.get_excluded_user_ids(a.id)
    assert b.id in excluded_after
    # Двусторонняя видимость: b тоже не увидит a.
    excluded_for_b = await repo.get_excluded_user_ids(b.id)
    assert a.id in excluded_for_b
