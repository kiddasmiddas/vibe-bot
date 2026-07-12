from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FeedPost(Base):
    """Пост пользователя в Ленте Mini App.

    Создаётся из Mini App (Premium + анкета). Истекает по `expires_at` через 48 ч.
    Статусы: active / expired / hidden_by_moderator / deleted_by_user / blocked.
    """

    __tablename__ = "feed_posts"
    __table_args__ = (
        Index(
            "ix_feed_posts_status_published_at",
            "status",
            "published_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Денормализовано для простоты среза просмотра (не джойнить users при каждом запросе).
    author_name: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_pending_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Волна 3: время последнего редактирования автором. Меняется явно из FeedService,
    # без onupdate=, чтобы случайные UPDATE на статусе/флагах не сдвигали значение.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class FeedPostMedia(Base):
    """Медиафайл поста ленты. CASCADE при удалении поста."""

    __tablename__ = "feed_post_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("feed_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class FeedComment(Base):
    """Комментарий к посту ленты.

    Содержит либо текст, либо медиа (CHECK-констрейнт `feed_comment_text_or_media`).
    Статусы: active / deleted_by_user / deleted_by_moderator.
    """

    __tablename__ = "feed_comments"
    __table_args__ = (
        CheckConstraint(
            "text IS NOT NULL OR (media_type IS NOT NULL AND media_file_id IS NOT NULL)",
            name="feed_comment_text_or_media",
        ),
        Index("ix_feed_comments_post_id_created_at", "post_id", "created_at"),
        Index("ix_feed_comments_parent_comment_id", "parent_comment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("feed_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Ветки глубины 1: у ответа здесь ВСЕГДА id корневого комментария поста
    # (ответ на ответ сервис прикрепляет к тому же корню, как в VK).
    parent_comment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("feed_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FeedReaction(Base):
    """Реакция пользователя на пост ленты.

    Составной PK (post_id, user_id) — одна реакция на юзера на пост.
    Смена типа — UPSERT. Типы: heart / sparkle / cry / eyes.
    """

    __tablename__ = "feed_reactions"

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("feed_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FeedCommentRestriction(Base):
    """Ограничение пользователя в комментариях до указанного времени.

    PK — user_id (одно активное ограничение на пользователя).
    Устанавливается модератором через админку.
    """

    __tablename__ = "feed_comment_restrictions"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
