"""Тесты на FeedService.create_post — месячный лимит постов по статусу.

Заказчик открыл создание постов в Ленте обычным пользователям (раньше — только
Premium) с лимитом 5 постов в месяц. Premium сохраняет свой лимит (дефолт 50).

Покрываем:
- обычный пользователь под лимитом → пост создаётся;
- обычный пользователь на лимите → 422 (с апселлом Premium в тексте);
- Premium на «обычном» лимите (5) НЕ блокируется — у него свой потолок;
- Premium на своём лимите → 422;
- при отсутствии ключей в settings берутся дефолты (обычный = 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.profile import Profile
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.user_repo import UserRepository
from app.services.feed_service import FeedService, FeedServiceError

# ---------------------------------------------------------------------------
# Заглушки
# ---------------------------------------------------------------------------


@dataclass
class _StubTextResult:
    approved: bool
    decision: str
    reason: str | None = None
    matched_terms: list[str] | None = None


class _StubModeration:
    """Мок ContentModerationService: текст всегда одобряется."""

    async def check_text(
        self,
        text: str,
        *,
        allow_links: bool,
        target_kind: str,
        target_id: int | None = None,
        user_id: int | None = None,
    ) -> _StubTextResult:
        return _StubTextResult(approved=True, decision="approved")


class _StubSettings:
    """settings_repo с заранее заданными целочисленными значениями.

    Ключ отсутствует → get_int возвращает None (сервис берёт дефолт).
    """

    def __init__(self, values: dict[str, int] | None = None) -> None:
        self._values = values or {}

    async def get_int(self, key: str) -> int | None:
        return self._values.get(key)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, telegram_id: int, *, premium: bool = False) -> Any:
    repo = UserRepository(db)
    user = await repo.create(telegram_id=telegram_id, username=f"u{telegram_id}")
    if premium:
        user.is_premium = True
        await db.flush()
    return user


def _profile(nickname: str = "Tester") -> Profile:
    """Detached-профиль: create_post читает только profile.nickname."""
    return Profile(nickname=nickname)


async def _seed_posts(db: AsyncSession, author_user_id: int, count: int) -> None:
    """Создаёт `count` постов автора в текущем месяце (минуя сервис → без лимита)."""
    now = datetime.now(tz=UTC)
    repo = FeedRepository(db)
    for _ in range(count):
        await repo.create_post(
            author_user_id=author_user_id,
            author_name="Tester",
            text="seed",
            status="active",
            is_pending_review=False,
            published_at=now,
            expires_at=now + timedelta(hours=48),
        )
    await db.flush()


def _make_service(db: AsyncSession, settings: _StubSettings) -> FeedService:
    return FeedService(
        db,
        feed_repo=FeedRepository(db),
        settings_repo=settings,  # type: ignore[arg-type]
        analytics_repo=AnalyticsRepository(db),
        moderation_service=_StubModeration(),  # type: ignore[arg-type]
    )


_NO_PREMODERATE = {"feed_premoderate_first_n_posts": 0}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regular_user_can_post_under_limit(db_session: AsyncSession) -> None:
    """Обычный пользователь без премиума может создать пост (раньше был 403)."""
    user = await _make_user(db_session, telegram_id=30_001)
    settings = _StubSettings(
        {"feed_post_limit_regular_month": 5, "feed_post_limit_premium_month": 50, **_NO_PREMODERATE}
    )
    svc = _make_service(db_session, settings)

    post_id, pending = await svc.create_post(
        user=user, profile=_profile(), text="Привет, лента!", media=[]
    )

    assert post_id > 0
    assert pending is False
    repo = FeedRepository(db_session)
    assert await repo.count_posts_by_user_since(user.id, datetime.min.replace(tzinfo=UTC)) == 1


@pytest.mark.asyncio
async def test_regular_user_blocked_at_limit(db_session: AsyncSession) -> None:
    """6-й пост обычного пользователя за месяц → 422 с апселлом Premium."""
    user = await _make_user(db_session, telegram_id=30_002)
    await _seed_posts(db_session, user.id, 5)
    settings = _StubSettings(
        {"feed_post_limit_regular_month": 5, "feed_post_limit_premium_month": 50, **_NO_PREMODERATE}
    )
    svc = _make_service(db_session, settings)

    with pytest.raises(FeedServiceError) as exc:
        await svc.create_post(user=user, profile=_profile(), text="Шестой пост", media=[])

    assert exc.value.status_code == 422
    assert "5" in exc.value.detail
    assert "Premium" in exc.value.detail
    assert "50" in exc.value.detail  # апселл несёт правильный premium-лимит
    # Шестой пост не создан — счётчик остался 5.
    repo = FeedRepository(db_session)
    assert await repo.count_posts_by_user_since(user.id, datetime.min.replace(tzinfo=UTC)) == 5


@pytest.mark.asyncio
async def test_premium_user_not_capped_at_regular_limit(db_session: AsyncSession) -> None:
    """Premium с 5 постами НЕ блокируется лимитом обычных — у него свой потолок 50."""
    user = await _make_user(db_session, telegram_id=30_003, premium=True)
    await _seed_posts(db_session, user.id, 5)
    settings = _StubSettings(
        {"feed_post_limit_regular_month": 5, "feed_post_limit_premium_month": 50, **_NO_PREMODERATE}
    )
    svc = _make_service(db_session, settings)

    post_id, _ = await svc.create_post(
        user=user, profile=_profile(), text="Шестой пост премиума", media=[]
    )

    assert post_id > 0
    repo = FeedRepository(db_session)
    assert await repo.count_posts_by_user_since(user.id, datetime.min.replace(tzinfo=UTC)) == 6


@pytest.mark.asyncio
async def test_premium_user_blocked_at_premium_limit(db_session: AsyncSession) -> None:
    """Premium на своём лимите → 422 (проверяем малым потолком, чтобы не сеять 50 строк)."""
    user = await _make_user(db_session, telegram_id=30_004, premium=True)
    await _seed_posts(db_session, user.id, 3)
    settings = _StubSettings(
        {"feed_post_limit_regular_month": 5, "feed_post_limit_premium_month": 3, **_NO_PREMODERATE}
    )
    svc = _make_service(db_session, settings)

    with pytest.raises(FeedServiceError) as exc:
        await svc.create_post(user=user, profile=_profile(), text="Четвёртый", media=[])

    assert exc.value.status_code == 422
    assert "3" in exc.value.detail


@pytest.mark.asyncio
async def test_defaults_when_settings_absent(db_session: AsyncSession) -> None:
    """Без ключей в settings берётся дефолт: обычный = 5 (6-й → 422)."""
    user = await _make_user(db_session, telegram_id=30_005)
    await _seed_posts(db_session, user.id, 5)
    # Пустой settings → premoderate тоже дефолт (3), но лимит проверяется раньше.
    svc = _make_service(db_session, _StubSettings())

    with pytest.raises(FeedServiceError) as exc:
        await svc.create_post(user=user, profile=_profile(), text="Шестой", media=[])

    assert exc.value.status_code == 422
    assert "5" in exc.value.detail
