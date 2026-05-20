from __future__ import annotations

import base64
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.db import get_db_session
from app.api.deps import current_user
from app.api.media import resolve_file_url, resolve_many
from app.api.schemas.creators import CreatorPostDetail, CreatorPostPreview, FeedResponse
from app.cache import get_redis
from app.config import settings
from app.db.models.dictionaries import CreatorCategory
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.creator_repo import CreatorRepository
from app.services.analytics_events import EventType

router = APIRouter()

_MAX_LIMIT = 50
_CURSOR_SEP = "|"


def _encode_cursor(published_at: datetime, post_id: int) -> str:
    """Кодирует курсор в base64-строку `"{iso}|{id}"`."""
    raw = f"{published_at.isoformat()}{_CURSOR_SEP}{post_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int] | None:
    """Декодирует курсор.  Возвращает None при любой ошибке."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.rsplit(_CURSOR_SEP, 1)
        return datetime.fromisoformat(ts_str), int(id_str)
    except Exception:
        return None


async def _log_miniapp_opened_once(user_id: int, db: AsyncSession) -> None:
    """Логирует EventType.MINIAPP_OPENED один раз в сессию.

    TTL Redis-ключа = settings.miniapp_session_ttl_seconds.
    """
    redis = get_redis()
    redis_key = f"miniapp_session:{user_id}"
    try:
        already = await redis.get(redis_key)
        if already:
            return
        await redis.set(redis_key, "1", ex=settings.miniapp_session_ttl_seconds)
    except Exception as exc:
        # Без рабочего Redis мы не можем гарантировать дедупликацию — лучше
        # вообще не писать аналитику, чем спамить её при каждом запросе.
        logger.warning("redis error checking miniapp session key, skip analytics: {}", exc)
        return

    try:
        analytics = AnalyticsRepository(db)
        await analytics.log_event(user_id, EventType.MINIAPP_OPENED)
    except Exception as exc:
        logger.warning("analytics log_event failed for MINIAPP_OPENED: {}", exc)


async def _get_category_title(db: AsyncSession, category_id: int) -> str:
    result = await db.get(CreatorCategory, category_id)
    return result.title if result else ""


async def _get_category_titles_batch(db: AsyncSession, category_ids: list[int]) -> dict[int, str]:
    """Загружает заголовки категорий одним запросом."""
    if not category_ids:
        return {}
    stmt = select(CreatorCategory).where(CreatorCategory.id.in_(category_ids))
    rows = list((await db.execute(stmt)).scalars().all())
    return {cat.id: cat.title for cat in rows}


@router.get("/api/creators/feed", response_model=FeedResponse)
async def feed(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FeedResponse:
    """Лента опубликованных постов с курсорной пагинацией.

    Возвращает только `is_published=True AND expires_at > now() AND is_pending_review=False`.
    Аналитическое событие MINIAPP_OPENED логируется один раз за сессию (TTL Redis-ключа
    определяется `settings.miniapp_session_ttl_seconds`).
    """
    await _log_miniapp_opened_once(user.id, db)

    decoded_cursor = _decode_cursor(cursor) if cursor else None
    repo = CreatorRepository(db)
    posts, next_raw = await repo.list_published_cursor(cursor=decoded_cursor, limit=limit)

    category_ids = list({p.category_id for p in posts})
    cat_titles = await _get_category_titles_batch(db, category_ids)

    photos_by_post = await repo.get_photos_for_posts([p.id for p in posts])

    items: list[CreatorPostPreview] = []
    for post in posts:
        first_photo = photos_by_post.get(post.id, [])
        raw_file_id = first_photo[0].file_id if first_photo else None
        first_photo_file_id = await resolve_file_url(raw_file_id)
        items.append(
            CreatorPostPreview(
                id=post.id,
                author_display_name=post.author_display_name,
                category_id=post.category_id,
                category_title=cat_titles.get(post.category_id, ""),
                first_photo_file_id=first_photo_file_id,
                title=post.description[:80],
                expires_at=post.expires_at,
                is_premium_post=post.is_premium_post,
            )
        )

    next_cursor: str | None = None
    if next_raw is not None:
        next_cursor = _encode_cursor(next_raw[0], next_raw[1])

    return FeedResponse(items=items, next_cursor=next_cursor)


@router.get("/api/creators/{post_id}", response_model=CreatorPostDetail)
async def get_post(
    post_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CreatorPostDetail:
    """Детали поста.

    404 если пост не существует, is_published=False, expires_at < now() или is_pending_review=True.
    """
    repo = CreatorRepository(db)
    post = await repo.get_by_id(post_id)

    now = datetime.now(tz=UTC)
    if (
        post is None
        or not post.is_published
        or post.is_pending_review
        or (post.expires_at is not None and post.expires_at <= now)
    ):
        raise HTTPException(status_code=404, detail="Post not found")

    photos = await repo.get_photos_for_post(post_id)
    cat_title = await _get_category_title(db, post.category_id)

    return CreatorPostDetail(
        id=post.id,
        author_display_name=post.author_display_name,
        category_id=post.category_id,
        category_title=cat_title,
        photos=await resolve_many([p.file_id for p in photos]),
        description=post.description,
        telegram_link=post.telegram_link,
        music_file_id=post.music_file_id,
        expires_at=post.expires_at,
        is_premium_post=post.is_premium_post,
    )
