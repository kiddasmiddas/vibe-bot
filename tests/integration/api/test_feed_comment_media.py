"""GET /api/feed/posts/{id}/comments — медиа комментария резолвится в URL.

Регрессия (репорт клиента 2026-06-11): фото в комментариях не отображались,
потому что эндпоинт отдавал сырой Telegram file_id вместо HTTP-URL (в отличие
от медиа постов, которое проходит через resolve_file_url). Фронт вставляет
media_file_id прямо в <img src>, поэтому там обязан быть URL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.user_repo import UserRepository
from tests.integration.api.conftest import TEST_BOT_TOKEN, build_init_data


async def _ensure_user(db: AsyncSession, telegram_id: int) -> User:
    repo = UserRepository(db)
    existing = await repo.get_by_telegram_id(telegram_id)
    if existing is not None:
        return existing
    user = await repo.create(telegram_id=telegram_id, username=f"u{telegram_id}")
    await db.flush()
    return user


@pytest.fixture
def _resolve_wraps_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переопределяем passthrough-мок: file_id → отличимый URL.

    Так тест ловит именно ОТСУТСТВИЕ резолва (если вернулся сырой file_id —
    значит resolve_file_url не вызван, баг вернулся).
    """

    async def _resolve_one(file_id: str | None) -> str | None:
        return f"https://files.example/{file_id}" if file_id else None

    monkeypatch.setattr("app.api.routes.feed.resolve_file_url", _resolve_one)


@pytest.mark.asyncio
async def test_comment_media_file_id_resolved_to_url(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    _resolve_wraps_url: None,
) -> None:
    user = await _ensure_user(api_db_session, telegram_id=880001)
    now = datetime.now(tz=UTC)
    repo = FeedRepository(api_db_session)
    post = await repo.create_post(
        author_user_id=user.id,
        author_name="Author",
        text="post",
        status="active",
        is_pending_review=False,
        published_at=now,
        expires_at=now + timedelta(hours=48),
    )
    await repo.create_comment(
        post_id=post.id,
        author_user_id=user.id,
        media_type="photo",
        media_file_id="AgACtelegramFileId123",
    )
    await api_db_session.flush()

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    resp = await api_client.get(
        f"/api/feed/posts/{post.id}/comments",
        headers={"X-Telegram-Init-Data": header},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    media = items[0]["media_file_id"]
    # Должен быть резолвленный URL, а НЕ сырой Telegram file_id.
    assert media == "https://files.example/AgACtelegramFileId123"
    assert not media.startswith("AgAC")


@pytest.mark.asyncio
async def test_text_only_comment_has_no_media(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    _resolve_wraps_url: None,
) -> None:
    """Текстовый комментарий без медиа → media_file_id остаётся None (резолв не дёргается)."""
    user = await _ensure_user(api_db_session, telegram_id=880002)
    now = datetime.now(tz=UTC)
    repo = FeedRepository(api_db_session)
    post = await repo.create_post(
        author_user_id=user.id,
        author_name="Author",
        text="post",
        status="active",
        is_pending_review=False,
        published_at=now,
        expires_at=now + timedelta(hours=48),
    )
    await repo.create_comment(post_id=post.id, author_user_id=user.id, text="просто текст")
    await api_db_session.flush()

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    resp = await api_client.get(
        f"/api/feed/posts/{post.id}/comments",
        headers={"X-Telegram-Init-Data": header},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["media_file_id"] is None
    assert items[0]["text"] == "просто текст"
