from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.premium import PremiumSubscription


class PremiumRepository:
    """Доступ к таблице premium_subscriptions. Логика «активна ли сейчас» — здесь же."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_subscription(self, user_id: int) -> PremiumSubscription | None:
        """Возвращает активную подписку пользователя (ends_at > now()), либо None.

        Если активных несколько (продление через создание нового ряда) — берём с самой
        поздней `ends_at`.
        """
        now = datetime.now(tz=UTC)
        stmt = (
            select(PremiumSubscription)
            .where(
                PremiumSubscription.user_id == user_id,
                PremiumSubscription.ends_at > now,
            )
            .order_by(desc(PremiumSubscription.ends_at))
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_subscription(
        self,
        *,
        user_id: int,
        ends_at: datetime,
        granted_by: str,
        payment_id: int | None = None,
        granted_by_user_id: int | None = None,
    ) -> PremiumSubscription:
        sub = PremiumSubscription(
            user_id=user_id,
            ends_at=ends_at,
            granted_by=granted_by,
            payment_id=payment_id,
            granted_by_user_id=granted_by_user_id,
        )
        self._session.add(sub)
        await self._session.flush()
        return sub

    async def extend_subscription(
        self,
        user_id: int,
        until: datetime,
        *,
        granted_by: str = "purchase",
        payment_id: int | None = None,
        granted_by_user_id: int | None = None,
    ) -> PremiumSubscription:
        """Если есть активная подписка — продлевает ends_at (если until позже текущего).
        Иначе создаёт новую."""
        active = await self.get_active_subscription(user_id)
        if active is not None:
            if until > active.ends_at:
                stmt = (
                    update(PremiumSubscription)
                    .where(PremiumSubscription.id == active.id)
                    .values(ends_at=until)
                )
                await self._session.execute(stmt)
                await self._session.flush()
                await self._session.refresh(active)
            return active
        return await self.create_subscription(
            user_id=user_id,
            ends_at=until,
            granted_by=granted_by,
            payment_id=payment_id,
            granted_by_user_id=granted_by_user_id,
        )
