from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.repositories.payment_repo import PaymentRepository
from app.db.repositories.user_repo import UserRepository


async def _make_user(db_session, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


@pytest.mark.asyncio
async def test_create_pending_sets_status(db_session) -> None:
    user = await _make_user(db_session, 5001)
    repo = PaymentRepository(db_session)

    payment = await repo.create_pending(
        user_id=user.id,
        amount_kop=19900,
        purpose="premium",
        invoice_payload="premium:5001:abc",
    )
    assert payment.id is not None
    assert payment.status == "pending"
    assert payment.currency == "RUB"
    assert payment.provider == "yookassa"
    assert payment.amount_kop == 19900


@pytest.mark.asyncio
async def test_mark_succeeded_fills_charge_ids(db_session) -> None:
    user = await _make_user(db_session, 5002)
    repo = PaymentRepository(db_session)
    payment = await repo.create_pending(
        user_id=user.id,
        amount_kop=30000,
        purpose="creator_post_1m",
        invoice_payload="creator:5002:abc",
    )

    await repo.mark_succeeded(
        payment.id,
        provider_charge_id="prov-XYZ",
        telegram_charge_id="tg-XYZ",
    )
    await db_session.refresh(payment)

    assert payment.status == "succeeded"
    assert payment.provider_payment_charge_id == "prov-XYZ"
    assert payment.telegram_payment_charge_id == "tg-XYZ"


@pytest.mark.asyncio
async def test_mark_failed_sets_failed_status_and_reason(db_session) -> None:
    user = await _make_user(db_session, 5003)
    repo = PaymentRepository(db_session)
    payment = await repo.create_pending(
        user_id=user.id,
        amount_kop=30000,
        purpose="creator_post_1m",
        invoice_payload="creator:5003:fail",
    )

    await repo.mark_failed(payment.id, reason="user_cancelled")
    await db_session.refresh(payment)

    assert payment.status == "failed"
    assert payment.failure_reason == "user_cancelled"


@pytest.mark.asyncio
async def test_get_by_invoice_payload_finds_payment(db_session) -> None:
    user = await _make_user(db_session, 5004)
    repo = PaymentRepository(db_session)
    payment = await repo.create_pending(
        user_id=user.id,
        amount_kop=19900,
        purpose="premium",
        invoice_payload="premium:5004:lookup",
    )

    found = await repo.get_by_invoice_payload("premium:5004:lookup")
    assert found is not None
    assert found.id == payment.id

    not_found = await repo.get_by_invoice_payload("does-not-exist")
    assert not_found is None


@pytest.mark.asyncio
async def test_amount_kop_must_be_positive(db_session) -> None:
    user = await _make_user(db_session, 5005)
    repo = PaymentRepository(db_session)

    with pytest.raises(IntegrityError):
        await repo.create_pending(
            user_id=user.id,
            amount_kop=0,
            purpose="premium",
            invoice_payload="premium:5005:bad",
        )
