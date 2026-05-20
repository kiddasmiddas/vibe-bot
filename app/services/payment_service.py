from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.payment_repo import PaymentRepository
from app.db.repositories.premium_repo import PremiumRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from app.services.exceptions import AlreadyPremiumError, PaymentProviderUnavailableError
from app.texts import premium as texts

if TYPE_CHECKING:
    from app.db.models.user import User

# Ключи из таблицы settings
SETTING_PREMIUM_PRICE_RUB = "premium_price_rub"
SETTING_PREMIUM_DURATION_DAYS = "premium_duration_days"

# Дефолты на случай, если запись ещё не создана в настройках
DEFAULT_PRICE_RUB = 299
DEFAULT_DURATION_DAYS = 30

# Формат payload для идентификации инвойса
PAYLOAD_PREFIX = "premium"


def _parse_payload(payload: str) -> int | None:
    """Парсит payload вида ``"premium:<payment_id>"`` и возвращает payment_id или None."""
    parts = payload.split(":", 1)
    if len(parts) != 2 or parts[0] != PAYLOAD_PREFIX:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


class PaymentService:
    """Бизнес-логика платежей Premium через Telegram Payments (ЮKassa)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payment_repo = PaymentRepository(session)
        self._premium_repo = PremiumRepository(session)
        self._user_repo = UserRepository(session)
        self._analytics_repo = AnalyticsRepository(session)
        self._settings_repo = SettingsRepository(session)

    async def _get_price_and_duration(self) -> tuple[int, int]:
        """Возвращает (цена в рублях, длительность в днях) из таблицы settings."""
        price = await self._settings_repo.get_int(SETTING_PREMIUM_PRICE_RUB)
        duration = await self._settings_repo.get_int(SETTING_PREMIUM_DURATION_DAYS)
        return (
            price if price is not None else DEFAULT_PRICE_RUB,
            duration if duration is not None else DEFAULT_DURATION_DAYS,
        )

    async def create_premium_invoice(self, user: User, bot: Bot) -> None:
        """Создаёт Payment в БД и отправляет инвойс через Telegram Payments.

        Raises:
            AlreadyPremiumError: если у пользователя уже активный Premium.
            PaymentProviderUnavailableError: если YOOKASSA_PROVIDER_TOKEN не задан.
        """
        # Проверяем, не активен ли уже Premium.
        now = datetime.now(tz=UTC)
        if user.is_premium and user.premium_until is not None and user.premium_until > now:
            raise AlreadyPremiumError(until=user.premium_until)

        provider_token = settings.yookassa_provider_token
        if not provider_token:
            raise PaymentProviderUnavailableError

        price_rub, _duration_days = await self._get_price_and_duration()
        amount_kop = price_rub * 100

        # Создаём платёжную запись в БД с временным payload.
        # Окончательный invoice_payload формируем после получения id.
        payment = await self._payment_repo.create_pending(
            user_id=user.id,
            amount_kop=amount_kop,
            purpose="premium",
            invoice_payload=f"{PAYLOAD_PREFIX}:pending_creation",
        )

        # Теперь id известен — обновляем payload уникально через репозиторий.
        invoice_payload = f"{PAYLOAD_PREFIX}:{payment.id}"
        await self._payment_repo.update_invoice_payload(payment.id, invoice_payload)

        logger.info(
            "sending premium invoice user_id={} payment_id={} price_rub={} token_pfx={}",
            user.id,
            payment.id,
            price_rub,
            provider_token[:8],  # : не логировать токен целиком
        )

        await bot.send_invoice(
            chat_id=user.telegram_id,
            title=texts.INVOICE_TITLE,
            description=texts.INVOICE_DESCRIPTION,
            payload=invoice_payload,
            provider_token=provider_token,
            currency="RUB",
            prices=[LabeledPrice(label=texts.INVOICE_LABEL_PRICE, amount=amount_kop)],
        )

    async def handle_pre_checkout(self, query: PreCheckoutQuery) -> tuple[bool, str | None]:
        """Валидирует pre_checkout_query.

        Returns:
            (True, None) если всё корректно.
            (False, reason) если есть проблема — reason передаётся Telegram как error_message.
        """
        payment_id = _parse_payload(query.invoice_payload)
        if payment_id is None:
            logger.warning("pre_checkout: invalid payload format payload={}", query.invoice_payload)
            return False, "Invalid payment payload"

        payment = await self._payment_repo.get_by_id(payment_id)
        if payment is None:
            logger.warning("pre_checkout: payment not found payment_id={}", payment_id)
            return False, "Payment not found"

        if payment.status == "succeeded":
            # Защита от replay: Telegram теоретически может попытаться провести
            # уже оплаченный инвойс повторно.
            logger.warning(
                "pre_checkout: replay attempt payment_id={} already succeeded", payment_id
            )
            return False, "Payment already processed"

        if payment.status != "pending":
            logger.warning(
                "pre_checkout: payment_id={} unexpected status={}", payment_id, payment.status
            )
            return False, "Payment in unexpected state"

        # Проверяем, что платёж принадлежит запрашивающему пользователю.
        user = await self._user_repo.get_by_telegram_id(query.from_user.id)
        if user is None or payment.user_id != user.id:
            logger.warning(
                "pre_checkout: user_id mismatch payment_id={} payment_user_id={} telegram_id={}",
                payment_id,
                payment.user_id,
                query.from_user.id,
            )
            return False, "Payment does not belong to this user"

        return True, None

    async def handle_successful_payment(self, payment_msg: Message, user: User) -> datetime:
        """Обрабатывает successful_payment: обновляет Payment, создаёт PremiumSubscription,
        обновляет User.

        Идемпотентен: если payment уже succeeded — не создаёт дубликаты.

        Returns:
            expires_at: дата окончания подписки (для отображения пользователю).
        """
        successful_payment = payment_msg.successful_payment
        if successful_payment is None:
            raise ValueError("message has no successful_payment")

        payment_id = _parse_payload(successful_payment.invoice_payload)
        if payment_id is None:
            raise ValueError(f"invalid invoice_payload: {successful_payment.invoice_payload!r}")

        payment = await self._payment_repo.get_by_id(payment_id)
        if payment is None:
            raise ValueError(f"payment not found: payment_id={payment_id}")

        now = datetime.now(tz=UTC)

        # Идемпотентность: если уже обработан — ничего не делаем, возвращаем premium_until.
        if payment.status == "succeeded":
            logger.info(
                "handle_successful_payment: payment_id={} already succeeded, skipping",
                payment_id,
            )
            return user.premium_until or now

        provider_charge_id = successful_payment.provider_payment_charge_id
        telegram_charge_id = successful_payment.telegram_payment_charge_id

        # : charge_id логируем только первые 8 символов.
        logger.info(
            "handle_successful_payment: payment_id={} prov_pfx={} tg_pfx={}",
            payment_id,
            (provider_charge_id or "")[:8],
            (telegram_charge_id or "")[:8],
        )

        await self._payment_repo.mark_succeeded(
            payment_id,
            provider_charge_id=provider_charge_id,
            telegram_charge_id=telegram_charge_id,
        )

        _price_rub, duration_days = await self._get_price_and_duration()
        expires_at = now + timedelta(days=duration_days)

        await self._premium_repo.create_subscription(
            user_id=user.id,
            ends_at=expires_at,
            granted_by="purchase",
            payment_id=payment_id,
        )

        await self._user_repo.update_premium(
            user.id,
            is_premium=True,
            premium_until=expires_at,
        )
        # Синхронизируем объект пользователя (он передан по ссылке из мидлвари).
        user.is_premium = True
        user.premium_until = expires_at

        await self._analytics_repo.log_event(
            user.id,
            EventType.PREMIUM_PURCHASED,
            {"payment_id": payment_id, "expires_at": expires_at.isoformat()},
        )

        return expires_at
