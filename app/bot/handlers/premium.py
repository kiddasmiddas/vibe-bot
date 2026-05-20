from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.premium import PremiumActionCb, premium_screen_kb
from app.db.models.user import User
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.services.access import is_admin_user
from app.services.analytics_events import EventType
from app.services.exceptions import AlreadyPremiumError, PaymentProviderUnavailableError
from app.services.payment_service import PaymentService
from app.texts import common as common_texts
from app.texts import premium as texts

router = Router(name="premium")


def _fmt_until(dt: object) -> str:
    """Форматирует дату окончания подписки для отображения пользователю."""
    from datetime import datetime

    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y")
    return str(dt)


@router.message(Command("premium"))
@router.message(F.text == common_texts.BTN_PREMIUM)
async def on_premium_menu(message: Message, user: User, db_session: AsyncSession) -> None:
    """Экран Premium: команда /premium или кнопка «Premium» в главном меню."""
    from datetime import UTC, datetime

    analytics = AnalyticsRepository(db_session)
    await analytics.log_event(user.id, EventType.PREMIUM_SCREEN_OPENED)

    # У администратора Premium-доступ априори (без подписки и срока).
    if is_admin_user(user):
        await message.answer(texts.ADMIN_PREMIUM_NOTICE)
        return

    now = datetime.now(tz=UTC)
    if user.is_premium and user.premium_until is not None and user.premium_until > now:
        import math

        days_left = math.ceil((user.premium_until - now).total_seconds() / 86400)
        await message.answer(
            texts.ALREADY_PREMIUM_TEMPLATE.format(
                until=_fmt_until(user.premium_until),
                days_left=days_left,
            )
        )
        return

    from app.db.repositories.settings_repo import SettingsRepository
    from app.services.payment_service import DEFAULT_DURATION_DAYS, DEFAULT_PRICE_RUB

    settings_repo = SettingsRepository(db_session)
    price_rub = await settings_repo.get_int("premium_price_rub") or DEFAULT_PRICE_RUB
    duration_days = await settings_repo.get_int("premium_duration_days") or DEFAULT_DURATION_DAYS

    screen_text = (
        f"<b>{texts.SCREEN_TITLE}</b>\n\n"
        f"{texts.BENEFITS}\n\n"
        f"{texts.PRICE_TEMPLATE.format(price=price_rub, days=duration_days)}"
    )
    await message.answer(screen_text, reply_markup=premium_screen_kb(), parse_mode="HTML")


@router.callback_query(PremiumActionCb.filter(F.action == "buy"))
async def cb_premium_buy(callback, user: User, db_session: AsyncSession, bot: Bot) -> None:
    """Нажатие кнопки «Оплатить» — отправка инвойса."""
    await callback.answer()

    service = PaymentService(db_session)
    try:
        await service.create_premium_invoice(user, bot)
    except AlreadyPremiumError as exc:
        import math
        from datetime import UTC, datetime

        days_left = max(0, math.ceil((exc.until - datetime.now(tz=UTC)).total_seconds() / 86400))
        await callback.message.answer(
            texts.ALREADY_PREMIUM_TEMPLATE.format(
                until=_fmt_until(exc.until),
                days_left=days_left,
            )
        )
    except PaymentProviderUnavailableError:
        logger.warning("premium invoice: provider token not configured user_id={}", user.id)
        await callback.message.answer(texts.PROVIDER_TOKEN_MISSING)


@router.pre_checkout_query()
async def on_pre_checkout_query(query: PreCheckoutQuery, db_session: AsyncSession) -> None:
    """Валидация pre_checkout_query перед проведением платежа.

    Telegram требует ответа в течение 10 секунд. Не отвечаем ok=True слепо —
    проверяем payload, статус платежа и соответствие пользователя. ()
    """
    service = PaymentService(db_session)
    ok, error_message = await service.handle_pre_checkout(query)
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message=error_message)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, user: User, db_session: AsyncSession) -> None:
    """Обработка успешного платежа. Telegram присылает это сообщение после оплаты."""
    service = PaymentService(db_session)
    try:
        expires_at = await service.handle_successful_payment(message, user)
        await message.answer(texts.PAYMENT_SUCCESS_TEMPLATE.format(until=_fmt_until(expires_at)))
    except Exception as exc:
        logger.error(
            "handle_successful_payment failed user_id={} err={}",
            user.id,
            exc,
        )
        # Откатываем частичные изменения упавшего платёжного флоу, затем в чистой
        # транзакции пишем аналитику отказа — иначе middleware закоммитит «мусор».
        try:
            await db_session.rollback()
        except Exception as rollback_exc:
            logger.error("db_session.rollback failed user_id={} err={}", user.id, rollback_exc)
        try:
            await AnalyticsRepository(db_session).log_event(
                user.id, EventType.PREMIUM_PURCHASE_FAILED
            )
        except Exception as analytics_exc:
            logger.error("analytics log_event failed user_id={} err={}", user.id, analytics_exc)
        await message.answer(texts.PAYMENT_FAILED)
