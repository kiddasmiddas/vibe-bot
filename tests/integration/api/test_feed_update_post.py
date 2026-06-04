"""Интеграционные тесты на PUT /api/feed/posts/{post_id} (Волна 3).

Проверяем:
- 200 — happy path, текст обновился, pending_review=True, expires_at не сброшен.
- 403 — редактируем чужой пост.
- 409 — пост в статусе blocked / hidden_by_moderator.
- 404 — пост не найден.
- 401 — без initData.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dictionaries import Gender, Vibe
from app.db.models.user import User
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.profile_repo import ProfileRepository
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


async def _ensure_profile(db: AsyncSession, user: User, *, nickname: str = "Author") -> None:
    """Создаёт завершённую анкету (нужно для current_user_with_profile)."""
    profile_repo = ProfileRepository(db)
    existing = await profile_repo.get_by_user_id(user.id)
    if existing is not None and existing.is_completed:
        return

    male = (await db.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    # Используем уникальные коды чтобы не конфликтовать с другими тестами в одной сессии.
    vibe_code = f"upd_vibe_{user.telegram_id}"
    vibe = (await db.execute(select(Vibe).where(Vibe.code == vibe_code))).scalar_one_or_none()
    if vibe is None:
        vibe = Vibe(
            code=vibe_code,
            title=f"Upd vibe {user.telegram_id}",
            number=9100 + (user.telegram_id % 1000),
            image_file_id=f"img_{user.telegram_id}",
        )
        db.add(vibe)
        await db.flush()

    if existing is None:
        profile = await profile_repo.create(
            user_id=user.id,
            nickname=nickname,
            age=22,
            gender_id=male.id,
            looking_for_age_min=18,
            looking_for_age_max=30,
            bio="hi",
            own_vibe_id=vibe.id,
            main_media_type="photo",
            main_media_file_id="profile_photo",
        )
    else:
        profile = existing

    await profile_repo.mark_completed(profile.id)
    await db.flush()


async def _make_post(
    db: AsyncSession,
    author_user_id: int,
    *,
    text: str = "Initial",
    status: str = "active",
    media_file_ids: list[str] | None = None,
) -> Any:
    """Создаёт пост, опционально с медиа."""
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db)
    post = await repo.create_post(
        author_user_id=author_user_id,
        author_name="Author",
        text=text,
        status=status,
        is_pending_review=False,
        published_at=now,
        expires_at=now + timedelta(hours=48),
    )
    if media_file_ids:
        await repo.replace_media(
            post.id,
            [
                {"file_id": fid, "media_type": "photo", "sort_order": idx}
                for idx, fid in enumerate(media_file_ids)
            ],
        )
    await db.flush()
    return post


@pytest.fixture(autouse=True)
def _disable_admin_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяем admin-notify, чтобы тест не пытался слать сообщения в реальный Telegram."""

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("app.api.routes.feed.notify_admins_feed_post_pending", _noop)


