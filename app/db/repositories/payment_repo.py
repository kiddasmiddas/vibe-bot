from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.premium import Payment


class PaymentRepository:
    """Доступ к таблице payments. Все переходы статусов — через этот репозиторий."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, payment_id: int) -> Payment | None:
        return await self._session.get(Payment, payment_id)

    async def get_by_invoice_payload(self, payload: str) -> Payment | None:
        stmt = select(Payment).where(Payment.invoice_payload == payload)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_pending(
        self,
        *,
        user_id: int,
        amount_kop: int,
        purpose: str,
        invoice_payload: str,
        currency: str = "RUB",
        provider: str = "yookassa",
    ) -> Payment:
        payment = Payment(
            user_id=user_id,
            amount_kop=amount_kop,
            currency=currency,
            provider=provider,
            invoice_payload=invoice_payload,
            purpose=purpose,
            status="pending",
        )
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def update_invoice_payload(self, payment_id: int, payload: str) -> None:
        """Обновляет invoice_payload после того, как стал известен payment.id."""
        stmt = update(Payment).where(Payment.id == payment_id).values(invoice_payload=payload)
        await self._session.execute(stmt)
        await self._session.flush()

    async def mark_succeeded(
        self,
        payment_id: int,
        *,
        provider_charge_id: str | None,
        telegram_charge_id: str | None,
    ) -> None:
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id)
            .values(
                status="succeeded",
                provider_payment_charge_id=provider_charge_id,
                telegram_payment_charge_id=telegram_charge_id,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        # Сбрасываем кэшированный объект в identity-map (если он там был),
        # чтобы последующий get_by_id увидел новые поля. Без этого тесты ловят
        # стейл-данные после прямого UPDATE.
        cached = await self._session.get(Payment, payment_id)
        if cached is not None:
            await self._session.refresh(cached)

    async def mark_failed(self, payment_id: int, reason: str | None = None) -> None:
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status="failed", failure_reason=reason)
        )
        await self._session.execute(stmt)
        await self._session.flush()
