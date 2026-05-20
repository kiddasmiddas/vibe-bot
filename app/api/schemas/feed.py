from __future__ import annotations

from pydantic import BaseModel


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


class FeedPostDetail(BaseModel):
    """Полная карточка поста."""

    id: int
    author_name: str
    text: str
    created_at: str  # ISO 8601
    photos: list[str]  # file_id в порядке position
    expires_at: str  # ISO 8601
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


class MediaItem(BaseModel):
    media_type: str
    file_id: str


class CreatePostRequest(BaseModel):
    text: str
    media: list[MediaItem] = []


class CreatePostResponse(BaseModel):
    id: int
    # True — пост ушёл на премодерацию, появится в ленте после одобрения.
    pending_review: bool = False


class CreateCommentRequest(BaseModel):
    text: str | None = None
    media_type: str | None = None
    media_file_id: str | None = None


class CreateCommentResponse(BaseModel):
    id: int


class CommentItem(BaseModel):
    id: int
    author_name: str
    text: str | None
    media_type: str | None
    media_file_id: str | None
    created_at: str  # ISO 8601

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
