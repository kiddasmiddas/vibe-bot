from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampMixin

# Допустимые значения для Profile.main_media_type.
MAIN_MEDIA_TYPES: tuple[str, ...] = ("photo", "video", "gif")


class Profile(Base, TimestampMixin):
    """Анкета пользователя. 1-к-1 с User."""

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("age >= 0", name="age_non_negative"),
        CheckConstraint(
            "looking_for_age_min <= looking_for_age_max",
            name="looking_for_age_range_valid",
        ),
        CheckConstraint(
            "main_media_type IN ('photo', 'video', 'gif')",
            name="main_media_type_allowed",
        ),
        Index("ix_profiles_age", "age"),
        Index("ix_profiles_city", "city"),
        Index("ix_profiles_is_active_is_hidden", "is_active", "is_hidden"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("genders.id", ondelete="RESTRICT"),
        nullable=False,
    )

    looking_for_age_min: Mapped[int] = mapped_column(Integer, nullable=False)
    looking_for_age_max: Mapped[int] = mapped_column(Integer, nullable=False)

    bio: Mapped[str] = mapped_column(Text, nullable=False)

    city: Mapped[str | None] = mapped_column(String(80), nullable=True)

    own_vibe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("vibes.id", ondelete="RESTRICT"),
        nullable=False,
    )

    main_media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    main_media_file_id: Mapped[str] = mapped_column(String(256), nullable=False)

    # Premium-only поля.
    music_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    video_note_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Контент-модерация: NSFW score попал в «серую зону» → ждёт админа.
    # Анкеты с этим флагом не показываются в мэтчинге.
    is_pending_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Флаг: пользователю нужно переподтвердить выбор вайбов после расширения сетки до 36.
    vibes_need_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class ProfileLookingForGender(Base):
    """M2M: кого ищет пользователь по полу."""

    __tablename__ = "profile_looking_for_genders"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    gender_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("genders.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ProfileFandom(Base):
    """M2M: фандомы пользователя."""

    __tablename__ = "profile_fandoms"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fandom_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fandoms.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ProfileDesiredFandom(Base):
    """M2M: фандомы, которые хотел бы видеть у собеседника."""

    __tablename__ = "profile_desired_fandoms"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fandom_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fandoms.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ProfileDesiredVibe(Base):
    """M2M: вайбы, которые хотел бы видеть у собеседника."""

    __tablename__ = "profile_desired_vibes"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vibe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("vibes.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ProfileInterest(Base):
    """M2M: интересы пользователя."""

    __tablename__ = "profile_interests"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    interest_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("interests.id", ondelete="CASCADE"),
        primary_key=True,
    )
