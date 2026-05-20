"""Тесты доступа к /admin: не-админ, админ (10.1, 10.2)."""

from __future__ import annotations

import pytest

from app.bot.handlers.admin._helpers import is_admin
from app.db.models.user import User


def _make_user(telegram_id: int) -> User:
    u = User(telegram_id=telegram_id, username=None, is_banned=False, is_premium=False)
    u.id = telegram_id
    return u


@pytest.mark.asyncio
async def test_is_admin_true(monkeypatch) -> None:
    """Пользователь из ADMIN_TELEGRAM_IDS является админом."""

    # Патчим settings
    from unittest.mock import MagicMock

    import app.bot.handlers.admin._helpers as helpers_module

    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111, 222]
    monkeypatch.setattr(helpers_module, "app_settings", fake_settings)

    user = _make_user(111)
    assert is_admin(user) is True


@pytest.mark.asyncio
async def test_is_admin_false(monkeypatch) -> None:
    """Пользователь НЕ из ADMIN_TELEGRAM_IDS не является админом."""
    from unittest.mock import MagicMock

    import app.bot.handlers.admin._helpers as helpers_module

    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = [111, 222]
    monkeypatch.setattr(helpers_module, "app_settings", fake_settings)

    user = _make_user(999)
    assert is_admin(user) is False


@pytest.mark.asyncio
async def test_is_admin_empty_list(monkeypatch) -> None:
    """Если список admin_telegram_ids пуст — никто не является админом."""
    from unittest.mock import MagicMock

    import app.bot.handlers.admin._helpers as helpers_module

    fake_settings = MagicMock()
    fake_settings.admin_telegram_ids = []
    monkeypatch.setattr(helpers_module, "app_settings", fake_settings)

    user = _make_user(42)
    assert is_admin(user) is False
