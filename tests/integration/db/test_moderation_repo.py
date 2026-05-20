from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.repositories.moderation_repo import ModerationRepository


@pytest.mark.asyncio
async def test_list_active_stop_words_returns_seeded(db_session) -> None:
    repo = ModerationRepository(db_session)
    items = await repo.list_active_stop_words()
    categories = {w.category for w in items}
    assert {"hate_speech", "link", "adult_keyword"}.issubset(categories)
    # Сортировка: kind, потом pattern. regex'ы перед word'ами в нашей сидинг-сетке.
    assert items[0].kind in ("regex", "word")


@pytest.mark.asyncio
async def test_add_stop_word_increments_cache_version(db_session, fake_redis) -> None:
    repo = ModerationRepository(db_session, redis=fake_redis)
    # Прогреваем кэш — версия инициализируется в 1.
    await repo.list_active_stop_words()
    assert await fake_redis.get("stop_words:version") == "1"

    await repo.add_stop_word(
        pattern="testword_unique",
        kind="word",
        category="other",
        admin_id=None,
    )
    # Кэш инвалидируется через INCR — версия становится 2.
    assert await fake_redis.get("stop_words:version") == "2"


@pytest.mark.asyncio
async def test_deactivate_stop_word_excludes_from_active(db_session) -> None:
    repo = ModerationRepository(db_session)
    word = await repo.add_stop_word(
        pattern="to_deactivate_unique",
        kind="word",
        category="other",
        admin_id=None,
    )
    await db_session.flush()
    before = {w.pattern for w in await repo.list_active_stop_words()}
    assert "to_deactivate_unique" in before

    await repo.deactivate_stop_word(word.id)
    await db_session.flush()
    after = {w.pattern for w in await repo.list_active_stop_words()}
    assert "to_deactivate_unique" not in after


@pytest.mark.asyncio
async def test_log_moderation_writes_record(db_session) -> None:
    repo = ModerationRepository(db_session)
    await repo.log_moderation(
        user_id=None,
        target_kind="profile_bio",
        target_id=123,
        check_type="text",
        decision="rejected",
        reason="stop_word: spam",
        matched_terms=["spam"],
    )
    await db_session.flush()
    pending = await repo.list_pending_review(target_kind="profile_bio")
    # rejected ≠ manual_review, поэтому в pending пусто.
    assert pending == []


@pytest.mark.asyncio
async def test_log_moderation_manual_review_appears_in_pending(db_session) -> None:
    repo = ModerationRepository(db_session)
    await repo.log_moderation(
        user_id=None,
        target_kind="profile_media",
        target_id=42,
        check_type="nsfw_image",
        decision="manual_review",
        nsfw_score=0.5,
    )
    await db_session.flush()
    pending = await repo.list_pending_review(target_kind="profile_media")
    assert len(pending) == 1
    assert pending[0].decision == "manual_review"
    assert pending[0].target_id == 42


@pytest.mark.asyncio
async def test_log_moderation_swallows_errors() -> None:
    """log_moderation не должен пробрасывать исключения наружу."""

    class _BrokenSession:
        def add(self, _obj):
            raise RuntimeError("session is closed")

        async def flush(self) -> None:
            pass

    repo = ModerationRepository(_BrokenSession())  # type: ignore[arg-type]
    # Не должно бросить.
    await repo.log_moderation(
        user_id=None,
        target_kind="profile_bio",
        target_id=1,
        check_type="text",
        decision="rejected",
    )


@pytest.mark.asyncio
async def test_invalid_kind_violates_check(db_session) -> None:
    repo = ModerationRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.add_stop_word(
            pattern="bad_kind_word",
            kind="not_a_kind",
            category="other",
            admin_id=None,
        )


@pytest.mark.asyncio
async def test_invalid_category_violates_check(db_session) -> None:
    repo = ModerationRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.add_stop_word(
            pattern="bad_category_word",
            kind="word",
            category="not_a_category",
            admin_id=None,
        )
