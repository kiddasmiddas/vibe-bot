from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.models.moderation import ContentModerationLog
from app.db.repositories.moderation_repo import ModerationRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.services.content_moderation_service import (
    ContentModerationService,
    TextModerationResult,
)


class _FakeDetector:
    def __init__(self, *, is_available: bool, score: float | None) -> None:
        self.is_available = is_available
        self._score = score

    def score(self, image_bytes: bytes) -> float | None:
        return self._score


def _service(db_session) -> ContentModerationService:  # type: ignore[no-untyped-def]
    return ContentModerationService(ModerationRepository(db_session))


@pytest.mark.asyncio
async def test_clean_text_approved(db_session) -> None:
    svc = _service(db_session)
    res = await svc.check_text(
        "Привет, как дела?",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is True
    assert res.decision == "approved"
    assert res.matched_terms == []
    assert res.reason is None


@pytest.mark.asyncio
async def test_link_rejected_when_disallowed(db_session) -> None:
    svc = _service(db_session)
    res = await svc.check_text(
        "Заходи https://example.com",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is False
    assert res.decision == "rejected"
    assert res.reason == "link_detected"


@pytest.mark.asyncio
async def test_link_allowed_when_flag_set(db_session) -> None:
    svc = _service(db_session)
    res = await svc.check_text(
        "Заходи https://example.com",
        target_kind="complaint_comment",
        target_id=None,
        allow_links=True,
    )
    assert res.approved is True
    assert res.decision == "approved"


@pytest.mark.asyncio
async def test_link_t_me_rejected(db_session) -> None:
    svc = _service(db_session)
    res = await svc.check_text(
        "t.me/somechannel",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is False
    assert res.reason == "link_detected"


@pytest.mark.asyncio
async def test_mention_rejected(db_session) -> None:
    svc = _service(db_session)
    res = await svc.check_text(
        "пиши мне в @username",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is False
    assert res.reason == "link_detected"


@pytest.mark.asyncio
async def test_stop_word_rejected(db_session) -> None:
    repo = ModerationRepository(db_session)
    await repo.add_stop_word(
        pattern="нацизм",
        kind="word",
        category="hate_speech",
        admin_id=None,
    )
    await db_session.flush()

    svc = ContentModerationService(repo)
    res: TextModerationResult = await svc.check_text(
        "Я люблю нацизм",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is False
    assert res.reason == "stop_word"
    assert "нацизм" in res.matched_terms


@pytest.mark.asyncio
async def test_leet_substitution_detects_stop_word(db_session) -> None:
    repo = ModerationRepository(db_session)
    await repo.add_stop_word(
        pattern="нацизм",
        kind="word",
        category="hate_speech",
        admin_id=None,
    )
    await db_session.flush()

    svc = ContentModerationService(repo)
    res = await svc.check_text(
        "Я люблю н@цизм!",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is False
    assert "нацизм" in res.matched_terms


@pytest.mark.asyncio
async def test_spacing_trick_detects_stop_word(db_session) -> None:
    repo = ModerationRepository(db_session)
    await repo.add_stop_word(
        pattern="нацизм",
        kind="word",
        category="hate_speech",
        admin_id=None,
    )
    await db_session.flush()

    svc = ContentModerationService(repo)
    res = await svc.check_text(
        "н а ц и з м",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is False
    assert "нацизм" in res.matched_terms


@pytest.mark.asyncio
async def test_broken_regex_does_not_crash(db_session) -> None:
    repo = ModerationRepository(db_session)
    await repo.add_stop_word(
        pattern="(?invalid)",
        kind="regex",
        category="other",
        admin_id=None,
    )
    await db_session.flush()

    svc = ContentModerationService(repo)
    res = await svc.check_text(
        "hello",
        target_kind="profile_bio",
        target_id=None,
    )
    # Битый regex пропущен, других совпадений нет → approved.
    assert res.approved is True
    assert res.decision == "approved"


@pytest.mark.asyncio
async def test_moderation_logged(db_session) -> None:
    svc = _service(db_session)
    await svc.check_text(
        "Заходи https://example.com",
        target_kind="profile_bio",
        target_id=777,
        user_id=None,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(ContentModerationLog)
            .where(ContentModerationLog.target_id == 777)
            .order_by(ContentModerationLog.id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert row.target_kind == "profile_bio"
    assert row.check_type == "text"
    assert row.decision == "rejected"
    assert row.matched_terms is not None and len(row.matched_terms) >= 1


@pytest.mark.asyncio
async def test_empty_text_passes_without_log(db_session) -> None:
    svc = _service(db_session)
    before = (
        await db_session.execute(select(func.count()).select_from(ContentModerationLog))
    ).scalar_one()

    res = await svc.check_text(
        "",
        target_kind="profile_bio",
        target_id=None,
    )
    assert res.approved is True
    assert res.decision == "approved"

    await db_session.flush()
    after = (
        await db_session.execute(select(func.count()).select_from(ContentModerationLog))
    ).scalar_one()
    assert before == after


# --- NSFW image moderation (Промпт 3.5.2) ---


@pytest.mark.asyncio
async def test_check_image_manual_review_when_no_model(db_session, monkeypatch) -> None:
    # Сбрасываем lru_cache singleton-фабрики, чтобы получить «свежий» детектор
    # на гарантированно отсутствующем пути.
    from app.services import nudenet_singleton

    nudenet_singleton.get_nudenet_detector.cache_clear()
    monkeypatch.setattr(
        "app.services.content_moderation_service.get_nudenet_detector",
        lambda: _FakeDetector(is_available=False, score=None),
    )

    svc = _service(db_session)
    res = await svc.check_image(
        b"x" * 100,
        target_kind="profile_media",
        target_id=4242,
        user_id=None,
    )

    assert res.decision == "manual_review"
    assert res.nsfw_score is None
    assert res.reason == "model_unavailable"

    await db_session.flush()
    row = (
        await db_session.execute(
            select(ContentModerationLog)
            .where(ContentModerationLog.target_id == 4242)
            .order_by(ContentModerationLog.id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert row.check_type == "nsfw_image"
    assert row.decision == "manual_review"
    assert row.nsfw_score is None


@pytest.mark.asyncio
async def test_check_image_with_mocked_detector_approved(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.content_moderation_service.get_nudenet_detector",
        lambda: _FakeDetector(is_available=True, score=0.1),
    )
    svc = _service(db_session)
    res = await svc.check_image(
        b"img",
        target_kind="profile_media",
        target_id=1,
    )
    assert res.decision == "approved"
    assert res.nsfw_score == 0.1
    assert res.reason is None


@pytest.mark.asyncio
async def test_check_image_with_mocked_detector_manual_review(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.content_moderation_service.get_nudenet_detector",
        lambda: _FakeDetector(is_available=True, score=0.5),
    )
    # threshold 0.7 (по умолчанию из env), score 0.5 → попадает в серую зону.
    svc = _service(db_session)
    res = await svc.check_image(
        b"img",
        target_kind="profile_media",
        target_id=2,
    )
    assert res.decision == "manual_review"
    assert res.nsfw_score == 0.5


@pytest.mark.asyncio
async def test_check_image_with_mocked_detector_rejected(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.content_moderation_service.get_nudenet_detector",
        lambda: _FakeDetector(is_available=True, score=0.95),
    )
    svc = _service(db_session)
    res = await svc.check_image(
        b"img",
        target_kind="profile_media",
        target_id=3,
    )
    assert res.decision == "rejected"
    assert res.nsfw_score == 0.95
    assert res.reason == "nsfw_detected"


@pytest.mark.asyncio
async def test_check_image_threshold_from_settings(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.content_moderation_service.get_nudenet_detector",
        lambda: _FakeDetector(is_available=True, score=0.55),
    )
    settings_repo = SettingsRepository(db_session)
    await settings_repo.set("nsfw_threshold", "0.5")
    await db_session.flush()

    svc = ContentModerationService(
        ModerationRepository(db_session),
        settings_repo=settings_repo,
    )
    res = await svc.check_image(
        b"img",
        target_kind="profile_media",
        target_id=42,
    )
    # 0.55 >= 0.5 → rejected.
    assert res.decision == "rejected"
    assert res.nsfw_score == 0.55
