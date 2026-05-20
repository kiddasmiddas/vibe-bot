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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampMixin


class CreatorPost(Base, TimestampMixin):
    """Рекламный пост креатора в «Аллее креаторов» (Mini App).

    Создаётся админом после ручной модерации и оплаты. Истекает по `expires_at` —
    шедулер выставляет `is_published=False`. `is_premium_post=True` означает
    расширенную карточку (несколько фото, музыка).
    """

    __tablename__ = "creator_posts"
    __table_args__ = (
        Index(
            "ix_creator_posts_is_published_expires_at",
            "is_published",
            "expires_at",
        ),
        Index("ix_creator_posts_category_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Автор может отсутствовать в боте — оставляем NULL и используем display_name.
    author_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # RESTRICT: нельзя удалять категорию, если на неё ссылаются посты.
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("creator_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_link: Mapped[str] = mapped_column(String(256), nullable=False)
    is_premium_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    music_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Контент-модерация: пост ждёт ручной проверки админа (NSFW manual_review
    # на любой из фотографий или подозрительный текст). В Mini App ленте не показывается.
    is_pending_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class CreatorPostPhoto(Base):
    """Фото поста креатора. 1 у обычного, до 3 у Premium-поста."""

    __tablename__ = "creator_post_photos"
    __table_args__ = (
        UniqueConstraint("post_id", "position", name="post_id_position"),
        CheckConstraint("position >= 0 AND position <= 2", name="position_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("creator_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Контент-модерация: NSFW score попал в «серую зону». Сам пост может оставаться
    # видимым, но конкретное фото не показываем до решения админа.
    is_pending_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class CreatorSubmission(Base):
    """Заявка пользователя на размещение в Аллее.

    TODO (этап админки/креаторов, ): сейчас по ТЗ заявки идут
    напрямую модератору. Эта таблица — задел на случай, если решат завести
    собственный流ow приёма заявок без выхода из бота.
    """

    __tablename__ = "creator_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
