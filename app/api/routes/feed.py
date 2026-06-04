from __future__ import annotations

import base64
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.types import BufferedInputFile
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.db import get_db_session
from app.api.deps import (
    current_premium_user_with_profile,
    current_user,
    current_user_with_profile,
)
from app.api.media import resolve_file_url, resolve_many
from app.api.schemas.feed import (
    CommentItem,
    CommentsResponse,
    CreateCommentRequest,
    CreateCommentResponse,
    CreatePostRequest,
    CreatePostResponse,
    FeedPostDetail,
    FeedPostPreview,
    FeedResponse,
    MediaItem,
    ReactionCounts,
    ReactionResponse,
    SetReactionRequest,
    UpdatePostRequest,
    UploadMediaResponse,
)
from app.bot.utils.admin_notify import notify_admins_feed_post_pending
from app.cache import get_redis
from app.config import settings
from app.db.models.profile import Profile
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.services.content_moderation_service import ContentModerationService
from app.services.feed_service import FeedService, FeedServiceError

router = APIRouter()

_MAX_LIMIT = 50
_CURSOR_SEP = "|"

# Redis rate-limit: не более 10 мутаций за 10 секунд на пользователя
_RL_WINDOW_SECONDS = 10
_RL_MAX_REQUESTS = 10

# Upload constraints
_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 МБ

# Singleton Bot для upload-эндпоинта (переиспользуем сессию, не создаём на запрос)
_upload_bot: Bot | None = None


def _get_upload_bot() -> Bot:
    global _upload_bot
    if _upload_bot is None:
        _upload_bot = Bot(token=settings.bot_token)
    return _upload_bot


