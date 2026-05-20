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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Допустимые виды лайков.
LIKE_KINDS: tuple[str, ...] = ("like", "superlike")


class Like(Base):
    """Исходящий лайк от одного пользователя к другому."""

    __tablename__ = "likes"
    __table_args__ = (
        UniqueConstraint("from_user_id", "to_user_id", name="uq_likes_from_to"),
        CheckConstraint("kind IN ('like', 'superlike')", name="kind_allowed"),
        CheckConstraint("from_user_id <> to_user_id", name="no_self_like"),
        Index("ix_likes_to_user_id", "to_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Dislike(Base):
    """Дизлайк (скип) пользователя — чтобы больше не показывать."""

    __tablename__ = "dislikes"
    __table_args__ = (
        UniqueConstraint("from_user_id", "to_user_id", name="uq_dislikes_from_to"),
        CheckConstraint("from_user_id <> to_user_id", name="no_self_dislike"),
        Index("ix_dislikes_from_user_id", "from_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Match(Base):
    """Состоявшийся мэтч. Пара хранится упорядоченно: user_a_id < user_b_id."""

    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("user_a_id", "user_b_id", name="uq_matches_user_a_user_b"),
        CheckConstraint("user_a_id < user_b_id", name="user_a_lt_user_b"),
        Index("ix_matches_user_a_id", "user_a_id"),
        Index("ix_matches_user_b_id", "user_b_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_a_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_b_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    initial_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ViewedProfile(Base):
    """Журнал просмотров: какие анкеты юзер уже видел, чтобы не показывать повторно."""

    __tablename__ = "viewed_profiles"

    viewer_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Block(Base):
    """Блокировка одного пользователя другим."""

    __tablename__ = "blocks"
    __table_args__ = (CheckConstraint("blocker_user_id <> blocked_user_id", name="no_self_block"),)

    blocker_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blocked_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
