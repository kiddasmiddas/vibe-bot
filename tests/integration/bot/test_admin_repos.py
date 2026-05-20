"""Интеграционные тесты для admin-специфичных операций с реальной БД.

Покрывает требования Этапа 10: поиск юзера, бан, жалоба resolve,
аллея create, premium ручная выдача, promo create, stopword add,
аналитика aggregate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.complaint_repo import ComplaintRepository
from app.db.repositories.creator_repo import CreatorRepository
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.premium_repo import PremiumRepository
from app.db.repositories.promo_repo import PromoRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


async def _make_user(db_session, telegram_id: int, username: str | None = None):
    repo = UserRepository(db_session)
    return await repo.create(telegram_id=telegram_id, username=username)


# ------------------------------------------------------------------ #
# 10.3 Поиск пользователя
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_user_search_by_telegram_id(db_session) -> None:
    """UserRepository.search находит пользователя по telegram_id."""
    user = await _make_user(db_session, telegram_id=7001001)
    repo = UserRepository(db_session)
    results = await repo.search("7001001")
    assert any(r.id == user.id for r in results)


@pytest.mark.asyncio
async def test_user_search_by_username(db_session) -> None:
    """UserRepository.search находит по @username (case-insensitive)."""
    user = await _make_user(db_session, telegram_id=7001002, username="testadmin_alice")
    repo = UserRepository(db_session)
    results = await repo.search("testadmin_alice")
    assert any(r.id == user.id for r in results)


@pytest.mark.asyncio
async def test_user_search_not_found(db_session) -> None:
    """UserRepository.search возвращает пустой список для несуществующего."""
    repo = UserRepository(db_session)
    results = await repo.search("definitely_nonexistent_xyz_9999")
    assert results == []


# ------------------------------------------------------------------ #
# 10.3 Бан пользователя
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_ban_user(db_session) -> None:
    """set_banned(True) выставляет is_banned=True."""
    user = await _make_user(db_session, telegram_id=7002001)
    repo = UserRepository(db_session)
    await repo.set_banned(user.id, banned=True)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.is_banned is True


@pytest.mark.asyncio
async def test_unban_user(db_session) -> None:
    """set_banned(False) снимает бан."""
    user = await _make_user(db_session, telegram_id=7002002)
    repo = UserRepository(db_session)
    await repo.set_banned(user.id, banned=True)
    await repo.set_banned(user.id, banned=False)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.is_banned is False


# ------------------------------------------------------------------ #
# 10.4 Жалоба resolve
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_complaint_resolve(db_session) -> None:
    """ComplaintRepository.resolve изменяет статус на 'resolved'."""
    from_user = await _make_user(db_session, telegram_id=7003001)
    target_user = await _make_user(db_session, telegram_id=7003002)

    # Берём любую причину жалобы из seed-данных
    from sqlalchemy import select

    from app.db.models.dictionaries import ComplaintReason

    reason = (await db_session.execute(select(ComplaintReason).limit(1))).scalar_one()

    complaint_repo = ComplaintRepository(db_session)
    complaint = await complaint_repo.create(
        from_user_id=from_user.id,
        target_user_id=target_user.id,
        reason_id=reason.id,
    )
    assert complaint.status == "new"

    await complaint_repo.resolve(complaint.id, moderator_user_id=from_user.id)
    await db_session.flush()
    await db_session.refresh(complaint)
    assert complaint.status == "resolved"


@pytest.mark.asyncio
async def test_complaint_set_status_rejected(db_session) -> None:
    """set_status позволяет перевести жалобу в 'rejected'."""
    from_user = await _make_user(db_session, telegram_id=7003003)
    target_user = await _make_user(db_session, telegram_id=7003004)

    from sqlalchemy import select

    from app.db.models.dictionaries import ComplaintReason

    reason = (await db_session.execute(select(ComplaintReason).limit(1))).scalar_one()

    complaint_repo = ComplaintRepository(db_session)
    complaint = await complaint_repo.create(
        from_user_id=from_user.id,
        target_user_id=target_user.id,
        reason_id=reason.id,
    )
    await complaint_repo.set_status(complaint.id, "rejected", resolver_id=from_user.id)
    await db_session.flush()
    await db_session.refresh(complaint)
    assert complaint.status == "rejected"


# ------------------------------------------------------------------ #
# 10.5 Аллея — создание поста с expires_at
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_alley_create_post_with_expires_at(db_session) -> None:
    """CreatorRepository.create_post создаёт пост с правильным expires_at."""
    admin_user = await _make_user(db_session, telegram_id=7004001)

    from sqlalchemy import select

    from app.db.models.dictionaries import CreatorCategory

    cat = (await db_session.execute(select(CreatorCategory).limit(1))).scalar_one()

    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(days=30)

    repo = CreatorRepository(db_session)
    post = await repo.create_post(
        author_display_name="Test Creator",
        category_id=cat.id,
        description="Test description",
        telegram_link="https://t.me/testchannel",
        published_at=now,
        expires_at=expires_at,
        is_published=True,
        is_pending_review=False,
        created_by_admin_id=admin_user.id,
    )
    assert post.id is not None
    assert post.expires_at is not None
    # expires_at должен быть ~30 дней от now
    diff = post.expires_at - now
    assert timedelta(days=29) <= diff <= timedelta(days=31)


# ------------------------------------------------------------------ #
# 10.6 Premium ручная выдача
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_premium_grant_manual(db_session) -> None:
    """UserRepository.set_premium выдаёт premium пользователю."""
    user = await _make_user(db_session, telegram_id=7005001)
    until = datetime.now(tz=UTC) + timedelta(days=30)

    user_repo = UserRepository(db_session)
    prem_repo = PremiumRepository(db_session)

    await user_repo.set_premium(user.id, until)
    await prem_repo.create_subscription(
        user_id=user.id,
        ends_at=until,
        granted_by="manual",
    )
    await db_session.flush()
    await db_session.refresh(user)
    assert user.is_premium is True


@pytest.mark.asyncio
async def test_premium_revoke(db_session) -> None:
    """UserRepository.clear_premium снимает is_premium."""
    user = await _make_user(db_session, telegram_id=7005002)
    until = datetime.now(tz=UTC) + timedelta(days=30)
    user_repo = UserRepository(db_session)
    await user_repo.set_premium(user.id, until)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.is_premium is True

    await user_repo.clear_premium(user.id)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.is_premium is False


# ------------------------------------------------------------------ #
# 10.7 Создание промо-поста
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_promo_create_draft(db_session) -> None:
    """PromoRepository.create_draft сохраняет пост в БД."""
    admin_user = await _make_user(db_session, telegram_id=7006001)
    promo_repo = PromoRepository(db_session)
    post = await promo_repo.create_draft(
        text="Test broadcast text",
        target_segment="all",
        created_by_admin_id=admin_user.id,
        status="queued",
    )
    assert post.id is not None
    assert post.text == "Test broadcast text"
    assert post.status == "queued"


# ------------------------------------------------------------------ #
# 10.8.2 Стоп-слово добавление + Redis-кэш инвалидирован
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_stopword_add_and_cache_invalidated(db_session, fake_redis) -> None:
    """add_stop_word добавляет запись + инвалидирует Redis-кэш."""
    mod_repo = ModerationRepository(db_session, fake_redis)

    # Предзаполним кэш
    await fake_redis.set("stop_words:version", "1")
    await fake_redis.set("stop_words:v1", "cached_data")

    sw = await mod_repo.add_stop_word(
        pattern="test_admin_word_xyz",
        kind="word",
        category="other",
    )
    assert sw.id is not None
    assert sw.pattern == "test_admin_word_xyz"

    # После add_stop_word кэш должен быть инвалидирован (версия инкрементирована)
    new_version = await fake_redis.get("stop_words:version")
    assert new_version is not None
    assert int(new_version) > 1


# ------------------------------------------------------------------ #
# 10.10 Аналитика aggregate
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_analytics_aggregate(db_session) -> None:
    """AnalyticsRepository.aggregate_by_event_type возвращает правильные счётчики."""
    user = await _make_user(db_session, telegram_id=7007001)
    analytics_repo = AnalyticsRepository(db_session)

    now = datetime.now(tz=UTC)
    # Записываем 3 события одного типа и 1 другого
    for _ in range(3):
        await analytics_repo.log_event(user.id, EventType.LIKE)
    await analytics_repo.log_event(user.id, EventType.DISLIKE)
    await db_session.flush()

    since = now - timedelta(seconds=10)
    until = now + timedelta(seconds=60)
    counts = await analytics_repo.aggregate_by_event_type(since, until)

    assert counts.get(EventType.LIKE, 0) >= 3
    assert counts.get(EventType.DISLIKE, 0) >= 1


@pytest.mark.asyncio
async def test_admin_repo_top_violators(db_session) -> None:
    """AdminRepository.top_violators возвращает список нарушителей по убыванию жалоб."""
    from sqlalchemy import select

    from app.db.models.dictionaries import ComplaintReason

    reason = (await db_session.execute(select(ComplaintReason).limit(1))).scalar_one()
    from_user = await _make_user(db_session, telegram_id=7008001)
    target_user = await _make_user(db_session, telegram_id=7008002)

    complaint_repo = ComplaintRepository(db_session)
    for _ in range(3):
        await complaint_repo.create(
            from_user_id=from_user.id,
            target_user_id=target_user.id,
            reason_id=reason.id,
        )
    await db_session.flush()

    admin_repo = AdminRepository(db_session)
    violators = await admin_repo.top_violators(limit=10)
    # top_violators возвращает telegram_id (для кликабельной ссылки в админке).
    violator_tg_ids = [v[0] for v in violators]
    assert target_user.telegram_id in violator_tg_ids
