from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Допустимые статусы промо-поста.
PROMO_POST_STATUSES: tuple[str, ...] = ("draft", "queued", "sending", "sent", "failed")
# Допустимые сегменты получателей.
PROMO_POST_SEGMENTS: tuple[str, ...] = ("all", "free", "premium", "custom")
# Допустимые типы медиа.
PROMO_POST_MEDIA_TYPES: tuple[str, ...] = ("photo", "video", "animation")
# Допустимые статусы получателя рассылки.
PROMO_RECIPIENT_STATUSES: tuple[str, ...] = ("pending", "sent", "failed")


class PromoPost(Base):
    """Промо-пост (рассылка) от админов: текст + опциональное медиа, сегмент аудитории."""

    __tablename__ = "promo_posts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'queued', 'sending', 'sent', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "target_segment IN ('all', 'free', 'premium', 'custom')",
            name="target_segment_allowed",
        ),
        CheckConstraint(
            "media_type IS NULL OR media_type IN ('photo', 'video', 'animation')",
            name="media_type_allowed",
        ),
        Index("ix_promo_posts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_segment: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    target_user_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PromoPostRecipient(Base):
    """Получатель промо-поста.

    Заполняется при подготовке рассылки и обновляется по факту отправки.
    """

    __tablename__ = "promo_post_recipients"
    __table_args__ = (
        UniqueConstraint(
            "promo_post_id",
            "user_id",
            name="uq_promo_post_recipients_promo_post_id_user_id",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="status_allowed",
        ),
        Index(
            "ix_promo_post_recipients_promo_post_id_status",
            "promo_post_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("promo_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
