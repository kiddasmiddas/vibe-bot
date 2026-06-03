"""Тесты на FeedService.update_post (Волна 3 — редактирование постов Ленты).

Покрываем:
- happy path (только текст / только медиа / оба);
- 403 — не автор;
- 409 — пост не в статусе active (blocked / hidden_by_moderator);
- 404 — пост не найден;
- 422 — текст не прошёл модерацию (стоп-слово / ссылка);
- no-op — повторная отправка тех же данных;
- expires_at не сбрасывается;
- updated_at пишется явно;
- is_pending_review=True после любого реального изменения.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.user_repo import UserRepository
from app.services.feed_service import FeedService, FeedServiceError

# ---------------------------------------------------------------------------
# Заглушки для зависимостей сервиса
# ---------------------------------------------------------------------------


@dataclass
class _StubTextResult:
    approved: bool
    decision: str
    reason: str | None = None
    matched_terms: list[str] | None = None


class _StubModeration:
    """Минимальный мок ContentModerationService для unit-теста update_post.

    Полностью имитирует методы check_text / check_image без обращения к БД.
    """

    def __init__(
        self,
        *,
        text_approved: bool = True,
        text_reason: str | None = None,
    ) -> None:
        self.text_approved = text_approved
        self.text_reason = text_reason
        self.check_text_calls: list[dict[str, Any]] = []
        self.check_image_calls: list[dict[str, Any]] = []

    async def check_text(
        self,
        text: str,
        *,
        allow_links: bool,
        target_kind: str,
        target_id: int | None = None,
        user_id: int | None = None,
    ) -> _StubTextResult:
        self.check_text_calls.append(
            {
                "text": text,
                "allow_links": allow_links,
                "target_kind": target_kind,
                "target_id": target_id,
                "user_id": user_id,
            }
        )
        if self.text_approved:
            return _StubTextResult(approved=True, decision="approved")
        return _StubTextResult(
            approved=False,
            decision="rejected",
            reason=self.text_reason or "stop_word",
            matched_terms=["test"],
        )


class _StubSettingsRepo:
    """Пустой settings_repo — update_post не использует его."""

    async def get_int(self, key: str) -> int | None:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, telegram_id: int) -> Any:
    """Создаёт пользователя через репозиторий (без анкеты — update_post её не требует)."""
    repo = UserRepository(db)
    return await repo.create(telegram_id=telegram_id, username=f"u{telegram_id}")


async def _make_post(
    db: AsyncSession,
    author_user_id: int,
    *,
    text: str = "Original text",
    status: str = "active",
    is_pending_review: bool = False,
    media: list[tuple[str, str]] | None = None,
) -> Any:
    """Создаёт пост с заданным текстом/статусом и опциональными медиа.

    `media` — список `[(file_id, media_type), ...]`.
    """
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db)
    post = await repo.create_post(
        author_user_id=author_user_id,
        author_name="TestAuthor",
        text=text,
        status=status,
        is_pending_review=is_pending_review,
        published_at=now,
        expires_at=now + timedelta(hours=48),
    )
    if media:
        await repo.replace_media(
            post.id,
            [
                {"file_id": fid, "media_type": mtype, "sort_order": idx}
                for idx, (fid, mtype) in enumerate(media)
            ],
        )
    await db.flush()
    return post


def _make_service(db: AsyncSession, *, moderation: _StubModeration | None = None) -> FeedService:
    return FeedService(
        db,
        feed_repo=FeedRepository(db),
        settings_repo=_StubSettingsRepo(),  # type: ignore[arg-type]
        analytics_repo=AnalyticsRepository(db),
        moderation_service=moderation or _StubModeration(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_post_text_only_success(db_session: AsyncSession) -> None:
    """Меняем только текст → пост обновлён, is_pending_review=True, expires_at не сброшен."""
    user = await _make_user(db_session, telegram_id=10_001)
    post = await _make_post(db_session, user.id, text="Old text")
    original_expires = post.expires_at
    original_created = post.created_at

    moderation = _StubModeration(text_approved=True)
    svc = _make_service(db_session, moderation=moderation)

    updated, changed = await svc.update_post(
        user=user,
        post_id=post.id,
        text="New text",
        media=None,
    )

    assert changed is True
    assert updated.text == "New text"
    assert updated.is_pending_review is True
    assert updated.expires_at == original_expires  # 48ч таймер от created_at не сброшен
    assert updated.created_at == original_created
    assert updated.updated_at > original_created
    # check_text вызван ровно один раз для нового текста
    assert len(moderation.check_text_calls) == 1
    assert moderation.check_text_calls[0]["text"] == "New text"


@pytest.mark.asyncio
async def test_update_post_media_only_success(db_session: AsyncSession) -> None:
    """Меняем только медиа → текст прежний, набор медиа заменён, pending_review=True."""
    user = await _make_user(db_session, telegram_id=10_002)
    post = await _make_post(
        db_session,
        user.id,
        text="Unchanged text",
        media=[("file_a", "photo")],
    )

    moderation = _StubModeration(text_approved=True)
    svc = _make_service(db_session, moderation=moderation)

    updated, changed = await svc.update_post(
        user=user,
        post_id=post.id,
        text="Unchanged text",  # тот же
        media=[{"file_id": "file_b", "media_type": "photo"}],
    )

    assert changed is True
    assert updated.text == "Unchanged text"
    assert updated.is_pending_review is True

    repo = FeedRepository(db_session)
    media = await repo.get_photos_for_post(post.id)
    assert [m.file_id for m in media] == ["file_b"]
    # check_text не вызывался — текст не менялся
    assert len(moderation.check_text_calls) == 0


@pytest.mark.asyncio
async def test_update_post_text_and_media_success(db_session: AsyncSession) -> None:
    """Меняем и текст, и медиа разом."""
    user = await _make_user(db_session, telegram_id=10_003)
    post = await _make_post(
        db_session,
        user.id,
        text="Original",
        media=[("file_a", "photo"), ("file_b", "photo")],
    )

    svc = _make_service(db_session)

    updated, changed = await svc.update_post(
        user=user,
        post_id=post.id,
        text="Edited text",
        media=[{"file_id": "file_c", "media_type": "gif"}],
    )

    assert changed is True
    assert updated.text == "Edited text"
    assert updated.is_pending_review is True
    repo = FeedRepository(db_session)
    media = await repo.get_photos_for_post(post.id)
    assert len(media) == 1
    assert media[0].file_id == "file_c"
    assert media[0].media_type == "gif"


@pytest.mark.asyncio
async def test_update_post_empty_media_clears_all(db_session: AsyncSession) -> None:
    """media=[] → удаляем все медиа поста."""
    user = await _make_user(db_session, telegram_id=10_004)
    post = await _make_post(
        db_session,
        user.id,
        text="Same",
        media=[("file_a", "photo")],
    )

    svc = _make_service(db_session)

    updated, changed = await svc.update_post(
        user=user,
        post_id=post.id,
        text="Same edit",
        media=[],
    )

    assert changed is True
    assert updated.text == "Same edit"
    repo = FeedRepository(db_session)
    media = await repo.get_photos_for_post(post.id)
    assert media == []


@pytest.mark.asyncio
async def test_update_post_not_author_forbidden(db_session: AsyncSession) -> None:
    """403 — пытается редактировать чужой пост."""
    author = await _make_user(db_session, telegram_id=10_005)
    other = await _make_user(db_session, telegram_id=10_006)
    post = await _make_post(db_session, author.id)

    svc = _make_service(db_session)

    with pytest.raises(FeedServiceError) as exc:
        await svc.update_post(
            user=other,
            post_id=post.id,
            text="Hijack attempt",
            media=None,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_post_blocked_status_conflict(db_session: AsyncSession) -> None:
    """409 — пост в статусе blocked нельзя редактировать."""
    user = await _make_user(db_session, telegram_id=10_007)
    post = await _make_post(db_session, user.id, status="blocked")

    svc = _make_service(db_session)

    with pytest.raises(FeedServiceError) as exc:
        await svc.update_post(
            user=user,
            post_id=post.id,
            text="Try edit",
            media=None,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_post_hidden_by_moderator_conflict(db_session: AsyncSession) -> None:
    """409 — пост, скрытый модератором, редактировать нельзя."""
    user = await _make_user(db_session, telegram_id=10_008)
    post = await _make_post(db_session, user.id, status="hidden_by_moderator")

    svc = _make_service(db_session)

    with pytest.raises(FeedServiceError) as exc:
        await svc.update_post(
            user=user,
            post_id=post.id,
            text="Try edit",
            media=None,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_post_not_found(db_session: AsyncSession) -> None:
    """404 — поста с таким id нет."""
    user = await _make_user(db_session, telegram_id=10_009)
    svc = _make_service(db_session)

    with pytest.raises(FeedServiceError) as exc:
        await svc.update_post(
            user=user,
            post_id=999_999_999,
            text="Anything",
            media=None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_post_text_moderation_rejected(db_session: AsyncSession) -> None:
    """422 — новый текст не прошёл модерацию (ссылка / стоп-слово)."""
    user = await _make_user(db_session, telegram_id=10_010)
    post = await _make_post(db_session, user.id, text="Original")

    moderation = _StubModeration(text_approved=False, text_reason="link_detected")
    svc = _make_service(db_session, moderation=moderation)

    with pytest.raises(FeedServiceError) as exc:
        await svc.update_post(
            user=user,
            post_id=post.id,
            text="Check https://spam.com",
            media=None,
        )
    assert exc.value.status_code == 422

    # Текст в БД не изменился, pending_review не выставлен.
    repo = FeedRepository(db_session)
    same = await repo.get_by_id(post.id)
    assert same is not None
    assert same.text == "Original"
    assert same.is_pending_review is False


@pytest.mark.asyncio
async def test_update_post_no_changes_is_noop(db_session: AsyncSession) -> None:
    """Тот же текст и тот же набор медиа → no-op, моделям БД нечего обновлять."""
    user = await _make_user(db_session, telegram_id=10_011)
    post = await _make_post(
        db_session,
        user.id,
        text="Same text",
        media=[("file_a", "photo")],
    )
    original_updated = post.updated_at

    moderation = _StubModeration(text_approved=True)
    svc = _make_service(db_session, moderation=moderation)

    result, changed = await svc.update_post(
        user=user,
        post_id=post.id,
        text="Same text",
        media=[{"file_id": "file_a", "media_type": "photo"}],
    )

    # No-op: модерация не вызывалась, pending_review не выставлен, changed=False
    # (значит роут НЕ дёрнет admin-notify).
    assert changed is False
    assert len(moderation.check_text_calls) == 0
    assert result.is_pending_review is False
    assert result.updated_at == original_updated


@pytest.mark.asyncio
async def test_update_post_media_unchanged_when_media_none(db_session: AsyncSession) -> None:
    """media=None → редактируем только текст, медиа остаются как были."""
    user = await _make_user(db_session, telegram_id=10_012)
    post = await _make_post(
        db_session,
        user.id,
        text="Original",
        media=[("file_a", "photo"), ("file_b", "photo")],
    )

    svc = _make_service(db_session)

    await svc.update_post(
        user=user,
        post_id=post.id,
        text="Edited",
        media=None,
    )

    repo = FeedRepository(db_session)
    media = await repo.get_photos_for_post(post.id)
    assert [m.file_id for m in media] == ["file_a", "file_b"]
