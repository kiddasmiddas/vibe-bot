"""Интеграционные тесты PaymentService против реальной БД.

Используют сессионный `db_session` с автооткатом (см. conftest.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.premium import Payment
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.payment_repo import PaymentRepository
from app.db.repositories.premium_repo import PremiumRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from app.services.exceptions import AlreadyPremiumError, PaymentProviderUnavailableError
from app.services.payment_service import PaymentService

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


async def _make_user(db_session, *, telegram_id: int, is_premium: bool = False, premium_until=None):
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    if is_premium or premium_until is not None:
        await UserRepository(db_session).update_premium(
            user.id, is_premium=is_premium, premium_until=premium_until
        )
        await db_session.flush()
        await db_session.refresh(user)
    return user


def _mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_invoice = AsyncMock()
    return bot


def _mock_pre_checkout(telegram_id: int, payload: str) -> MagicMock:
    query = MagicMock()
    query.invoice_payload = payload
    query.from_user = MagicMock()
    query.from_user.id = telegram_id
    return query


def _mock_successful_payment_message(payload: str, user_telegram_id: int = 0) -> MagicMock:
    sp = MagicMock()
    sp.invoice_payload = payload
    sp.provider_payment_charge_id = "prov_charge_abc123"
    sp.telegram_payment_charge_id = "tg_charge_xyz456"

    msg = MagicMock()
    msg.successful_payment = sp
    msg.from_user = MagicMock()
    msg.from_user.id = user_telegram_id
    return msg


# ---------------------------------------------------------------------------
# create_premium_invoice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_premium_invoice_creates_payment_and_calls_send_invoice(
    db_session,
) -> None:
    """create_premium_invoice → Payment в БД со status='pending', bot.send_invoice вызван."""
    user = await _make_user(db_session, telegram_id=70001)
    bot = _mock_bot()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = "381764678:TEST:abc"
        service = PaymentService(db_session)
        await service.create_premium_invoice(user, bot)

    bot.send_invoice.assert_awaited_once()
    call_kwargs = bot.send_invoice.call_args.kwargs

    # Проверяем ключевые параметры инвойса.
    assert call_kwargs["chat_id"] == user.telegram_id
    assert call_kwargs["currency"] == "RUB"
    payload = call_kwargs["payload"]
    assert payload.startswith("premium:")
    # Новый формат: premium:<tariff>:<id>. payment_id всегда в последней секции.
    payment_id = int(payload.split(":")[-1])

    # Платёж должен быть в БД.
    payment = await PaymentRepository(db_session).get_by_id(payment_id)
    assert payment is not None
    assert payment.status == "pending"
    # Тариф вшит в purpose ('premium:<tariff>'); по умолчанию — месяц.
    assert payment.purpose.startswith("premium:")
    assert payment.user_id == user.id
    assert payment.invoice_payload == payload


@pytest.mark.asyncio
async def test_create_premium_invoice_active_premium_raises(db_session) -> None:
    """Если у юзера уже активный Premium — AlreadyPremiumError, никакого Payment в БД."""
    until = datetime.now(tz=UTC) + timedelta(days=10)
    user = await _make_user(db_session, telegram_id=70002, is_premium=True, premium_until=until)
    bot = _mock_bot()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = "381764678:TEST:abc"
        service = PaymentService(db_session)
        with pytest.raises(AlreadyPremiumError) as exc_info:
            await service.create_premium_invoice(user, bot)

    assert exc_info.value.until == until
    bot.send_invoice.assert_not_awaited()

    # В БД нет pending-платежа для этого юзера.
    from sqlalchemy import select

    stmt = select(Payment).where(Payment.user_id == user.id, Payment.status == "pending")
    result = (await db_session.execute(stmt)).scalar_one_or_none()
    assert result is None


@pytest.mark.asyncio
async def test_create_premium_invoice_no_provider_token_raises(db_session) -> None:
    """Если YOOKASSA_PROVIDER_TOKEN пустой — PaymentProviderUnavailableError."""
    user = await _make_user(db_session, telegram_id=70003)
    bot = _mock_bot()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = ""
        service = PaymentService(db_session)
        with pytest.raises(PaymentProviderUnavailableError):
            await service.create_premium_invoice(user, bot)

    bot.send_invoice.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_pre_checkout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_pre_checkout_valid_returns_true(db_session) -> None:
    """Валидный payload и pending-платёж → (True, None)."""
    user = await _make_user(db_session, telegram_id=70010)
    payment = await PaymentRepository(db_session).create_pending(
        user_id=user.id,
        amount_kop=29900,
        purpose="premium",
        invoice_payload="premium:99999",
    )
    # Обновляем payload на правильный.
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{payment.id}")
    )
    await db_session.flush()

    query = _mock_pre_checkout(user.telegram_id, f"premium:{payment.id}")
    service = PaymentService(db_session)
    ok, reason = await service.handle_pre_checkout(query)

    assert ok is True
    assert reason is None


@pytest.mark.asyncio
async def test_handle_pre_checkout_payment_not_found_returns_false(db_session) -> None:
    """Несуществующий payment_id → (False, ...)."""
    user = await _make_user(db_session, telegram_id=70011)
    query = _mock_pre_checkout(user.telegram_id, "premium:999999999")

    service = PaymentService(db_session)
    ok, reason = await service.handle_pre_checkout(query)

    assert ok is False
    assert reason is not None


@pytest.mark.asyncio
async def test_handle_pre_checkout_wrong_user_returns_false(db_session) -> None:
    """Платёж принадлежит другому пользователю → (False, ...)."""
    owner = await _make_user(db_session, telegram_id=70020)
    attacker = await _make_user(db_session, telegram_id=70021)

    payment = await PaymentRepository(db_session).create_pending(
        user_id=owner.id,
        amount_kop=29900,
        purpose="premium",
        invoice_payload="premium:pchk_mismatch",
    )
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{payment.id}")
    )
    await db_session.flush()

    query = _mock_pre_checkout(attacker.telegram_id, f"premium:{payment.id}")
    service = PaymentService(db_session)
    ok, reason = await service.handle_pre_checkout(query)

    assert ok is False
    assert reason is not None


@pytest.mark.asyncio
async def test_handle_pre_checkout_already_succeeded_returns_false(db_session) -> None:
    """Payment уже succeeded → (False, ...) — защита от replay."""
    user = await _make_user(db_session, telegram_id=70030)
    payment_repo = PaymentRepository(db_session)
    payment = await payment_repo.create_pending(
        user_id=user.id,
        amount_kop=29900,
        purpose="premium",
        invoice_payload="premium:succeeded_test",
    )
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{payment.id}")
    )
    await payment_repo.mark_succeeded(
        payment.id,
        provider_charge_id="prov_test",
        telegram_charge_id="tg_test",
    )

    query = _mock_pre_checkout(user.telegram_id, f"premium:{payment.id}")
    service = PaymentService(db_session)
    ok, reason = await service.handle_pre_checkout(query)

    assert ok is False
    assert reason is not None


# ---------------------------------------------------------------------------
# handle_successful_payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_successful_payment_updates_user_and_creates_subscription(
    db_session,
) -> None:
    """handle_successful_payment: payment → succeeded, subscription создана, user обновлён."""
    user = await _make_user(db_session, telegram_id=70040)
    payment_repo = PaymentRepository(db_session)
    payment = await payment_repo.create_pending(
        user_id=user.id,
        amount_kop=29900,
        purpose="premium",
        invoice_payload="premium:succ_test",
    )
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{payment.id}")
    )
    await db_session.flush()

    msg = _mock_successful_payment_message(f"premium:{payment.id}", user.telegram_id)

    service = PaymentService(db_session)
    expires_at = await service.handle_successful_payment(msg, user)

    # Payment обновился.
    updated_payment = await payment_repo.get_by_id(payment.id)
    assert updated_payment is not None
    assert updated_payment.status == "succeeded"
    assert updated_payment.provider_payment_charge_id == "prov_charge_abc123"

    # Подписка создана.
    sub = await PremiumRepository(db_session).get_active_subscription(user.id)
    assert sub is not None
    assert sub.payment_id == payment.id

    # User обновлён.
    assert user.is_premium is True
    assert user.premium_until is not None

    # Возвращённое значение соответствует.
    assert expires_at == user.premium_until

    # Аналитика записана.
    events = await AnalyticsRepository(db_session).list_recent_for_user(user.id)
    event_types = [e.event_type for e in events]
    assert EventType.PREMIUM_PURCHASED in event_types


@pytest.mark.asyncio
async def test_handle_successful_payment_idempotent_on_duplicate(db_session) -> None:
    """Повторный вызов с уже succeeded payment → ничего не делаем, не падаем."""
    user = await _make_user(db_session, telegram_id=70050)
    payment_repo = PaymentRepository(db_session)
    payment = await payment_repo.create_pending(
        user_id=user.id,
        amount_kop=29900,
        purpose="premium",
        invoice_payload="premium:idem_test",
    )
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{payment.id}")
    )
    await db_session.flush()

    msg = _mock_successful_payment_message(f"premium:{payment.id}", user.telegram_id)

    service = PaymentService(db_session)
    # Первый вызов.
    await service.handle_successful_payment(msg, user)

    # Второй вызов — дубль.
    service2 = PaymentService(db_session)
    result = await service2.handle_successful_payment(msg, user)

    # Не упал, вернул premium_until.
    assert result == user.premium_until

    # Подписок не дублируется (одна).
    from sqlalchemy import select

    from app.db.models.premium import PremiumSubscription

    subs_count = (
        (
            await db_session.execute(
                select(PremiumSubscription).where(PremiumSubscription.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(subs_count) == 1


# ---------------------------------------------------------------------------
# Тарифы: week / month / year
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tariff", "expected_price_rub", "expected_days"),
    [
        ("week", 100, 7),
        ("month", 200, 30),
        ("year", 1500, 365),
    ],
)
async def test_create_premium_invoice_per_tariff_uses_correct_price_and_payload(
    db_session, tariff: str, expected_price_rub: int, expected_days: int
) -> None:
    """Для каждого тарифа выставляется корректная цена и payload содержит тариф."""
    user = await _make_user(db_session, telegram_id=70100 + hash(tariff) % 100)
    bot = _mock_bot()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = "381764678:TEST:abc"
        service = PaymentService(db_session)
        await service.create_premium_invoice(user, bot, tariff=tariff)

    bot.send_invoice.assert_awaited_once()
    call_kwargs = bot.send_invoice.call_args.kwargs

    # Сумма в копейках = цена * 100 (одна позиция в prices).
    assert call_kwargs["prices"][0].amount == expected_price_rub * 100

    # Срок зашит в описание и в label инвойса (UX-проверка).
    assert str(expected_days) in call_kwargs["description"]
    assert str(expected_days) in call_kwargs["prices"][0].label

    # Тариф вшит в payload в формате premium:<tariff>:<id>.
    payload = call_kwargs["payload"]
    parts = payload.split(":")
    assert parts[0] == "premium"
    assert parts[1] == tariff
    payment_id = int(parts[-1])

    # Payment в БД c корректным purpose ('premium:<tariff>') и суммой.
    payment = await PaymentRepository(db_session).get_by_id(payment_id)
    assert payment is not None
    assert payment.status == "pending"
    assert payment.purpose == f"premium:{tariff}"
    assert payment.amount_kop == expected_price_rub * 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tariff", "expected_days"),
    [
        ("week", 7),
        ("month", 30),
        ("year", 365),
    ],
)
async def test_handle_successful_payment_per_tariff_sets_correct_premium_until(
    db_session, tariff: str, expected_days: int
) -> None:
    """handle_successful_payment вычисляет premium_until = now + duration_days(tariff).

    Тариф читается из Payment.purpose (а не из payload) — это защита от подмены.
    """
    user = await _make_user(db_session, telegram_id=70200 + hash(tariff) % 100)
    payment_repo = PaymentRepository(db_session)

    # Создаём pending платёж напрямую с purpose='premium:<tariff>'.
    payment = await payment_repo.create_pending(
        user_id=user.id,
        amount_kop=12345,  # любая ненулевая сумма
        purpose=f"premium:{tariff}",
        invoice_payload=f"premium:{tariff}:placeholder_{tariff}",
    )
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{tariff}:{payment.id}")
    )
    await db_session.flush()

    msg = _mock_successful_payment_message(f"premium:{tariff}:{payment.id}", user.telegram_id)

    before = datetime.now(tz=UTC)
    service = PaymentService(db_session)
    expires_at = await service.handle_successful_payment(msg, user)
    after = datetime.now(tz=UTC)

    # premium_until ≈ now + expected_days (с допуском на время выполнения теста).
    delta = expires_at - before
    delta_max = after + timedelta(days=expected_days) - before
    assert timedelta(days=expected_days) - timedelta(seconds=5) <= delta <= delta_max

    assert user.is_premium is True
    assert user.premium_until == expires_at


@pytest.mark.asyncio
async def test_create_premium_invoice_unknown_tariff_falls_back_to_month(db_session) -> None:
    """Неизвестный тариф нормализуется в 'month' — никаких падений."""
    user = await _make_user(db_session, telegram_id=70300)
    bot = _mock_bot()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = "381764678:TEST:abc"
        service = PaymentService(db_session)
        # "lifetime" не входит в ALLOWED_TARIFFS — должно нормализоваться в month.
        await service.create_premium_invoice(user, bot, tariff="lifetime")

    call_kwargs = bot.send_invoice.call_args.kwargs
    # Цена месяца — 200 ₽ = 20000 копеек.
    assert call_kwargs["prices"][0].amount == 200 * 100
    payload = call_kwargs["payload"]
    assert payload.startswith("premium:month:")


@pytest.mark.asyncio
async def test_handle_successful_payment_legacy_payload_treated_as_month(db_session) -> None:
    """Старый формат payload 'premium:<id>' (без тарифа) должен обрабатываться как month."""
    user = await _make_user(db_session, telegram_id=70400)
    payment_repo = PaymentRepository(db_session)

    # Создаём pending в legacy-стиле: purpose='premium' (без тарифа).
    payment = await payment_repo.create_pending(
        user_id=user.id,
        amount_kop=20000,
        purpose="premium",
        invoice_payload="premium:legacy_placeholder",
    )
    from sqlalchemy import update

    from app.db.models.premium import Payment as PaymentModel

    await db_session.execute(
        update(PaymentModel)
        .where(PaymentModel.id == payment.id)
        .values(invoice_payload=f"premium:{payment.id}")
    )
    await db_session.flush()

    msg = _mock_successful_payment_message(f"premium:{payment.id}", user.telegram_id)

    before = datetime.now(tz=UTC)
    service = PaymentService(db_session)
    expires_at = await service.handle_successful_payment(msg, user)

    # Legacy → month → 30 дней.
    delta = expires_at - before
    assert timedelta(days=30) - timedelta(seconds=5) <= delta <= timedelta(days=30, seconds=5)
