"""Интеграционные тесты на POST /api/feed/upload.

Цель — закрепить выбор chat_id для загрузки медиа через бота:
- если задан `MEDIA_STAGING_CHAT_ID` — отправляем туда (личка админов не страдает);
- если не задан, но есть `ADMIN_TELEGRAM_IDS` — legacy-fallback на admin[0] с warning;
- если ни того, ни другого — 503.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dictionaries import Gender, Vibe
from app.db.models.user import User
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
    """Создаёт завершённую анкету (требуется для current_user_with_profile)."""
    profile_repo = ProfileRepository(db)
    existing = await profile_repo.get_by_user_id(user.id)
    if existing is not None and existing.is_completed:
        return

    male = (await db.execute(select(Gender).where(Gender.code == "male"))).scalar_one()
    vibe_code = f"upl_vibe_{user.telegram_id}"
    vibe = (await db.execute(select(Vibe).where(Vibe.code == vibe_code))).scalar_one_or_none()
    if vibe is None:
        vibe = Vibe(
            code=vibe_code,
            title=f"Upl vibe {user.telegram_id}",
            number=9200 + (user.telegram_id % 1000),
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


class _FakeBot:
    """Минимальный заместитель `aiogram.Bot` для тестов upload-эндпоинта.

    Запоминает chat_id последнего вызова send_photo / send_animation и
    возвращает фейковый Message c photo[0].file_id == "stub_file_id".
    """

    def __init__(self) -> None:
        self.send_photo_calls: list[dict[str, Any]] = []
        self.send_animation_calls: list[dict[str, Any]] = []

    async def send_photo(self, *, chat_id: int, photo: Any) -> Any:
        self.send_photo_calls.append({"chat_id": chat_id})
        return SimpleNamespace(photo=[SimpleNamespace(file_id="stub_file_id")])

    async def send_animation(self, *, chat_id: int, animation: Any) -> Any:
        self.send_animation_calls.append({"chat_id": chat_id})
        return SimpleNamespace(animation=SimpleNamespace(file_id="stub_anim_id"))


@pytest.fixture
def fake_bot(monkeypatch: pytest.MonkeyPatch) -> _FakeBot:
    bot = _FakeBot()
    monkeypatch.setattr("app.api.routes.feed._get_upload_bot", lambda: bot)
    return bot


@pytest.fixture(autouse=True)
def _stub_nsfw(monkeypatch: pytest.MonkeyPatch) -> None:
    """В тестах нет NudeNet и реального TG — стабим check_image на approved."""
    from app.services.content_moderation_service import ImageModerationResult

    async def _ok(self: Any, image_bytes: bytes, **kwargs: Any) -> ImageModerationResult:
        return ImageModerationResult(decision="approved", nsfw_score=0.0, reason=None)

    monkeypatch.setattr(
        "app.services.content_moderation_service.ContentModerationService.check_image",
        _ok,
    )


@pytest.fixture(autouse=True)
def _stub_redis_for_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяем Redis в feed-роуте, иначе DNS `redis` не резолвится в тестах."""
    from unittest.mock import AsyncMock, MagicMock

    fake = AsyncMock()
    fake.get = AsyncMock(return_value=None)
    fake.set = AsyncMock(return_value=True)
    fake.delete = AsyncMock(return_value=0)
    # redis-py: pipeline().incr/expire — синхронные builder-методы; execute — async.
    pipe = MagicMock()
    pipe.incr = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, True])
    fake.pipeline = MagicMock(return_value=pipe)
    monkeypatch.setattr("app.api.routes.feed.get_redis", lambda: fake)


@pytest.fixture
def _settings_snapshot():
    """Сохраняем/восстанавливаем поля settings, чтобы тесты не текли друг в друга."""
    from app.config import settings

    snap = (settings.media_staging_chat_id, list(settings.admin_telegram_ids))
    try:
        yield settings
    finally:
        settings.media_staging_chat_id = snap[0]  # type: ignore[misc]
        settings.admin_telegram_ids = snap[1]  # type: ignore[misc]


@pytest.mark.asyncio
async def test_upload_uses_staging_chat_when_configured(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    fake_bot: _FakeBot,
    _settings_snapshot: Any,
) -> None:
    """MEDIA_STAGING_CHAT_ID задан → send_photo вызывается со staging-chat."""
    user = await _ensure_user(api_db_session, telegram_id=400_001)
    await _ensure_profile(api_db_session, user)

    _settings_snapshot.media_staging_chat_id = -1009999999
    _settings_snapshot.admin_telegram_ids = [111, 222]

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    files = {"file": ("a.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}
    resp = await api_client.post(
        "/api/feed/upload",
        files=files,
        headers={"X-Telegram-Init-Data": header},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["file_id"] == "stub_file_id"
    assert body["media_type"] == "photo"

    assert len(fake_bot.send_photo_calls) == 1
    assert fake_bot.send_photo_calls[0]["chat_id"] == -1009999999
    # admin[0] не должен быть использован
    assert all(c["chat_id"] != 111 for c in fake_bot.send_photo_calls)


@pytest.mark.asyncio
async def test_upload_falls_back_to_admin_when_no_staging(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    fake_bot: _FakeBot,
    _settings_snapshot: Any,
) -> None:
    """staging не настроен, есть admin_ids → legacy-fallback на admin[0]."""
    user = await _ensure_user(api_db_session, telegram_id=400_002)
    await _ensure_profile(api_db_session, user)

    _settings_snapshot.media_staging_chat_id = None
    _settings_snapshot.admin_telegram_ids = [123_456, 999]

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    files = {"file": ("a.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}
    resp = await api_client.post(
        "/api/feed/upload",
        files=files,
        headers={"X-Telegram-Init-Data": header},
    )

    assert resp.status_code == 200, resp.text
    assert len(fake_bot.send_photo_calls) == 1
    assert fake_bot.send_photo_calls[0]["chat_id"] == 123_456


@pytest.mark.asyncio
async def test_upload_503_when_nothing_configured(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    fake_bot: _FakeBot,
    _settings_snapshot: Any,
) -> None:
    """Нет ни MEDIA_STAGING_CHAT_ID, ни ADMIN_TELEGRAM_IDS → 503."""
    user = await _ensure_user(api_db_session, telegram_id=400_003)
    await _ensure_profile(api_db_session, user)

    _settings_snapshot.media_staging_chat_id = None
    _settings_snapshot.admin_telegram_ids = []

    header = build_init_data(TEST_BOT_TOKEN, user.telegram_id)
    files = {"file": ("a.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}
    resp = await api_client.post(
        "/api/feed/upload",
        files=files,
        headers={"X-Telegram-Init-Data": header},
    )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Media upload not configured"
    # Бот вызываться не должен
    assert fake_bot.send_photo_calls == []
    assert fake_bot.send_animation_calls == []
