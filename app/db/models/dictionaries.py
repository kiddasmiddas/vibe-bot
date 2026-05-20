from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import DictionaryMixin


class Gender(Base, DictionaryMixin):
    __tablename__ = "genders"


class Fandom(Base, DictionaryMixin):
    __tablename__ = "fandoms"


class Interest(Base, DictionaryMixin):
    __tablename__ = "interests"


class CreatorCategory(Base, DictionaryMixin):
    __tablename__ = "creator_categories"


class Vibe(Base, DictionaryMixin):
    __tablename__ = "vibes"

    # Уникальный пользовательский номер вайба (для выбора по цифре в боте).
    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    # Telegram file_id картинки вайба, отправляемой пользователю.
    # nullable=True — реальные file_id загружает админ; до загрузки хранится None.
    image_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ComplaintReason(Base, DictionaryMixin):
    __tablename__ = "complaint_reasons"