@pytest.fixture(autouse=True)
def _stub_redis_for_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяем Redis-клиент в feed-роуте, чтобы тесты не упирались в `redis:6379`.

    feed-роут вызывает SettingsRepository/ModerationRepository → check_text →
    list_active_stop_words с Redis-кэшем. В тестовом окружении DNS `redis`
    не резолвится — без этой фикстуры падает socket.gaierror на ровном месте.
    """
    from unittest.mock import AsyncMock, MagicMock

    fake = AsyncMock()
    fake.get = AsyncMock(return_value=None)
    fake.set = AsyncMock(return_value=True)
    fake.delete = AsyncMock(return_value=0)
    fake.incr = AsyncMock(return_value=1)
    fake.expire = AsyncMock(return_value=True)
    # pipeline() — синхронный билдер. AsyncMock тут даёт coroutine, который
    # тихо проваливается в `_check_rate_limit` через `except Exception` —
    # тест проходит, но rate-limit-ветка вообще не выполняется. Делаем
    # синхронный mock, возвращающий AsyncMock с awaitable execute().
    pipe = AsyncMock()
    pipe.incr = MagicMock(return_value=None)
    pipe.expire = MagicMock(return_value=None)
    pipe.execute = AsyncMock(return_value=[1, True])
    fake.pipeline = MagicMock(return_value=pipe)
    monkeypatch.setattr("app.api.routes.feed.get_redis", lambda: fake)


@pytest.mark.asyncio
async def test_update_post_text_success(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """200 — автор меняет текст, pending_review=True, expires_at не сброшен."""
    user = await _ensure_user(api_db_session, telegram_id=300_001)
    await _ensure_profile(api_db_session, user)
    post = await _make_post(api_db_session, user.id, text="Initial")
    original_expires = post.expires_at

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    response = await api_client.put(
        f"/api/feed/posts/{post.id}",
        json={"text": "Edited text"},
        headers={"X-Telegram-Init-Data": header},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == post.id
    assert data["text"] == "Edited text"
    # expires_at не должен меняться — таймер от created_at
    assert data["expires_at"] == original_expires.isoformat()

    # Проверяем в БД, что pending_review выставлен.
    repo = FeedRepository(api_db_session)
    refreshed = await repo.get_by_id(post.id)
    assert refreshed is not None
    assert refreshed.is_pending_review is True
    assert refreshed.text == "Edited text"


@pytest.mark.asyncio
async def test_update_post_not_author_forbidden(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """403 — пользователь пытается редактировать чужой пост."""
    author = await _ensure_user(api_db_session, telegram_id=300_002)
    await _ensure_profile(api_db_session, author)
    other = await _ensure_user(api_db_session, telegram_id=300_003)
    await _ensure_profile(api_db_session, other)

    post = await _make_post(api_db_session, author.id, text="Original")

    header = build_init_data(TEST_BOT_TOKEN, other.telegram_id)
    response = await api_client.put(
        f"/api/feed/posts/{post.id}",
        json={"text": "Hijack"},
        headers={"X-Telegram-Init-Data": header},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_post_blocked_status_conflict(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """409 — пост в статусе blocked редактировать нельзя."""
    user = await _ensure_user(api_db_session, telegram_id=300_004)
    await _ensure_profile(api_db_session, user)
    post = await _make_post(api_db_session, user.id, status="blocked")

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    response = await api_client.put(
        f"/api/feed/posts/{post.id}",
        json={"text": "New content"},
        headers={"X-Telegram-Init-Data": header},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_post_not_found(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """404 — нет поста с таким id."""
    user = await _ensure_user(api_db_session, telegram_id=300_005)
    await _ensure_profile(api_db_session, user)

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    response = await api_client.put(
        "/api/feed/posts/999999999",
        json={"text": "Whatever"},
        headers={"X-Telegram-Init-Data": header},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_post_requires_auth(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """401 — без X-Telegram-Init-Data."""
    user = await _ensure_user(api_db_session, telegram_id=300_006)
    await _ensure_profile(api_db_session, user)
    post = await _make_post(api_db_session, user.id)

    # Без init-data заголовка — current_user отвечает 401
    response = await api_client.put(
        f"/api/feed/posts/{post.id}",
        json={"text": "New"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_post_replace_media(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """200 — медиа заменяется на новое; pending_review=True."""
    user = await _ensure_user(api_db_session, telegram_id=300_007)
    await _ensure_profile(api_db_session, user)
    post = await _make_post(
        api_db_session,
        user.id,
        text="Stable text",
        media_file_ids=["old_file_1"],
    )

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    response = await api_client.put(
        f"/api/feed/posts/{post.id}",
        json={
            "text": "Stable text",
            "media": [{"file_id": "new_file_1", "media_type": "photo"}],
        },
        headers={"X-Telegram-Init-Data": header},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["photos"] == ["new_file_1"]

    repo = FeedRepository(api_db_session)
    refreshed = await repo.get_by_id(post.id)
    assert refreshed is not None
    assert refreshed.is_pending_review is True
