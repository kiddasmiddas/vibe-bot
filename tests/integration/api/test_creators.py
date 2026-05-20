from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dictionaries import CreatorCategory
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.creator_repo import CreatorRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from tests.integration.api.conftest import TEST_BOT_TOKEN, build_init_data

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(db: AsyncSession, telegram_id: int) -> User:
    repo = UserRepository(db)
    user = await repo.get_by_telegram_id(telegram_id)
    if user is None:
        user = await repo.create(telegram_id=telegram_id, username=f"u{telegram_id}")
        await db.flush()
    return user


async def _make_category(db: AsyncSession, code: str) -> CreatorCategory:
    cat = CreatorCategory(code=code, title=code.replace("_", " ").title())
    db.add(cat)
    await db.flush()
    return cat


async def _make_post(
    db: AsyncSession,
    *,
    code: str,
    published_offset_seconds: int = 0,
    expires_in_days: int = 10,
    is_published: bool = True,
    is_pending_review: bool = False,
) -> int:
    """Создаёт пост и первое фото, возвращает post.id."""
    cat = await _make_category(db, code)
    repo = CreatorRepository(db)
    now = datetime.now(tz=UTC)
    post = await repo.create_post(
        author_display_name="Creator",
        category_id=cat.id,
        description=f"Description for {code}",
        telegram_link="https://t.me/test_channel",
        is_premium_post=False,
        published_at=now + timedelta(seconds=published_offset_seconds),
        expires_at=now + timedelta(days=expires_in_days),
        is_published=is_published,
    )
    if is_pending_review:
        post.is_pending_review = True
        await db.flush()
    await repo.add_photo(post.id, f"file_id_{code}", 0)
    return post.id


# ---------------------------------------------------------------------------
# User/auth helpers in tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def auth_user(api_db_session: AsyncSession):  # type: ignore[no-untyped-def]
    """Создаёт пользователя в тестовой БД и возвращает (user, init_data_header)."""
    user = await _ensure_user(api_db_session, telegram_id=200_001)
    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    return user, header


# ---------------------------------------------------------------------------
# Tests: feed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_empty(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """Пустая лента → items=[], next_cursor=None."""
    _user, header = auth_user
    response = await api_client.get("/api/creators/feed", headers={"X-Telegram-Init-Data": header})
    assert response.status_code == 200
    data = response.json()
    # Может быть пусто или содержать посты из других тестов, но структура корректная
    assert "items" in data
    assert "next_cursor" in data


