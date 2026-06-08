"""Интеграционные тесты выбора тарифа Premium на уровне хэндлера.

Каждый из трёх тарифов (week / month / year) должен создавать Payment с правильной
суммой и payload, содержащим тариф.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers.premium import cb_premium_buy, on_premium_menu
from app.bot.keyboards.premium import PremiumActionCb
from app.db.repositories.payment_repo import PaymentRepository
from app.db.repositories.user_repo import UserRepository
from app.texts import common as common_texts
from app.texts import premium as texts


async def _make_user(db_session, *, telegram_id: int):
    return await UserRepository(db_session).create(telegram_id=telegram_id)


def _make_message(text: str = common_texts.BTN_PREMIUM) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


def _make_callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    return callback


# ---------------------------------------------------------------------------
# Экран /premium теперь рисует три тарифные кнопки + новое описание.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_premium_screen_shows_three_tariff_buttons_and_new_benefits(db_session) -> None:
    user = await _make_user(db_session, telegram_id=90001)
    message = _make_message()

    await on_premium_menu(message, user, db_session)

    message.answer.assert_awaited_once()
    text_sent = message.answer.call_args.args[0]
    # Новый текст преимуществ — фрагменты из ТЗ.
    assert "Безлимит лайков" in text_sent
    assert "Вайб по фото" in text_sent
    assert "предыдущей анкете" in text_sent

    # Все три кнопки тарифов отрисованы в reply_markup.
    repr_call = str(message.answer.call_args)
    assert texts.BTN_TARIFF_WEEK in repr_call
    assert texts.BTN_TARIFF_MONTH in repr_call
    assert texts.BTN_TARIFF_YEAR in repr_call


# ---------------------------------------------------------------------------
# Каждый тариф → корректный инвойс.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tariff", "expected_amount_kop", "expected_days"),
    [
        ("week", 100 * 100, 7),
        ("month", 200 * 100, 30),
        ("year", 1500 * 100, 365),
    ],
)
async def test_cb_premium_buy_per_tariff_creates_invoice(
    db_session, tariff: str, expected_amount_kop: int, expected_days: int
) -> None:
    user = await _make_user(db_session, telegram_id=90100 + hash(tariff) % 100)

    callback = _make_callback()
    cb_data = PremiumActionCb(action="buy", tariff=tariff)
    bot = MagicMock()
    bot.send_invoice = AsyncMock()

    with patch("app.services.payment_service.settings") as mock_settings:
        mock_settings.yookassa_provider_token = "381764678:TEST:abc"
        await cb_premium_buy(callback, cb_data, user, db_session, bot)

    bot.send_invoice.assert_awaited_once()
    kw = bot.send_invoice.call_args.kwargs
    assert kw["currency"] == "RUB"
    assert kw["prices"][0].amount == expected_amount_kop

    # Срок отражён в описании инвойса.
    assert str(expected_days) in kw["description"]

    # Payload: premium:<tariff>:<payment_id>.
    payload = kw["payload"]
    parts = payload.split(":")
    assert parts[0] == "premium"
    assert parts[1] == tariff
    payment_id = int(parts[-1])

    payment = await PaymentRepository(db_session).get_by_id(payment_id)
    assert payment is not None
    assert payment.amount_kop == expected_amount_kop
    assert payment.purpose == f"premium:{tariff}"
    assert payment.status == "pending"
