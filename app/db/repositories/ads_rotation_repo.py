"""Доступ к пулу авто-рекламы (`ad_rotation_posts`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ads_rotation import AdRotationPost


class AdsRotationRepository:
    """CRUD пула рекламы + round-robin выбор следующего креатива."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **fields: Any) -> AdRotationPost:
        post = AdRotationPost(**fields)
        self._session.add(post)
        await self._session.flush()
        return post

    async def get_by_id(self, ad_id: int) -> AdRotationPost | None:
        return await self._session.get(AdRotationPost, ad_id)

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[AdRotationPost]:
        stmt = (
            select(AdRotationPost)
            .order_by(AdRotationPost.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count(self) -> int:
        return (await self._session.execute(select(func.count(AdRotationPost.id)))).scalar_one()

    async def update_fields(self, ad_id: int, **fields: Any) -> AdRotationPost:
        if fields:
            await self._session.execute(
                update(AdRotationPost).where(AdRotationPost.id == ad_id).values(**fields)
            )
            await self._session.flush()
        post = await self._session.get(AdRotationPost, ad_id)
        if post is None:
            raise ValueError(f"AdRotationPost {ad_id} not found")
        await self._session.refresh(post)
        return post

    async def delete(self, ad_id: int) -> bool:
        post = await self._session.get(AdRotationPost, ad_id)
        if post is None:
            return False
        await self._session.delete(post)
        await self._session.flush()
        return True

    async def pick_next(self) -> AdRotationPost | None:
        """Выбрать следующий креатив по кругу и отметить показ.

        Round-robin: наименее недавно показанный (`last_shown_at` NULLS FIRST), при
        равенстве — по `id`. Инкрементит `shown_count` и ставит `last_shown_at=now()`.
        Возвращает выбранный креатив или `None`, если пул пуст.
        """
        ad_id = (
            await self._session.execute(
                select(AdRotationPost.id)
                .order_by(
                    AdRotationPost.last_shown_at.asc().nulls_first(),
                    AdRotationPost.id.asc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if ad_id is None:
            return None
        # clock_timestamp() (а не now()): меняется по-стейтментно, поэтому несколько
        # подряд показов получают строго возрастающее время — ротация корректна даже
        # в рамках одной транзакции (now()/transaction_timestamp был бы константой).
        await self._session.execute(
            update(AdRotationPost)
            .where(AdRotationPost.id == ad_id)
            .values(
                shown_count=AdRotationPost.shown_count + 1,
                last_shown_at=func.clock_timestamp(),
            )
        )
        await self._session.flush()
        post = await self._session.get(AdRotationPost, ad_id)
        if post is not None:
            await self._session.refresh(post)
        return post
