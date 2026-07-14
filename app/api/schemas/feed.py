from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Допустимые типы медиа на ВХОДЕ (что отдаёт /api/feed/upload). На выходе схемы
# оставляем str — в БД могут быть легаси-значения, строгий Literal уронил бы
# сериализацию ответа.
MediaTypeIn = Literal["photo", "gif"]


class FeedPostPreview(BaseModel):
    """Краткая карточка поста для ленты."""

    id: int
    author_name: str
    text: str
    created_at: str  # ISO 8601
    first_photo_file_id: str | None

    model_config = {"from_attributes": True}


class ReactionCounts(BaseModel):
    heart: int = 0
    sparkle: int = 0
    cry: int = 0
    eyes: int = 0


class MediaItem(BaseModel):
    """Медиа в ОТВЕТЕ (из БД). media_type — str, чтобы не падать на легаси."""

    media_type: str
    file_id: str


class MediaItemIn(BaseModel):
    """Медиа во ВХОДЯЩЕМ запросе (создание/редактирование поста).

    media_type валидируется строго — отвергаем всё, кроме photo/gif, ещё на
    десериализации (раньше можно было сохранить произвольную строку ≤16 симв.).
    """

    media_type: MediaTypeIn
    file_id: str


class FeedPostDetail(BaseModel):
    """Полная карточка поста."""

    id: int
    author_id: int | None  # User.id автора — фронт сравнивает с current_user для UI edit-кнопки
    author_name: str
    text: str
    created_at: str  # ISO 8601
    photos: list[str]  # file_id в порядке position (для просмотра)
    media: list[MediaItem]  # полный набор медиа с media_type — для редактирования
    expires_at: str | None  # ISO 8601; None = пост живёт вечно (ttl=0)
    reactions: ReactionCounts
    my_reaction: str | None

    model_config = {"from_attributes": True}


class FeedResponse(BaseModel):
    """Ответ ленты с курсорной пагинацией."""

    items: list[FeedPostPreview]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Write: request/response схемы
# ---------------------------------------------------------------------------


class CreatePostRequest(BaseModel):
    text: str
    media: list[MediaItemIn] = []


class CreatePostResponse(BaseModel):
    id: int
    # True — пост ушёл на премодерацию, появится в ленте после одобрения.
    pending_review: bool = False


class UpdatePostRequest(BaseModel):
    """Запрос на редактирование поста Ленты (Волна 3).

    - `text` — новый текст (обязателен, как и при создании).
    - `media` — None ⇒ медиа не меняем; пустой список ⇒ удалить все медиа;
      непустой список ⇒ заменить набор медиа целиком в указанном порядке.
    """

    text: str
    media: list[MediaItemIn] | None = None


class CreateCommentRequest(BaseModel):
    text: str | None = None
    media_type: MediaTypeIn | None = None
    media_file_id: str | None = None
    # id комментария, на который отвечают (ветки глубины 1).
    parent_id: int | None = None


class CreateCommentResponse(BaseModel):
    id: int


class CommentItem(BaseModel):
    id: int
    author_name: str
    text: str | None
    media_type: str | None
    media_file_id: str | None
    created_at: str  # ISO 8601
    parent_id: int | None = None
    # Ответы ветки (глубина 1); у самих ответов список всегда пуст.
    replies: list[CommentItem] = []

    model_config = {"from_attributes": True}


class CommentsResponse(BaseModel):
    items: list[CommentItem]
    next_cursor: str | None


class SetReactionRequest(BaseModel):
    reaction_type: str


class ReactionResponse(BaseModel):
    counts: ReactionCounts
    my_reaction: str | None


class UploadMediaResponse(BaseModel):
    """Ответ на загрузку медиа-файла через бота."""

    file_id: str
    media_type: str  # "photo" | "gif"