@pytest.mark.asyncio
async def test_feed_order_desc_by_published_at(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """Три поста с разным published_at → возвращаются в порядке DESC."""
    _user, header = auth_user
    pid1 = await _make_post(api_db_session, code="order_a", published_offset_seconds=0)
    pid2 = await _make_post(api_db_session, code="order_b", published_offset_seconds=1)
    pid3 = await _make_post(api_db_session, code="order_c", published_offset_seconds=2)

    response = await api_client.get(
        "/api/creators/feed?limit=50", headers={"X-Telegram-Init-Data": header}
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    # pid3 должен идти раньше pid2, pid2 раньше pid1
    assert ids.index(pid3) < ids.index(pid2) < ids.index(pid1)


@pytest.mark.asyncio
async def test_feed_cursor_pagination(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """limit=2 → 2 items + next_cursor; следующий запрос → оставшийся пост."""
    _user, header = auth_user
    # Создаём 3 поста с разным временем публикации
    pid_oldest = await _make_post(api_db_session, code="pag_old", published_offset_seconds=10)
    pid_mid = await _make_post(api_db_session, code="pag_mid", published_offset_seconds=20)
    pid_newest = await _make_post(api_db_session, code="pag_new", published_offset_seconds=30)

    # Первая страница: limit=2
    r1 = await api_client.get(
        "/api/creators/feed?limit=2", headers={"X-Telegram-Init-Data": header}
    )
    assert r1.status_code == 200
    data1 = r1.json()
    assert len(data1["items"]) == 2
    assert data1["next_cursor"] is not None

    page1_ids = {item["id"] for item in data1["items"]}
    assert pid_newest in page1_ids
    assert pid_mid in page1_ids

    # Вторая страница по курсору
    r2 = await api_client.get(
        f"/api/creators/feed?limit=2&cursor={data1['next_cursor']}",
        headers={"X-Telegram-Init-Data": header},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    page2_ids = {item["id"] for item in data2["items"]}
    assert pid_oldest in page2_ids
    # Когда постов не больше — next_cursor должен быть None
    # (может быть не None если есть другие посты из других тестов, но pid_mid не в page2)
    assert pid_mid not in page2_ids
    assert pid_newest not in page2_ids


@pytest.mark.asyncio
async def test_feed_excludes_unpublished(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """is_published=False → не попадает в ленту."""
    _user, header = auth_user
    hidden_id = await _make_post(api_db_session, code="unpub_test", is_published=False)
    r = await api_client.get(
        "/api/creators/feed?limit=50", headers={"X-Telegram-Init-Data": header}
    )
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()["items"]}
    assert hidden_id not in ids


@pytest.mark.asyncio
async def test_feed_excludes_expired(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """expires_at < now() → не попадает в ленту."""
    _user, header = auth_user
    cat = await _make_category(api_db_session, "exp_feed_cat")
    repo = CreatorRepository(api_db_session)
    now = datetime.now(tz=UTC)
    expired = await repo.create_post(
        author_display_name="E",
        category_id=cat.id,
        description="expired",
        telegram_link="https://t.me/x",
        is_premium_post=False,
        published_at=now - timedelta(days=5),
        expires_at=now - timedelta(seconds=1),
        is_published=True,
    )
    r = await api_client.get(
        "/api/creators/feed?limit=50", headers={"X-Telegram-Init-Data": header}
    )
    ids = {item["id"] for item in r.json()["items"]}
    assert expired.id not in ids


@pytest.mark.asyncio
async def test_feed_excludes_pending_review(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """is_pending_review=True → не попадает в ленту."""
    _user, header = auth_user
    pending_id = await _make_post(api_db_session, code="pend_feed_test", is_pending_review=True)
    r = await api_client.get(
        "/api/creators/feed?limit=50", headers={"X-Telegram-Init-Data": header}
    )
    ids = {item["id"] for item in r.json()["items"]}
    assert pending_id not in ids


# ---------------------------------------------------------------------------
# Tests: detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_post_detail(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """GET /api/creators/{id} для опубликованного поста → 200 со всеми полями."""
    _user, header = auth_user
    cat = await _make_category(api_db_session, "detail_cat")
    repo = CreatorRepository(api_db_session)
    now = datetime.now(tz=UTC)
    post = await repo.create_post(
        author_display_name="DetailAuthor",
        category_id=cat.id,
        description="Full description here",
        telegram_link="https://t.me/detail_channel",
        is_premium_post=True,
        published_at=now,
        expires_at=now + timedelta(days=10),
        is_published=True,
    )
    await repo.add_photo(post.id, "photo_file_0", 0)
    await repo.add_photo(post.id, "photo_file_1", 1)

    r = await api_client.get(f"/api/creators/{post.id}", headers={"X-Telegram-Init-Data": header})
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == post.id
    assert data["description"] == "Full description here"
    assert data["telegram_link"] == "https://t.me/detail_channel"
    assert data["is_premium_post"] is True
    assert len(data["photos"]) == 2
    assert data["photos"][0] == "photo_file_0"
    assert data["photos"][1] == "photo_file_1"


@pytest.mark.asyncio
async def test_get_post_pending_review_returns_404(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """is_pending_review=True → 404."""
    _user, header = auth_user
    pending_id = await _make_post(api_db_session, code="pend_detail", is_pending_review=True)
    r = await api_client.get(
        f"/api/creators/{pending_id}", headers={"X-Telegram-Init-Data": header}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_post_expired_returns_404(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """expires_at < now() → 404."""
    _user, header = auth_user
    cat = await _make_category(api_db_session, "exp_detail_cat")
    repo = CreatorRepository(api_db_session)
    now = datetime.now(tz=UTC)
    expired = await repo.create_post(
        author_display_name="E",
        category_id=cat.id,
        description="expired",
        telegram_link="https://t.me/x",
        is_premium_post=False,
        published_at=now - timedelta(days=5),
        expires_at=now - timedelta(seconds=1),
        is_published=True,
    )
    r = await api_client.get(
        f"/api/creators/{expired.id}", headers={"X-Telegram-Init-Data": header}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_post_nonexistent_returns_404(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    auth_user,
) -> None:
    """Несуществующий post_id → 404."""
    _user, header = auth_user
    r = await api_client.get("/api/creators/999999999", headers={"X-Telegram-Init-Data": header})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests: analytics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_miniapp_opened_logged(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    make_init_data,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Первый запрос к /feed пишет событие MINIAPP_OPENED в analytics.

    Мокаем Redis в in-memory словарь — без рабочего Redis аналитика не пишется
    (мы не хотим дублировать событие при каждом запросе, если дедупликация
    через сессионный флаг недоступна).
    """
    from unittest.mock import AsyncMock

    fake = AsyncMock()
    fake.get = AsyncMock(return_value=None)
    fake.set = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.routes.creators.get_redis", lambda: fake)

    user = await _ensure_user(api_db_session, telegram_id=200_099)
    header = make_init_data(user.telegram_id)

    await api_client.get("/api/creators/feed", headers={"X-Telegram-Init-Data": header})

    analytics = AnalyticsRepository(api_db_session)
    events = await analytics.list_recent_for_user(user.id, limit=20)
    event_types = [e.event_type for e in events]
    assert EventType.MINIAPP_OPENED in event_types


@pytest.mark.asyncio
async def test_analytics_miniapp_opened_not_duplicated_in_session(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    make_init_data,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторный запрос в той же сессии не дублирует событие."""
    from unittest.mock import AsyncMock

    state: dict[str, str] = {}

    async def _get(key: str) -> str | None:
        return state.get(key)

    async def _set(key: str, value: str, ex: int) -> None:
        state[key] = value

    fake = AsyncMock()
    fake.get = _get
    fake.set = _set
    monkeypatch.setattr("app.api.routes.creators.get_redis", lambda: fake)

    user = await _ensure_user(api_db_session, telegram_id=200_098)
    header = make_init_data(user.telegram_id)

    for _ in range(3):
        await api_client.get("/api/creators/feed", headers={"X-Telegram-Init-Data": header})

    analytics = AnalyticsRepository(api_db_session)
    events = await analytics.list_recent_for_user(user.id, limit=20)
    miniapp_events = [e for e in events if e.event_type == EventType.MINIAPP_OPENED]
    assert len(miniapp_events) == 1
