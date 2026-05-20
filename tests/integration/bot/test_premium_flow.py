"""Интеграционные тесты хэндлеров Premium против реальной БД.

Используют сессионный `db_session` с автооткатом (см. conftest.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.premium import on_premium_menu
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.analytics_events import EventType
from app.texts import common as common_texts
from app.texts import premium as texts


async def _make_user(db_session, *, telegram_id: int, is_premium: bool = False, premium_until=None):
    user = await UserRepository(db_session).create(telegram_id=telegram_id)
    if is_premium or premium_until is not None:
        await UserRepository(db_session).update_premium(
            user.id, is_premium=is_premium, premium_until=premium_until
        )
        await db_session.flush()
        await db_session.refresh(user)
    return user


def _make_message(text: str = common_texts.BTN_PREMIUM) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


# ---------------------------------------------------------------------------
# on_premium_menu
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_premium_menu_renders_screen_and_logs_analytics(db_session) -> None:
    """Нажатие BTN_PREMIUM → показывает экран + analytics PREMIUM_SCREEN_OPENED."""
    user = await _make_user(db_session, telegram_id=80001)
    message = _make_message()

    await on_premium_menu(message, user, db_session)

    message.answer.assert_awaited_once()
    text_sent = message.answer.call_args.args[0]
    assert texts.SCREEN_TITLE in text_sent
    assert texts.BTN_BUY in str(message.answer.call_args)

    events = await AnalyticsRepository(db_session).list_recent_for_user(user.id)
    assert any(e.event_type == EventType.PREMIUM_SCREEN_OPENED for e in events)


@pytest.mark.asyncio
async def test_on_premium_menu_active_premium_shows_already_premium(db_session) -> None:
    """Если Premium уже активен → ALREADY_PREMIUM_TEMPLATE без inline-кнопок."""
    until = datetime.now(tz=UTC) + timedelta(days=15)
    user = await _make_user(db_session, telegram_id=80002, is_premium=True, premium_until=until)
    message = _make_message()

    await on_premium_menu(message, user, db_session)

    message.answer.assert_awaited_once()
    text_sent = message.answer.call_args.args[0]
    assert "уже приобрет" in text_sent
    # До окончания 15 дней — в сообщении есть число оставшихся дней.
    assert "15" in text_sent


@pytest.mark.asyncio
async def test_on_premium_menu_expired_premium_shows_screen(db_session) -> None:
    """Если premium_until в прошлом — показывается экран покупки, не «уже активен»."""
    until = datetime.now(tz=UTC) - timedelta(days=1)
    user = await _make_user(db_session, telegram_id=80003, is_premium=False, premium_until=until)
    message = _make_message()

    await on_premium_menu(message, user, db_session)

    message.answer.assert_awaited_once()
    text_sent = message.answer.call_args.args[0]
    assert texts.SCREEN_TITLE in text_sent


# ---------------------------------------------------------------------------
# cb_premium_buy — через callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cb_premium_buy_sends_invoice(db_session) -> None:
    """Нажатие «Оплатить» → bot.send_invoice вызван."""
    from app.bot.handlers.premium import cb_premium_buy

    user = await _make_user(db_session, telegram_id=80010)

    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()

    bot = MagicMock()
    bot.send_invoice = AsyncMock()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = "381764678:TEST:abc"
        await cb_premium_buy(callback, user, db_session, bot)

    bot.send_invoice.assert_awaited_once()
    call_kwargs = bot.send_invoice.call_args.kwargs
    assert call_kwargs["currency"] == "RUB"
    assert call_kwargs["payload"].startswith("premium:")
