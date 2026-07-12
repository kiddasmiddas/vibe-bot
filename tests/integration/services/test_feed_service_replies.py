"""Тесты FeedService.create_comment с parent_id — ветки глубины 1.

Покрываем:
- корневой комментарий → parent NULL, адресат пуша об ответе None;
- ответ на корневой → parent = корень, адресат = автор корня;
- ответ на ответ → прикрепляется к КОРНЮ, адресат = автор ответа (на который тапнули);
- parent из чужого поста / удалённый / несуществующий → 404;
- выдача: list_comments_cursor отдаёт только корни, list_replies_for_comments — ветки.
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


@dataclass
class _StubTextResult:
    approved: bool
    decision: str
    reason: str | None = None


class _StubModeration:
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
    async def get_int(self, key: str) -> int | None:
        return None  # везде дефолты


def _make_service(db: AsyncSession) -> FeedService:
    return FeedService(
        db,
        feed_repo=FeedRepository(db),
        settings_repo=_StubSettings(),  # type: ignore[arg-type]
        analytics_repo=AnalyticsRepository(db),
        moderation_service=_StubModeration(),  # type: ignore[arg-type]
    )


async def _make_user(db: AsyncSession, telegram_id: int) -> Any:
    return await UserRepository(db).create(telegram_id=telegram_id, username=f"u{telegram_id}")


async def _make_post(db: AsyncSession, author_user_id: int) -> int:
    now = datetime.now(tz=UTC)
    post = await FeedRepository(db).create_post(
        author_user_id=author_user_id,
        author_name="Author",
        text="post",
        status="active",
        is_pending_review=False,
        published_at=now,
        expires_at=now + timedelta(hours=48),
    )
    return post.id


def _profile() -> Profile:
    return Profile(nickname="Tester")


@pytest.mark.asyncio
async def test_root_comment_has_no_parent(db_session: AsyncSession) -> None:
    author = await _make_user(db_session, 71_001)
    commenter = await _make_user(db_session, 71_002)
    post_id = await _make_post(db_session, author.id)
    svc = _make_service(db_session)

    comment_id, reply_to = await svc.create_comment(
        user=commenter,
        profile=_profile(),
        post_id=post_id,
        text="привет",
        media_type=None,
        media_file_id=None,
    )

    assert reply_to is None
    comment = await FeedRepository(db_session).get_comment(comment_id)
    assert comment is not None and comment.parent_comment_id is None


@pytest.mark.asyncio
async def test_reply_to_root(db_session: AsyncSession) -> None:
    author = await _make_user(db_session, 71_003)
    alice = await _make_user(db_session, 71_004)
    bob = await _make_user(db_session, 71_005)
    post_id = await _make_post(db_session, author.id)
    svc = _make_service(db_session)

    root_id, _ = await svc.create_comment(
        user=alice,
        profile=_profile(),
        post_id=post_id,
        text="корень",
        media_type=None,
        media_file_id=None,
    )
    reply_id, reply_to = await svc.create_comment(
        user=bob,
        profile=_profile(),
        post_id=post_id,
        text="ответ",
        media_type=None,
        media_file_id=None,
        parent_id=root_id,
    )

    assert reply_to == alice.id
    reply = await FeedRepository(db_session).get_comment(reply_id)
    assert reply is not None and reply.parent_comment_id == root_id


@pytest.mark.asyncio
async def test_reply_to_reply_attaches_to_root(db_session: AsyncSession) -> None:
    """Глубина 1: ответ на ответ уходит в корень, но пуш — автору ответа."""
    author = await _make_user(db_session, 71_006)
    alice = await _make_user(db_session, 71_007)
    bob = await _make_user(db_session, 71_008)
    carol = await _make_user(db_session, 71_009)
    post_id = await _make_post(db_session, author.id)
    svc = _make_service(db_session)

    root_id, _ = await svc.create_comment(
        user=alice,
        profile=_profile(),
        post_id=post_id,
        text="корень",
        media_type=None,
        media_file_id=None,
    )
    bob_reply_id, _ = await svc.create_comment(
        user=bob,
        profile=_profile(),
        post_id=post_id,
        text="ответ Боба",
        media_type=None,
        media_file_id=None,
        parent_id=root_id,
    )
    carol_reply_id, reply_to = await svc.create_comment(
        user=carol,
        profile=_profile(),
        post_id=post_id,
        text="ответ Кэрол Бобу",
        media_type=None,
        media_file_id=None,
        parent_id=bob_reply_id,
    )

    assert reply_to == bob.id  # пуш — тому, на кого тапнули
    carol_reply = await FeedRepository(db_session).get_comment(carol_reply_id)
    assert carol_reply is not None and carol_reply.parent_comment_id == root_id  # но ветка корня


@pytest.mark.asyncio
async def test_reply_to_foreign_post_comment_404(db_session: AsyncSession) -> None:
    author = await _make_user(db_session, 71_010)
    commenter = await _make_user(db_session, 71_011)
    post_a = await _make_post(db_session, author.id)
    post_b = await _make_post(db_session, author.id)
    svc = _make_service(db_session)

    root_in_a, _ = await svc.create_comment(
        user=commenter,
        profile=_profile(),
        post_id=post_a,
        text="в посте A",
        media_type=None,
        media_file_id=None,
    )
    with pytest.raises(FeedServiceError) as exc:
        await svc.create_comment(
            user=commenter,
            profile=_profile(),
            post_id=post_b,
            text="не туда",
            media_type=None,
            media_file_id=None,
            parent_id=root_in_a,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reply_to_deleted_or_missing_parent_404(db_session: AsyncSession) -> None:
    author = await _make_user(db_session, 71_012)
    commenter = await _make_user(db_session, 71_013)
    post_id = await _make_post(db_session, author.id)
    svc = _make_service(db_session)
    repo = FeedRepository(db_session)

    root_id, _ = await svc.create_comment(
        user=commenter,
        profile=_profile(),
        post_id=post_id,
        text="удалят",
        media_type=None,
        media_file_id=None,
    )
    await repo.set_comment_status(root_id, "deleted_by_user")

    for bad_parent in (root_id, 999_999_999):
        with pytest.raises(FeedServiceError) as exc:
            await svc.create_comment(
                user=commenter,
                profile=_profile(),
                post_id=post_id,
                text="ответ",
                media_type=None,
                media_file_id=None,
                parent_id=bad_parent,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_listing_roots_and_replies(db_session: AsyncSession) -> None:
    author = await _make_user(db_session, 71_014)
    commenter = await _make_user(db_session, 71_015)
    post_id = await _make_post(db_session, author.id)
    svc = _make_service(db_session)
    repo = FeedRepository(db_session)

    root1, _ = await svc.create_comment(
        user=commenter,
        profile=_profile(),
        post_id=post_id,
        text="корень 1",
        media_type=None,
        media_file_id=None,
    )
    root2, _ = await svc.create_comment(
        user=commenter,
        profile=_profile(),
        post_id=post_id,
        text="корень 2",
        media_type=None,
        media_file_id=None,
    )
    reply1, _ = await svc.create_comment(
        user=author,
        profile=_profile(),
        post_id=post_id,
        text="ответ 1",
        media_type=None,
        media_file_id=None,
        parent_id=root1,
    )

    roots, _cursor = await repo.list_comments_cursor(post_id=post_id, cursor=None, limit=20)
    assert [c.id for c in roots] == [root1, root2]  # ответы не в пагинации

    replies = await repo.list_replies_for_comments([root1, root2])
    assert [r.id for r in replies.get(root1, [])] == [reply1]
    assert root2 not in replies
