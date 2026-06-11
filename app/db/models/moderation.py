from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
from app.db.models._mixins import TimestampMixin

# Допустимые статусы жалобы.
COMPLAINT_STATUSES: tuple[str, ...] = ("new", "in_progress", "resolved", "rejected")

# Стоп-слова: типы паттернов и категории.
STOP_WORD_KINDS: tuple[str, ...] = ("word", "regex")
STOP_WORD_CATEGORIES: tuple[str, ...] = ("hate_speech", "link", "adult_keyword", "other")

# Журнал модерации: на каком объекте проверяли, какая проверка, какое решение.
MODERATION_TARGET_KINDS: tuple[str, ...] = (
    "profile_bio",
    "profile_nickname",
    "profile_city",
    "profile_media",
    "like_message",
    "creator_post_text",
    "creator_post_photo",
    "complaint_comment",
    "feed_post",
    "feed_comment",
    "feed_media",
)
MODERATION_CHECK_TYPES: tuple[str, ...] = ("text", "nsfw_image")
MODERATION_DECISIONS: tuple[str, ...] = ("approved", "manual_review", "rejected")


class Complaint(Base):
    """Жалоба одного пользователя на другого. Очередь модерации админов."""

    __tablename__ = "complaints"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved', 'rejected')",
            name="status_allowed",
        ),
        CheckConstraint("from_user_id <> target_user_id", name="no_self_complaint"),
        Index("ix_complaints_status_created_at", "status", "created_at"),
        Index("ix_complaints_target_user_id", "target_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("complaint_reasons.id", ondelete="RESTRICT"),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moderator_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    moderator_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class StopWord(Base, TimestampMixin):
    """Стоп-слово или regex-паттерн для текстовой модерации.

    Редактируется только из админского режима бота. Никогда не из кода/env.
    Кэшируется в Redis на 60 сек с версионированием.
    """

    __tablename__ = "stop_words"
    __table_args__ = (
        UniqueConstraint("pattern", "kind", name="uq_stop_words_pattern_kind"),
        CheckConstraint("kind IN ('word', 'regex')", name="kind_allowed"),
        CheckConstraint(
            "category IN ('hate_speech', 'link', 'adult_keyword', 'other')",
            name="category_allowed",
        ),
        Index("ix_stop_words_kind_is_active", "kind", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Кто последним редактировал; нужно для аудита в админском режиме ().
    updated_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ContentModerationLog(Base):
    """Аудит-журнал всех решений контент-модерации (текст и NSFW).

    Не FK на target — типы сущностей разные (profile_id / like_id / post_id / ...).
    target_kind однозначно определяет, в какой таблице искать target_id.
    """

    __tablename__ = "content_moderation_log"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('profile_bio', 'profile_nickname', 'profile_media', "
            "'like_message', 'creator_post_text', 'creator_post_photo', "
            "'complaint_comment', 'feed_post', 'feed_comment', 'feed_media', "
            "'profile_city')",
            name="target_kind_allowed",
        ),
        CheckConstraint("check_type IN ('text', 'nsfw_image')", name="check_type_allowed"),
        CheckConstraint(
            "decision IN ('approved', 'manual_review', 'rejected')",
            name="decision_allowed",
        ),
        Index(
            "ix_content_moderation_log_user_id_created_at",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_content_moderation_log_target_kind_decision",
            "target_kind",
            "decision",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_type: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    nsfw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_terms: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
