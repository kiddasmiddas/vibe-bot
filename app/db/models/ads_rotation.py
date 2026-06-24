"""Авто-реклама с ротацией в ленте анкет (показывается после каждой N-й анкеты).

Пул креативов крутится по кругу (round-robin по `last_shown_at`). Управляется
из админки. Премиум-пользователи рекламу не видят (см. `ads_rotation_service`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Допустимые типы медиа креатива.
AD_ROTATION_MEDIA_TYPES: tuple[str, ...] = ("photo", "video", "animation")
# Допустимые цели кнопки «Перейти»: url — внешняя ссылка, premium — экран тарифов в боте.
AD_ROTATION_BUTTON_TARGETS: tuple[str, ...] = ("url", "premium")


class AdRotationPost(Base):
    """Креатив авто-рекламы для показа в ленте анкет.

    Поля кнопки опциональны: если `button_label` пуст — у юзера показывается только
    «Не интересно». Если задан — рядом появляется кнопка с этим текстом, ведущая на
    внешнюю ссылку (`button_target='url'`, `button_url`) или на экран покупки Premium
    (`button_target='premium'`).
    """

    __tablename__ = "ad_rotation_posts"
    __table_args__ = (
        CheckConstraint(
            "media_type IS NULL OR media_type IN ('photo', 'video', 'animation')",
            name="ad_rotation_media_type_allowed",
        ),
        CheckConstraint(
            "button_target IS NULL OR button_target IN ('url', 'premium')",
            name="ad_rotation_button_target_allowed",
        ),
        # Внешняя кнопка-ссылка обязана нести URL; для premium-цели URL не нужен.
        CheckConstraint(
            "button_target IS DISTINCT FROM 'url' OR button_url IS NOT NULL",
            name="ad_rotation_url_target_needs_url",
        ),
        # Креатив не может быть пустым: нужен текст или медиа.
        CheckConstraint(
            "text IS NOT NULL OR media_file_id IS NOT NULL",
            name="ad_rotation_text_or_media",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    button_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_target: Mapped[str | None] = mapped_column(String(16), nullable=True)
    button_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    shown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
