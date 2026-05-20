from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy import delete as sa_delete_import
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.creators import CreatorPost, CreatorPostPhoto


class CreatorRepository:
    """Доступ к creator_posts и creator_post_photos."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, post_id: int) -> CreatorPost | None:
        return await self._session.get(CreatorPost, post_id)

    async def create_post(self, **fields: Any) -> CreatorPost:
        post = CreatorPost(**fields)
        self._session.add(post)
        await self._session.flush()
        return post

    async def add_photo(self, post_id: int, file_id: str, position: int) -> CreatorPostPhoto:
        photo = CreatorPostPhoto(post_id=post_id, file_id=file_id, position=position)
        self._session.add(photo)
        await self._session.flush()
        return photo

    async def list_published(self, limit: int, offset: int = 0) -> list[CreatorPost]:
        """Опубликованные, не истёкшие и одобренные модерацией посты — лента Mini App.

        : лента отдаёт только посты с
        `is_published=True AND expires_at > now() AND is_pending_review=False`.
        """
        now = datetime.now(tz=UTC)
        stmt = (
            select(CreatorPost)
            .where(
                CreatorPost.is_published.is_(True),
                CreatorPost.expires_at > now,
                CreatorPost.is_pending_review.is_(False),
            )
            .order_by(desc(CreatorPost.published_at), desc(CreatorPost.id))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_expiring_soon(self, days: int) -> list[CreatorPost]:
        """Опубликованные посты, истекающие в ближайшие `days` дней.
        Используется шедулером для уведомлений автору."""
        now = datetime.now(tz=UTC)
        horizon = now + timedelta(days=days)
        stmt = (
            select(CreatorPost)
            .where(
                CreatorPost.is_published.is_(True),
                CreatorPost.expires_at > now,
                CreatorPost.expires_at <= horizon,
            )
            .order_by(CreatorPost.expires_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_published_cursor(
        self,
        cursor: tuple[datetime, int] | None,
        limit: int,
    ) -> tuple[list[CreatorPost], tuple[datetime, int] | None]:
        """Опубликованные посты с курсорной пагинацией.

        ORDER BY published_at DESC, id DESC.  Курсор — пара (published_at, id)
        последнего возвращённого поста: следующая страница содержит только записи,
        идущие строго после него по составному ключу.

        Возвращает `(posts, next_cursor)`, где `next_cursor is None` означает конец ленты.
        """
        now = datetime.now(tz=UTC)
        base_filter = and_(
            CreatorPost.is_published.is_(True),
            CreatorPost.expires_at > now,
            CreatorPost.is_pending_review.is_(False),
            # published_at NULL — это черновики/предпубликации; в ленту они не
            # должны попадать в принципе, а ещё их нельзя засунуть в курсор.
            CreatorPost.published_at.is_not(None),
        )

        if cursor is not None:
            cursor_ts, cursor_id = cursor
            # Composite cursor: (published_at, id) < (cursor_ts, cursor_id)
            # Нужны строки, у которых published_at < cursor_ts
            # ИЛИ (published_at == cursor_ts AND id < cursor_id).
            cursor_filter = or_(
                CreatorPost.published_at < cursor_ts,
                and_(
                    CreatorPost.published_at == cursor_ts,
                    CreatorPost.id < cursor_id,
                ),
            )
            stmt = (
                select(CreatorPost)
                .where(base_filter, cursor_filter)
                .order_by(desc(CreatorPost.published_at), desc(CreatorPost.id))
                .limit(limit)
            )
        else:
            stmt = (
                select(CreatorPost)
                .where(base_filter)
                .order_by(desc(CreatorPost.published_at), desc(CreatorPost.id))
                .limit(limit)
            )

        posts = list((await self._session.execute(stmt)).scalars().all())
        next_cursor: tuple[datetime, int] | None = None
        if len(posts) == limit:
            last = posts[-1]
            # base_filter гарантирует, что published_at не NULL.
            assert last.published_at is not None
            next_cursor = (last.published_at, last.id)
        return posts, next_cursor

    async def get_photos_for_post(self, post_id: int) -> list[CreatorPostPhoto]:
        """Фото поста, отсортированные по position."""
        stmt = (
            select(CreatorPostPhoto)
            .where(CreatorPostPhoto.post_id == post_id)
            .order_by(CreatorPostPhoto.position)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_photos_for_posts(self, post_ids: list[int]) -> dict[int, list[CreatorPostPhoto]]:
        """Фото для нескольких постов одним запросом.  Возвращает dict post_id -> photos."""
        if not post_ids:
            return {}
        stmt = (
            select(CreatorPostPhoto)
            .where(CreatorPostPhoto.post_id.in_(post_ids))
            .order_by(CreatorPostPhoto.post_id, CreatorPostPhoto.position)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        result: dict[int, list[CreatorPostPhoto]] = {pid: [] for pid in post_ids}
        for photo in rows:
            result[photo.post_id].append(photo)
        return result

    async def expire_post(self, post_id: int) -> None:
        """Мягкое снятие с публикации: выставляем is_published=False."""
        stmt = update(CreatorPost).where(CreatorPost.id == post_id).values(is_published=False)
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_all_posts(
        self,
        *,
        published_only: bool = False,
        expired_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CreatorPost]:
        """Список постов для администратора (все фильтры опциональны).

        Используется в разделе «Аллея» (10.5) и «На проверке» (10.8.1).
        """
        now = datetime.now(tz=UTC)
        stmt = select(CreatorPost)
        if published_only:
            stmt = stmt.where(CreatorPost.is_published.is_(True))
        if expired_only:
            stmt = stmt.where(
                or_(
                    CreatorPost.expires_at <= now,
                    CreatorPost.is_published.is_(False),
                )
            )
        stmt = stmt.order_by(desc(CreatorPost.id)).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_pending_review_posts(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[CreatorPost]:
        """Посты с is_pending_review=True — очередь ручной модерации (10.8.1)."""
        stmt = (
            select(CreatorPost)
            .where(CreatorPost.is_pending_review.is_(True))
            .order_by(CreatorPost.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete_post(self, post_id: int) -> None:
        """Физическое удаление поста (каскадно удаляет фото)."""
        await self._session.execute(sa_delete_import(CreatorPost).where(CreatorPost.id == post_id))
        await self._session.flush()

    async def approve_post(self, post_id: int) -> None:
        """Снимает флаг is_pending_review, пост появляется в ленте."""
        stmt = update(CreatorPost).where(CreatorPost.id == post_id).values(is_pending_review=False)
        await self._session.execute(stmt)
        await self._session.flush()

    async def extend_post(self, post_id: int, months: int) -> CreatorPost | None:
        """Продлевает expires_at на N месяцев относительно текущего значения или now()."""
        post = await self._session.get(CreatorPost, post_id)
        if post is None:
            return None
        base = (
            post.expires_at
            if post.expires_at and post.expires_at > datetime.now(tz=UTC)
            else datetime.now(tz=UTC)
        )
        # Приблизительно: 1 месяц = 30 дней.
        from datetime import timedelta

        new_expires = base + timedelta(days=30 * months)
        stmt = update(CreatorPost).where(CreatorPost.id == post_id).values(expires_at=new_expires)
        await self._session.execute(stmt)
        await self._session.flush()
        await self._session.refresh(post)
        return post
