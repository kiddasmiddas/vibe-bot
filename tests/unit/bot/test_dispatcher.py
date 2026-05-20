from __future__ import annotations

from unittest.mock import MagicMock

from aiogram import Bot, Dispatcher

from app.bot.dispatcher import build_dispatcher


def test_build_dispatcher_registers_common_router() -> None:
    bot = MagicMock(spec=Bot)
    redis = MagicMock()

    dp = build_dispatcher(bot, redis)

    assert isinstance(dp, Dispatcher)
    router_names = {r.name for r in dp.sub_routers}
    assert "common" in router_names
