from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.promo import PromoPost, PromoPostRecipient


class PromoRepository:
    """Доступ к промо-постам и таблице получателей рассылки."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_draft(self, **fields: Any) -> PromoPost:
        # status по умолчанию 'draft' уже задан на уровне модели — позволяем
        # вызывающему переопределить любые поля.
        post = PromoPost(**fields)
        self._session.add(post)
        await self._session.flush()
        return post

    async def update(self, promo_post_id: int, **fields: Any) -> PromoPost:
        if fields:
            stmt = update(PromoPost).where(PromoPost.id == promo_post_id).values(**fields)
            await self._session.execute(stmt)
            await self._session.flush()
        # expire, чтобы перечитать актуальные значения после UPDATE.
        post = await self._session.get(PromoPost, promo_post_id)
        if post is None:
            raise ValueError(f"PromoPost {promo_post_id} not found")
        await self._session.refresh(post)
        return post

    async def get_by_id(self, promo_post_id: int) -> PromoPost | None:
        return await self._session.get(PromoPost, promo_post_id)

    async def list_by_status(
        self,
        status: str,
        limit: int,
        offset: int = 0,
    ) -> list[PromoPost]:
        stmt = (
            select(PromoPost)
            .where(PromoPost.status == status)
            .order_by(PromoPost.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_recipients(self, promo_post_id: int, user_ids: list[int]) -> None:
        """Bulk-вставка получателей. Дубли по (promo_post_id, user_id) пропускаются."""
        if not user_ids:
            return
        rows = [{"promo_post_id": promo_post_id, "user_id": uid} for uid in user_ids]
        stmt = pg_insert(PromoPostRecipient).values(rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["promo_post_id", "user_id"],
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def mark_recipient_sent(self, promo_post_id: int, user_id: int) -> None:
        stmt = (
            update(PromoPostRecipient)
            .where(
                PromoPostRecipient.promo_post_id == promo_post_id,
                PromoPostRecipient.user_id == user_id,
            )
            .values(status="sent", sent_at=func.now(), error=None)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def mark_recipient_failed(
        self,
        promo_post_id: int,
        user_id: int,
        error: str,
    ) -> None:
        stmt = (
            update(PromoPostRecipient)
            .where(
                PromoPostRecipient.promo_post_id == promo_post_id,
                PromoPostRecipient.user_id == user_id,
            )
            .values(status="failed", error=error)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_scheduled_ready(self, now: datetime) -> list[PromoPost]:
        """Возвращает посты со status='queued' и scheduled_at <= now (для шедулера)."""
        stmt = select(PromoPost).where(
            PromoPost.status == "queued",
            PromoPost.scheduled_at <= now,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_recipient(self, promo_post_id: int, user_id: int) -> PromoPostRecipient | None:
        """Возвращает запись получателя или None если не найдена."""
        stmt = select(PromoPostRecipient).where(
            PromoPostRecipient.promo_post_id == promo_post_id,
            PromoPostRecipient.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_pending_recipients(self, promo_post_id: int) -> list[PromoPostRecipient]:
        """Возвращает получателей со status='pending' для данного поста."""
        stmt = select(PromoPostRecipient).where(
            PromoPostRecipient.promo_post_id == promo_post_id,
            PromoPostRecipient.status == "pending",
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def recount_progress(self, promo_post_id: int) -> PromoPost:
        """Пересчитывает total/delivered/failed из таблицы получателей и сохраняет в PromoPost."""
        stmt = select(
            func.count(PromoPostRecipient.id),
            func.count().filter(PromoPostRecipient.status == "sent"),
            func.count().filter(PromoPostRecipient.status == "failed"),
        ).where(PromoPostRecipient.promo_post_id == promo_post_id)
        total, delivered, failed = (await self._session.execute(stmt)).one()
        upd = (
            update(PromoPost)
            .where(PromoPost.id == promo_post_id)
            .values(
                total_recipients=int(total),
                delivered_count=int(delivered),
                failed_count=int(failed),
            )
        )
        await self._session.execute(upd)
        await self._session.flush()
        post = await self._session.get(PromoPost, promo_post_id)
        if post is None:
            raise ValueError(f"PromoPost {promo_post_id} not found")
        await self._session.refresh(post)
        return post
