from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType


@pytest.mark.asyncio
async def test_log_event_persists(db_session) -> None:
    user = await UserRepository(db_session).create(telegram_id=50001)
    repo = AnalyticsRepository(db_session)
    await repo.log_event(user.id, EventType.LIKE, payload={"to": 42})

    events = await repo.list_recent_for_user(user.id)
    assert len(events) == 1
    assert events[0].event_type == "like"
    assert events[0].payload == {"to": 42}
    assert events[0].user_id == user.id


@pytest.mark.asyncio
async def test_log_event_with_null_user(db_session) -> None:
    repo = AnalyticsRepository(db_session)
    await repo.log_event(None, EventType.BOT_START, payload=None)
    # Никаких исключений — запись прошла. list_recent_for_user(None) не имеет смысла,
    # просто убеждаемся, что вызов не упал. Дополнительно поищем через явный SELECT.
    from sqlalchemy import select

    from app.db.models.analytics import AnalyticsEvent

    rows = (
        (
            await db_session.execute(
                select(AnalyticsEvent).where(
                    AnalyticsEvent.user_id.is_(None),
                    AnalyticsEvent.event_type == "bot_start",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_log_event_swallows_db_errors() -> None:
    """Если сессия закрыта/в ошибке — log_event не должен пробрасывать исключение."""
    broken_session = MagicMock()
    broken_session.add = MagicMock()
    broken_session.flush = AsyncMock(side_effect=SQLAlchemyError("session is closed"))

    repo = AnalyticsRepository(broken_session)
    # Не должно поднимать исключение.
    await repo.log_event(1, EventType.LIKE, payload={"k": "v"})
    broken_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_event_swallows_unexpected_errors() -> None:
    """Любое неожиданное исключение тоже проглатывается — телеметрия не валит поток."""
    broken_session = MagicMock()
    broken_session.add = MagicMock(side_effect=RuntimeError("unexpected"))
    broken_session.flush = AsyncMock()

    repo = AnalyticsRepository(broken_session)
    await repo.log_event(None, EventType.BOT_START)
