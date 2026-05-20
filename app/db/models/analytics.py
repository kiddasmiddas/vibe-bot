from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalyticsEvent(Base):
    """Журнал продуктовой аналитики. Запись здесь не должна валить пользовательский поток —
    репозиторий пишет события best-effort и проглатывает ошибки.

    `event_type` — строка, список валидных значений см. в `app.services.analytics_events.EventType`.
    Мы намеренно НЕ используем Postgres enum-тип, чтобы расширять список без миграций.
    """

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index(
            "ix_analytics_events_event_type_created_at",
            "event_type",
            "created_at",
        ),
        Index("ix_analytics_events_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