def _encode_cursor(published_at: datetime, post_id: int) -> str:
    """Кодирует курсор в base64-строку `"{iso}|{id}"`."""
    raw = f"{published_at.isoformat()}{_CURSOR_SEP}{post_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int] | None:
    """Декодирует курсор. Возвращает None при любой ошибке."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.rsplit(_CURSOR_SEP, 1)
        return datetime.fromisoformat(ts_str), int(id_str)
    except Exception:
        return None


async def _check_rate_limit(user_id: int) -> None:
    """Простой Redis-троттл для write-эндпоинтов.

    При недоступности Redis — пропускаем (graceful degradation).
    """
    redis = get_redis()
    key = f"feed_write_rl:{user_id}"
    try:
        count_raw = await redis.get(key)
        count = int(count_raw) if count_raw else 0
        if count >= _RL_MAX_REQUESTS:
            raise HTTPException(status_code=429, detail="Too many requests")
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _RL_WINDOW_SECONDS)
        await pipe.execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("feed write rate-limit redis error, skipping: {}", exc)


def _build_feed_service(db: AsyncSession) -> FeedService:
    redis = get_redis()
    settings_repo = SettingsRepository(db, redis)
    analytics_repo = AnalyticsRepository(db)
    mod_repo = ModerationRepository(db, redis)
    moderation_service = ContentModerationService(mod_repo, settings_repo)
    return FeedService(
        db,
        feed_repo=FeedRepository(db),
        settings_repo=settings_repo,
        analytics_repo=analytics_repo,
        moderation_service=moderation_service,
    )


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------


@router.post("/api/feed/upload", response_model=UploadMediaResponse)
async def upload_feed_media(
    file: UploadFile = File(...),
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> UploadMediaResponse:
    """Загрузить медиа-файл через бота и получить Telegram file_id.

    Фронт отправляет multipart/form-data с полем `file`.
    Бэк читает байты, передаёт их боту через BufferedInputFile, получает file_id,
    после чего прогоняет через NSFW-проверку ().

    Ограничения:
    - content_type: image/jpeg | image/png | image/webp | image/gif
    - размер: не более 5 МБ

    Возвращает {file_id, media_type: "photo"|"gif"}.
    422 если NSFW-проверка отклонила изображение.
    502 при ошибке Telegram API.
    """
    user, _profile = pair
    await _check_rate_limit(user.id)

    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {content_type}. Allowed: jpeg, png, webp, gif",
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="File too large. Maximum size is 5 MB")

    filename = file.filename or "upload"
    is_gif = content_type == "image/gif"
    bot = _get_upload_bot()

    # Предпочитаем выделенный staging-чат — личка админов не должна засоряться
    # пользовательскими загрузками. Legacy-fallback на admin[0] оставлен, чтобы
    # старые деплои не разваливались, если оператор забыл прописать новый env.
    staging_chat_id = settings.media_staging_chat_id
    if staging_chat_id is not None:
        chat_id = staging_chat_id
    else:
        admin_ids = settings.admin_telegram_ids
        if admin_ids:
            logger.warning(
                "MEDIA_STAGING_CHAT_ID is not set — falling back to ADMIN_TELEGRAM_IDS[0] "
                "for /api/feed/upload. Configure a dedicated staging chat to stop spamming admins."
            )
            chat_id = admin_ids[0]
        else:
            logger.error(
                "Neither MEDIA_STAGING_CHAT_ID nor ADMIN_TELEGRAM_IDS configured — "
                "cannot upload media via bot"
            )
            raise HTTPException(status_code=503, detail="Media upload not configured")

    try:
        if is_gif:
            msg = await bot.send_animation(
                chat_id=chat_id,
                animation=BufferedInputFile(data, filename=filename),
            )
            if msg.animation is None:
                raise HTTPException(status_code=502, detail="Telegram returned no animation")
            file_id = msg.animation.file_id
            media_type = "gif"
        else:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(data, filename=filename),
            )
            if not msg.photo:
                raise HTTPException(status_code=502, detail="Telegram returned no photo")
            file_id = msg.photo[-1].file_id
            media_type = "photo"
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Telegram upload failed for user_id={}: {}", user.id, exc)
        raise HTTPException(status_code=502, detail="Failed to upload media to Telegram") from exc

    # NSFW-проверка (, §15.3). Байты уже прочитаны — передаём их напрямую.
    # NudeNet недоступен в dev → check_image вернёт manual_review (graceful fallback).
    redis = get_redis()
    settings_repo = SettingsRepository(db, redis)
    mod_repo = ModerationRepository(db, redis)
    moderation_service = ContentModerationService(mod_repo, settings_repo)
    nsfw_result = await moderation_service.check_image(
        data,
        target_kind="feed_media",
        user_id=user.id,
    )
    if nsfw_result.decision == "rejected":
        raise HTTPException(status_code=422, detail="Media rejected: NSFW content detected")
    if nsfw_result.decision == "manual_review":
        logger.warning("feed_media upload manual_review: user_id={} file_id={}", user.id, file_id)

    return UploadMediaResponse(file_id=file_id, media_type=media_type)


# ---------------------------------------------------------------------------
# Read endpoints (unchanged logic, extended GET /api/feed/posts/{id})
# ---------------------------------------------------------------------------


@router.get("/api/feed/posts", response_model=FeedResponse)
async def feed_posts(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FeedResponse:
    """Лента активных постов с курсорной пагинацией.

    Возвращает только `status='active' AND expires_at > now() AND published_at IS NOT NULL`.
    """
    # ТЗ п.8: без заполненной анкеты — только превью ограниченного объёма.
    profile = await ProfileRepository(db).get_by_user_id(user.id)
    if profile is None or not profile.is_completed:
        preview_limit = await SettingsRepository(db).get_int("feed_preview_limit_no_profile")
        limit = min(limit, preview_limit if preview_limit is not None else 10)

    decoded_cursor = _decode_cursor(cursor) if cursor else None
    repo = FeedRepository(db)
    posts, next_raw = await repo.list_active_cursor(cursor=decoded_cursor, limit=limit)

    photos_by_post = await repo.get_photos_for_posts([p.id for p in posts])

    items: list[FeedPostPreview] = []
    for post in posts:
        media_list = photos_by_post.get(post.id, [])
        raw_file_id = media_list[0].file_id if media_list else None
        first_photo_url = await resolve_file_url(raw_file_id)
        items.append(
            FeedPostPreview(
                id=post.id,
                author_name=post.author_name,
                text=post.text,
                created_at=post.created_at.isoformat(),
                first_photo_file_id=first_photo_url,
            )
        )

    next_cursor: str | None = None
    if next_raw is not None:
        next_cursor = _encode_cursor(next_raw[0], next_raw[1])

    return FeedResponse(items=items, next_cursor=next_cursor)


@router.get("/api/feed/posts/{post_id}", response_model=FeedPostDetail)
async def get_feed_post(
    post_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FeedPostDetail:
    """Детали поста, включая счётчики реакций и моя реакция.

    404 если пост не существует, status != 'active' или expires_at < now().
    """
    repo = FeedRepository(db)
    post = await repo.get_by_id(post_id)

    now = datetime.now(tz=UTC)
    if (
        post is None
        or post.status != "active"
        or (post.expires_at is not None and post.expires_at <= now)
    ):
        raise HTTPException(status_code=404, detail="Post not found")

    photos = await repo.get_photos_for_post(post_id)

    raw_counts = await repo.count_reactions_by_post(post_id)
    counts = ReactionCounts(
        heart=raw_counts.get("heart", 0),
        sparkle=raw_counts.get("sparkle", 0),
        cry=raw_counts.get("cry", 0),
        eyes=raw_counts.get("eyes", 0),
    )

    my_reaction_obj = await repo.get_user_reaction(post_id, user.id)
    my_reaction = my_reaction_obj.reaction_type if my_reaction_obj else None

    # expires_at гарантированно не None: пост active и не истёк (проверено выше).
    if post.expires_at is None:
        raise HTTPException(status_code=500, detail="Post missing expires_at")

    return FeedPostDetail(
        id=post.id,
        author_id=post.author_user_id,
        author_name=post.author_name,
        text=post.text,
        created_at=post.created_at.isoformat(),
        photos=await resolve_many([m.file_id for m in photos]),
        media=[MediaItem(media_type=m.media_type, file_id=m.file_id) for m in photos],
        expires_at=post.expires_at.isoformat(),
        reactions=counts,
        my_reaction=my_reaction,
    )


# ---------------------------------------------------------------------------
# Comments read
# ---------------------------------------------------------------------------


@router.get("/api/feed/posts/{post_id}/comments", response_model=CommentsResponse)
async def list_comments(
    post_id: int,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=_MAX_LIMIT),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CommentsResponse:
    """Комментарии поста с курсорной пагинацией (только status='active')."""
    decoded_cursor = _decode_cursor(cursor) if cursor else None
    repo = FeedRepository(db)
    comments, next_raw = await repo.list_comments_cursor(
        post_id=post_id, cursor=decoded_cursor, limit=limit
    )

    # FeedComment не хранит author_name — загружаем из Profile по author_user_id.
    author_ids = list({c.author_user_id for c in comments})
    profile_repo = ProfileRepository(db)
    author_names: dict[int, str] = {}
    for aid in author_ids:
        p = await profile_repo.get_by_user_id(aid)
        author_names[aid] = p.nickname if (p and p.nickname) else "Deleted"

    items = [
        CommentItem(
            id=c.id,
            author_name=author_names.get(c.author_user_id, "Unknown"),
            text=c.text,
            media_type=c.media_type,
            media_file_id=c.media_file_id,
            created_at=c.created_at.isoformat(),
        )
        for c in comments
    ]

    next_cursor: str | None = None
    if next_raw is not None:
        next_cursor = _encode_cursor(next_raw[0], next_raw[1])

    return CommentsResponse(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


@router.post("/api/feed/posts", response_model=CreatePostResponse, status_code=201)
async def create_post(
    body: CreatePostRequest,
    pair: tuple[User, Profile] = Depends(current_premium_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> CreatePostResponse:
    """Создать пост (только Premium + завершённая анкета).

    403 если не Premium / нет анкеты.
    422 если лимит исчерпан или текст содержит ссылку.
    """
    user, profile = pair
    await _check_rate_limit(user.id)

    svc = _build_feed_service(db)
    try:
        post_id, pending_review = await svc.create_post(
            user=user,
            profile=profile,
            text=body.text,
            media=[{"media_type": m.media_type, "file_id": m.file_id} for m in body.media],
        )
    except FeedServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Пост ушёл на премодерацию — присылаем админам карточку с фото, чтобы
    # они оперативно одобрили/скрыли его через /admin → «Лента» → «На проверке».
    # Сбой уведомления не должен ломать создание поста.
    if pending_review:
        first_media = body.media[0] if body.media else None
        try:
            await notify_admins_feed_post_pending(
                _get_upload_bot(),
                author_name=profile.nickname,
                telegram_id=user.telegram_id,
                text=body.text,
                media_type=first_media.media_type if first_media else None,
                media_file_id=first_media.file_id if first_media else None,
                db_session=db,
            )
        except Exception as exc:
            logger.warning("feed post pending admin-notify failed: {}", exc)

    return CreatePostResponse(id=post_id, pending_review=pending_review)


@router.put("/api/feed/posts/{post_id}", response_model=FeedPostDetail)
async def update_feed_post(
    post_id: int,
    body: UpdatePostRequest,
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> FeedPostDetail:
    """Редактировать свой пост (Волна 3).

    - 403 — не автор поста / нет анкеты.
    - 404 — пост не найден.
    - 409 — пост в статусе, в котором редактирование запрещено
      (blocked / hidden_by_moderator / expired / deleted_by_user).
    - 422 — текст не прошёл модерацию (ссылка / стоп-слово).

    При фактическом изменении (текст или медиа) пост уходит в pending_review=True;
    уведомление админам отправляется через notify_admins_feed_post_pending
    (graceful — сбой не ломает 200-ответ).
    expires_at НЕ сбрасывается: 48-часовой таймер по ТЗ идёт от created_at.
    """
    user, profile = pair
    await _check_rate_limit(user.id)

    svc = _build_feed_service(db)
    media_payload: list[dict[str, str]] | None
    if body.media is None:
        media_payload = None
    else:
        media_payload = [{"media_type": m.media_type, "file_id": m.file_id} for m in body.media]

    try:
        updated_post, changed = await svc.update_post(
            user=user,
            post_id=post_id,
            text=body.text,
            media=media_payload,
        )
    except FeedServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    repo = FeedRepository(db)
    photos = await repo.get_photos_for_post(post_id)

    # Уведомляем админов только когда РЕАЛЬНО применили изменения — no-op
    # (повторный submit того же контента) не должен пере-спамить очередь.
    if changed:
        first_media = photos[0] if photos else None
        try:
            await notify_admins_feed_post_pending(
                _get_upload_bot(),
                author_name=profile.nickname,
                telegram_id=user.telegram_id,
                text=updated_post.text,
                media_type=first_media.media_type if first_media else None,
                media_file_id=first_media.file_id if first_media else None,
                db_session=db,
            )
        except Exception as exc:
            logger.warning("feed post edit admin-notify failed: {}", exc)

    # Возвращаем актуальную карточку — фронт сразу видит изменённый text/photos.
    raw_counts = await repo.count_reactions_by_post(post_id)
    counts = ReactionCounts(
        heart=raw_counts.get("heart", 0),
        sparkle=raw_counts.get("sparkle", 0),
        cry=raw_counts.get("cry", 0),
        eyes=raw_counts.get("eyes", 0),
    )
    my_reaction_obj = await repo.get_user_reaction(post_id, user.id)
    my_reaction = my_reaction_obj.reaction_type if my_reaction_obj else None

    if updated_post.expires_at is None:
        raise HTTPException(status_code=500, detail="Post missing expires_at")

    return FeedPostDetail(
        id=updated_post.id,
        author_id=updated_post.author_user_id,
        author_name=updated_post.author_name,
        text=updated_post.text,
        created_at=updated_post.created_at.isoformat(),
        photos=await resolve_many([m.file_id for m in photos]),
        media=[MediaItem(media_type=m.media_type, file_id=m.file_id) for m in photos],
        expires_at=updated_post.expires_at.isoformat(),
        reactions=counts,
        my_reaction=my_reaction,
    )


@router.post(
    "/api/feed/posts/{post_id}/comments",
    response_model=CreateCommentResponse,
    status_code=201,
)
async def create_comment(
    post_id: int,
    body: CreateCommentRequest,
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> CreateCommentResponse:
    """Создать комментарий (анкета обязательна).

    403 нет анкеты / ограничен в комментариях.
    422 лимит / ссылка / медиа от non-premium / нарушение text XOR media.
    """
    user, profile = pair
    await _check_rate_limit(user.id)

    svc = _build_feed_service(db)
    try:
        comment_id = await svc.create_comment(
            user=user,
            profile=profile,
            post_id=post_id,
            text=body.text,
            media_type=body.media_type,
            media_file_id=body.media_file_id,
        )
    except FeedServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return CreateCommentResponse(id=comment_id)


@router.put("/api/feed/posts/{post_id}/reaction", response_model=ReactionResponse)
async def set_reaction(
    post_id: int,
    body: SetReactionRequest,
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> ReactionResponse:
    """Поставить или сменить реакцию (анкета обязательна).

    403 нет анкеты. 422 неверный reaction_type.
    """
    user, _profile = pair
    await _check_rate_limit(user.id)

    svc = _build_feed_service(db)
    try:
        counts, my_reaction = await svc.set_reaction(
            user=user,
            post_id=post_id,
            reaction_type=body.reaction_type,
        )
    except FeedServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ReactionResponse(
        counts=ReactionCounts(**counts),
        my_reaction=my_reaction,
    )


@router.delete("/api/feed/posts/{post_id}/reaction", response_model=ReactionResponse)
async def remove_reaction(
    post_id: int,
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> ReactionResponse:
    """Снять свою реакцию (анкета обязательна).

    403 нет анкеты.
    """
    user, _profile = pair
    await _check_rate_limit(user.id)

    svc = _build_feed_service(db)
    try:
        counts, my_reaction = await svc.remove_reaction(user=user, post_id=post_id)
    except FeedServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ReactionResponse(
        counts=ReactionCounts(**counts),
        my_reaction=my_reaction,
    )


@router.delete("/api/feed/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: int,
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Удалить свой комментарий.

    403 если не автор. 404 если не найден.
    """
    user, _profile = pair
    await _check_rate_limit(user.id)

    svc = _build_feed_service(db)
    try:
        await svc.delete_comment(user=user, comment_id=comment_id)
    except FeedServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
