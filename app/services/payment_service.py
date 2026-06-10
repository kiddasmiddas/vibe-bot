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

# Legacy-ключи (одна цена, единый срок) — оставлены как fallback для обратной
# совместимости. Если в settings нет тарифных ключей, читаем эти.
SETTING_PREMIUM_PRICE_RUB = "premium_price_rub"
SETTING_PREMIUM_DURATION_DAYS = "premium_duration_days"

# Ключи тарифов в таблице settings.
SETTING_PREMIUM_PRICE_RUB_WEEK = "premium_price_week_rub"
SETTING_PREMIUM_DURATION_DAYS_WEEK = "premium_duration_days_week"
SETTING_PREMIUM_PRICE_RUB_MONTH = "premium_price_month_rub"
SETTING_PREMIUM_DURATION_DAYS_MONTH = "premium_duration_days_month"
SETTING_PREMIUM_PRICE_RUB_YEAR = "premium_price_year_rub"
SETTING_PREMIUM_DURATION_DAYS_YEAR = "premium_duration_days_year"

# Дефолты на случай, если запись ещё не создана в настройках.
DEFAULT_PRICE_RUB = 200
DEFAULT_DURATION_DAYS = 30

TARIFF_WEEK = "week"
TARIFF_MONTH = "month"
TARIFF_YEAR = "year"
ALLOWED_TARIFFS: tuple[str, ...] = (TARIFF_WEEK, TARIFF_MONTH, TARIFF_YEAR)

# Дефолтные пары (price_rub, duration_days) если settings пустые.
TARIFF_DEFAULTS: dict[str, tuple[int, int]] = {
    TARIFF_WEEK: (100, 7),
    TARIFF_MONTH: (200, 30),
    TARIFF_YEAR: (1500, 365),
}

# Ключи (settings_price, settings_duration) на каждый тариф.
_TARIFF_SETTING_KEYS: dict[str, tuple[str, str]] = {
    TARIFF_WEEK: (SETTING_PREMIUM_PRICE_RUB_WEEK, SETTING_PREMIUM_DURATION_DAYS_WEEK),
    TARIFF_MONTH: (SETTING_PREMIUM_PRICE_RUB_MONTH, SETTING_PREMIUM_DURATION_DAYS_MONTH),
    TARIFF_YEAR: (SETTING_PREMIUM_PRICE_RUB_YEAR, SETTING_PREMIUM_DURATION_DAYS_YEAR),
}

# Формат payload для идентификации инвойса.
PAYLOAD_PREFIX = "premium"

# Хранение тарифа внутри Payment.purpose: 'premium:<tariff>'.
PURPOSE_PREFIX = "premium"


def _normalize_tariff(tariff: str | None) -> str:
    """Приводит входной тариф к канону. Пустая/неизвестная строка → month (legacy)."""
    if tariff in ALLOWED_TARIFFS:
        return tariff
    return TARIFF_MONTH


def _build_purpose(tariff: str) -> str:
    """Формирует значение Payment.purpose с зашитым тарифом: ``premium:<tariff>``."""
    return f"{PURPOSE_PREFIX}:{tariff}"


def _parse_tariff_from_purpose(purpose: str | None) -> str:
    """Извлекает тариф из Payment.purpose. Поддерживает legacy-значение 'premium'."""
    if not purpose:
        return TARIFF_MONTH
    parts = purpose.split(":", 1)
    if len(parts) == 2 and parts[0] == PURPOSE_PREFIX and parts[1] in ALLOWED_TARIFFS:
        return parts[1]
    return TARIFF_MONTH


def _build_payload(payment_id: int, tariff: str) -> str:
    """Формирует invoice_payload вида ``premium:<tariff>:<payment_id>``."""
    return f"{PAYLOAD_PREFIX}:{tariff}:{payment_id}"


