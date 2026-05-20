"""Раздел «Аналитика» (10.10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin._helpers import is_admin, show_screen
from app.bot.keyboards.admin import (
    AdminAnalyticsCb,
    AdminMenuCb,
    admin_back_home_kb,
    analytics_kb,
)
from app.db.models.user import User
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.services.analytics_events import EventType
from app.texts.admin import (
    ANALYTICS_CONVERSION,
    ANALYTICS_EVENT_ROW,
    ANALYTICS_HEADER,
    ANALYTICS_NO_DATA,
    ANALYTICS_SELECT_PERIOD,
    ANALYTICS_TOP_VIOLATORS,
    ANALYTICS_VIOLATOR_ROW,
)

router = Router(name="admin.analytics")

_PERIOD_DELTAS = {
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}

_PERIOD_LABELS = {
    "day": "день",
    "week": "неделю",
    "month": "месяц",
}


@router.callback_query(AdminMenuCb.filter(F.action == "analytics"))
async def cb_analytics_menu(callback: CallbackQuery, user: User) -> None:
    if not is_admin(user):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await show_screen(
            callback.message,
            text=ANALYTICS_SELECT_PERIOD,
            reply_markup=analytics_kb(),
        )


@router.callback_query(AdminAnalyticsCb.filter())
async def cb_analytics_period(
    callback: CallbackQuery,
    callback_data: AdminAnalyticsCb,
    user: User,
    db_session: AsyncSession,
) -> None:
    if not is_admin(user):
        await callback.answer()
        return

    period = callback_data.period
    delta = _PERIOD_DELTAS.get(period, timedelta(days=1))
    until = datetime.now(tz=UTC)
    since = until - delta

    analytics_repo = AnalyticsRepository(db_session)
    counts = await analytics_repo.aggregate_by_event_type(since, until)

    admin_repo = AdminRepository(db_session)
    violators = await admin_repo.top_violators(limit=10)

    await callback.answer()
    if not callback.message:
        return

    label = _PERIOD_LABELS.get(period, period)
    lines = [ANALYTICS_HEADER.format(period=label)]

    if not counts:
        lines.append(ANALYTICS_NO_DATA)
    else:
        for event_type, count in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(ANALYTICS_EVENT_ROW.format(event_type=event_type, count=count))

    # Конверсия в Premium
    opened = counts.get(EventType.PREMIUM_SCREEN_OPENED, 0)
    purchased = counts.get(EventType.PREMIUM_PURCHASED, 0)
    if opened > 0:
        rate = purchased / opened
        lines.append(ANALYTICS_CONVERSION.format(rate=rate))

    # Топ нарушители
    if violators:
        lines.append("")
        lines.append(ANALYTICS_TOP_VIOLATORS)
        for telegram_id, cnt in violators:
            lines.append(ANALYTICS_VIOLATOR_ROW.format(telegram_id=telegram_id, count=cnt))

    await show_screen(
        callback.message,
        text="\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_back_home_kb(),
    )
