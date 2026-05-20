from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analytics import AnalyticsEvent


class AnalyticsRepository:
    """Доступ к таблице analytics_events. Пишет события best-effort —
    не должен валить пользовательский поток, если БД временно недоступна."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_event(
        self,
        user_id: int | None,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Пишет событие. При любой ошибке БД логирует через loguru и проглатывает.

        Аналитика — фоновая телеметрия и не должна ломать UX. Любой `Exception` от
        SQLAlchemy ловится и подавляется. Не-DB исключения (например, `asyncio.CancelledError`)
        пробрасываются как обычно.
        """
        event = AnalyticsEvent(
            user_id=user_id,
            event_type=event_type,
            payload=payload,
        )
        try:
            self._session.add(event)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.error(
                "analytics log_event failed: event_type={} user_id={} err={}",
                event_type,
                user_id,
                exc,
            )
        except Exception as exc:  # телеметрия не должна ронять поток
            logger.error(
                "analytics log_event unexpected error: event_type={} user_id={} err={}",
                event_type,
                user_id,
                exc,
            )

    async def aggregate_by_event_type(
        self,
        since: datetime,
        until: datetime,
    ) -> dict[str, int]:
        """COUNT(*) по event_type за период [since, until). Используется в аналитике (10.10)."""
        stmt = (
            select(
                AnalyticsEvent.event_type,
                func.count(AnalyticsEvent.id).label("cnt"),
            )
            .where(
                AnalyticsEvent.created_at >= since,
                AnalyticsEvent.created_at < until,
            )
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.event_type: int(row.cnt) for row in rows}

    async def list_recent_for_user(
        self,
        user_id: int,
        limit: int = 50,
    ) -> list[AnalyticsEvent]:
        stmt = (
            select(AnalyticsEvent)
            .where(AnalyticsEvent.user_id == user_id)
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