def _parse_payload(payload: str) -> int | None:
    """Парсит payload и возвращает payment_id.

    Поддерживает оба формата:
      * новый: ``premium:<tariff>:<id>``
      * legacy: ``premium:<id>`` (для уже выставленных до релиза инвойсов).
    """
    parts = payload.split(":")
    if len(parts) < 2 or parts[0] != PAYLOAD_PREFIX:
        return None
    # Берём последнюю секцию — это id и в новом, и в legacy-формате.
    try:
        return int(parts[-1])
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

    async def _get_price_and_duration(self, tariff: str = TARIFF_MONTH) -> tuple[int, int]:
        """Возвращает (цена в рублях, длительность в днях) для тарифа.

        Порядок резолва: тарифные ключи в settings → дефолты тарифа из TARIFF_DEFAULTS.
        Для тарифа month дополнительный fallback на legacy-ключи premium_price_rub /
        premium_duration_days, если тарифных значений нет.
        """
        tariff = _normalize_tariff(tariff)
        price_key, duration_key = _TARIFF_SETTING_KEYS[tariff]

        price = await self._settings_repo.get_int(price_key)
        duration = await self._settings_repo.get_int(duration_key)

        # Legacy-fallback ТОЛЬКО для месячного тарифа (исторически premium_price_rub
        # описывал именно «месяц на 30 дней»).
        if tariff == TARIFF_MONTH:
            if price is None:
                price = await self._settings_repo.get_int(SETTING_PREMIUM_PRICE_RUB)
            if duration is None:
                duration = await self._settings_repo.get_int(SETTING_PREMIUM_DURATION_DAYS)

        default_price, default_duration = TARIFF_DEFAULTS[tariff]
        return (
            price if price is not None else default_price,
            duration if duration is not None else default_duration,
        )

    async def create_premium_invoice(
        self, user: User, bot: Bot, *, tariff: str = TARIFF_MONTH
    ) -> None:
        """Создаёт Payment в БД и отправляет инвойс через Telegram Payments.

        Args:
            user: покупатель.
            bot: aiogram-бот.
            tariff: 'week' | 'month' | 'year'. Неизвестное → 'month'.

        Raises:
            AlreadyPremiumError: если у пользователя уже активный Premium.
            PaymentProviderUnavailableError: если YOOKASSA_PROVIDER_TOKEN не задан.
        """
        tariff = _normalize_tariff(tariff)

        # Проверяем, не активен ли уже Premium.
        now = datetime.now(tz=UTC)
        if user.is_premium and user.premium_until is not None and user.premium_until > now:
            raise AlreadyPremiumError(until=user.premium_until)

        provider_token = settings.yookassa_provider_token
        if not provider_token:
            raise PaymentProviderUnavailableError

        price_rub, duration_days = await self._get_price_and_duration(tariff)
        amount_kop = price_rub * 100

        # Создаём платёжную запись в БД с временным payload.
        # Окончательный invoice_payload формируем после получения id.
        # Тариф сохраняем в purpose, чтобы не доверять payload-у пользователя.
        payment = await self._payment_repo.create_pending(
            user_id=user.id,
            amount_kop=amount_kop,
            purpose=_build_purpose(tariff),
            invoice_payload=f"{PAYLOAD_PREFIX}:pending_creation:{user.id}:{now.timestamp()}",
        )

        # Теперь id известен — обновляем payload уникально через репозиторий.
        invoice_payload = _build_payload(payment.id, tariff)
        await self._payment_repo.update_invoice_payload(payment.id, invoice_payload)

        logger.info(
            "sending premium invoice user_id={} payment_id={} tariff={} "
            "price_rub={} days={} token_pfx={}",
            user.id,
            payment.id,
            tariff,
            price_rub,
            duration_days,
            provider_token[:8],  # : не логировать токен целиком
        )

        await bot.send_invoice(
            chat_id=user.telegram_id,
            title=texts.INVOICE_TITLE,
            description=texts.INVOICE_DESCRIPTION_TEMPLATE.format(days=duration_days),
            payload=invoice_payload,
            provider_token=provider_token,
            currency="RUB",
            prices=[
                LabeledPrice(
                    label=texts.INVOICE_LABEL_PRICE_TEMPLATE.format(days=duration_days),
                    amount=amount_kop,
                )
            ],
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

        # Берём тариф из Payment.purpose (сохранён нами при create_invoice), а не
        # из payload — payload пришёл от пользователя и теоретически мог быть подделан.
        tariff = _parse_tariff_from_purpose(payment.purpose)
        _price_rub, duration_days = await self._get_price_and_duration(tariff)
        # Продлеваем от текущей даты окончания, если Premium ещё активен (в т.ч.
        # выданный вручную годовой) — иначе оплата короткого тарифа укоротила бы
        # уже оплаченный/выданный срок. Иначе считаем от now.
        base = (
            user.premium_until
            if user.premium_until is not None and user.premium_until > now
            else now
        )
        expires_at = base + timedelta(days=duration_days)

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
            {
                "payment_id": payment_id,
                "tariff": tariff,
                "expires_at": expires_at.isoformat(),
            },
        )

        return expires_at
