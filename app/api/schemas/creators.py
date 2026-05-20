from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreatorPostPreview(BaseModel):
    """Краткая карточка поста для ленты Mini App."""

    id: int
    author_display_name: str
    category_id: int
    category_title: str
    first_photo_file_id: str | None
    title: str  # первые 80 символов description
    expires_at: datetime | None
    is_premium_post: bool

    model_config = {"from_attributes": True}


class CreatorPostDetail(BaseModel):
    """Полная карточка поста: открывается при тапе на карточку в ленте."""

    id: int
    author_display_name: str
    category_id: int
    category_title: str
    photos: list[str]  # file_id фотографий в порядке position
    description: str
    telegram_link: str
    music_file_id: str | None
    expires_at: datetime | None
    is_premium_post: bool

    model_config = {"from_attributes": True}


class FeedResponse(BaseModel):
    """Ответ ленты с курсорной пагинацией."""

    items: list[CreatorPostPreview]
    next_cursor: str | None
