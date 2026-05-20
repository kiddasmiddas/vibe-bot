"""Юнит-тесты меню команд бота (`app/bot/commands.py`)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault

from app.bot.commands import _admin_commands, _public_commands, setup_bot_commands
from app.config import settings


def test_public_commands_are_start_premium_delete() -> None:
    names = [c.command for c in _public_commands()]
    assert names == ["start", "premium", "delete"]
    assert "admin" not in names


def test_admin_commands_include_admin() -> None:
    names = [c.command for c in _admin_commands()]
    assert set(names) == {"start", "premium", "delete", "admin"}


def test_command_definitions_are_valid() -> None:
    """Имена и описания укладываются в лимиты Telegram."""
    for cmd in _admin_commands():
        assert re.fullmatch(r"[a-z0-9_]{1,32}", cmd.command)
        assert 1 <= len(cmd.description) <= 256


@pytest.mark.asyncio
async def test_setup_sets_default_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_telegram_ids", [])
    bot = AsyncMock()

    await setup_bot_commands(bot)

    # Без админов — единственный вызов: публичные команды в дефолтном скоупе.
    assert bot.set_my_commands.await_count == 1
    call = bot.set_my_commands.await_args_list[0]
    assert isinstance(call.kwargs["scope"], BotCommandScopeDefault)
    assert [c.command for c in call.args[0]] == ["start", "premium", "delete"]


@pytest.mark.asyncio
async def test_setup_sets_chat_scope_per_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_telegram_ids", [111, 222])
    bot = AsyncMock()

    await setup_bot_commands(bot)

    # 1 дефолтный вызов + по одному персональному на каждого админа.
    assert bot.set_my_commands.await_count == 3
    admin_calls = bot.set_my_commands.await_args_list[1:]
    chat_ids = {c.kwargs["scope"].chat_id for c in admin_calls}
    assert chat_ids == {111, 222}
    for call in admin_calls:
        assert isinstance(call.kwargs["scope"], BotCommandScopeChat)
        assert "admin" in [c.command for c in call.args[0]]


@pytest.mark.asyncio
async def test_setup_swallows_telegram_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сетевая ошибка set_my_commands не должна ронять старт бота."""
    monkeypatch.setattr(settings, "admin_telegram_ids", [])
    bot = AsyncMock()
    bot.set_my_commands.side_effect = TelegramAPIError(method=None, message="boom")

    # Не пробрасывает исключение — старт продолжается.
    await setup_bot_commands(bot)
