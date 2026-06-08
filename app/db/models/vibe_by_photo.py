"""Модель запроса «Вайб по фото» (Premium-фича).

Пользователь загружает 1-3 фото, бот пересылает их в MEDIA_STAGING_CHAT_ID
с inline-клавиатурой выбора вайба. Модератор кликает кнопку → вайб
присваивается профилю, и регистрация продолжается / профиль обновляется.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Допустимые значения статусов запроса.
VIBE_BY_PHOTO_STATUSES: tuple[str, ...] = ("pending", "completed", "rejected")
# Допустимые значения "источника" запроса (registration / profile edit).
VIBE_BY_PHOTO_ORIGINS: tuple[str, ...] = ("registration", "profile_edit")


class VibeByPhotoRequest(Base):
    """Запрос пользователя на подбор вайба по присланным фото.

    Поле photo_file_ids хранит file_id фотографий через ``;`` (макс. 3). Это
    компромисс между простотой схемы и работой Alembic с ARRAY на разных
    диалектах: запросы редки, парсинг тривиален, индексы по элементам не нужны.
    """

    __tablename__ = "vibe_by_photo_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="vbp_status_allowed",
        ),
        CheckConstraint(
            "origin IN ('registration', 'profile_edit')",
            name="vbp_origin_allowed",
        ),
        Index("ix_vbp_requests_status_created", "status", "created_at"),
        Index("ix_vbp_requests_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Профиль может ещё не существовать (registration-flow), потому FK nullable.
    profile_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    # file_id фото через ';'. Максимум 3 шт.
    photo_file_ids: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        default="",
        server_default="",
    )
    assigned_vibe_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("vibes.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
