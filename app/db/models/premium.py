from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampMixin

# Допустимые значения для PremiumSubscription.granted_by.
PREMIUM_GRANTED_BY: tuple[str, ...] = ("purchase", "manual")

# Допустимые значения для Payment.status.
PAYMENT_STATUSES: tuple[str, ...] = ("pending", "succeeded", "failed")


class PremiumSubscription(Base):
    """Период действия Premium у пользователя.

    Может быть создан как результат покупки (`granted_by='purchase'`, с FK на payments),
    так и выдан вручную админом (`granted_by='manual'`, с FK на админа).
    """

    __tablename__ = "premium_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "granted_by IN ('purchase', 'manual')",
            name="granted_by_allowed",
        ),
        CheckConstraint("ends_at > started_at", name="ends_after_start"),
        Index("ix_premium_subscriptions_user_id_ends_at", "user_id", "ends_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Forward-reference на payments.id. Циклической зависимости нет — в Payment нет FK
    # на premium_subscriptions, поэтому строковая ссылка по __tablename__ корректна.
    payment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_by: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class Payment(Base, TimestampMixin):
    """Финансовая запись о платеже через Telegram Payments (провайдер по умолчанию — ЮKassa).

    Сумма хранится в копейках, как в Telegram Payments. `invoice_payload` уникален — это
    тот же payload, что мы передаём в инвойс; используется в `pre_checkout_query` и
    `successful_payment` для антидубликата.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("amount_kop > 0", name="amount_positive"),
        Index("ix_payments_user_id_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # RESTRICT: платёж — финансовая запись, не каскадить вслед за удалением пользователя.
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_kop: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="yookassa")
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invoice_payload: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Причина отказа (если status='failed') — например, сообщение провайдера или
    # внутренняя метка. Хранится отдельно от invoice_payload.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
