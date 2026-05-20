from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.bot.middlewares.user_middleware import UserMiddleware
from app.db.models.analytics import AnalyticsEvent
from app.db.models.user import User
from app.services.analytics_events import EventType


@pytest.fixture
def session_factory(db_engine, db_session):
    """Фабрика, отдающая ту же транзакционную сессию, что и `db_session`.

    Это нужно, чтобы изменения, сделанные middleware, были видны тесту
    в рамках одной SAVEPOINT-транзакции (см. conftest.db_session).
    """

    class _SingleSessionFactory:
        def __call__(self):
            return _Ctx(db_session)

    class _Ctx:
        def __init__(self, session) -> None:
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            # session.commit() в middleware на вложенной транзакции — это flush,
            # внешний rollback в фикстуре всё откатит после теста.
            return None

    return _SingleSessionFactory()


@pytest.mark.asyncio
async def test_user_middleware_creates_user_and_logs_bot_start(db_session, session_factory) -> None:
    mw = UserMiddleware(session_factory)

    handler = AsyncMock(return_value="ok")
    tg_user = MagicMock(id=42, username="alice")
    event = MagicMock()
    data: dict = {"event_from_user": tg_user}

    # Подменим commit, чтобы он работал как flush в рамках теста.
    db_session.commit = db_session.flush  # type: ignore[assignment]

    result = await mw(handler, event, data)
    assert result == "ok"

    user = data["user"]
    assert user is not None
    assert user.telegram_id == 42
    assert user.username == "alice"

    # Запись в БД действительно сохранена.
    fetched = (await db_session.execute(select(User).where(User.telegram_id == 42))).scalar_one()
    assert fetched.id == user.id

    events = (
        (await db_session.execute(select(AnalyticsEvent).where(AnalyticsEvent.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].event_type == EventType.BOT_START.value


@pytest.mark.asyncio
async def test_user_middleware_does_not_duplicate_bot_start(db_session, session_factory) -> None:
    mw = UserMiddleware(session_factory)
    db_session.commit = db_session.flush  # type: ignore[assignment]

    handler = AsyncMock(return_value="ok")
    tg_user = MagicMock(id=77, username="bob")
    event = MagicMock()

    await mw(handler, event, {"event_from_user": tg_user})
    await mw(handler, event, {"event_from_user": tg_user})

    users = (await db_session.execute(select(User).where(User.telegram_id == 77))).scalars().all()
    assert len(users) == 1

    events = (
        (
            await db_session.execute(
                select(AnalyticsEvent).where(AnalyticsEvent.user_id == users[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


@pytest.mark.asyncio
async def test_user_middleware_passes_through_without_from_user(
    session_factory,
) -> None:
    mw = UserMiddleware(session_factory)
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    data: dict = {"event_from_user": None}

    result = await mw(handler, event, data)
    assert result == "ok"
    assert data["user"] is None
