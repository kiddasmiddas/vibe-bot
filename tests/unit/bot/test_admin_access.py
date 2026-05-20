"""Юнит-тесты разграничения доступа: администратор vs модератор.

Модератор имеет доступ ко всей админ-панели (`is_admin`), но не к управлению
модераторами (`is_full_admin`). Полный администратор — и то, и другое.
"""

from __future__ import annotations

import pytest

from app.bot.handlers.admin._helpers import is_admin, is_full_admin
from app.config import settings
from app.db.models.user import User
from app.services.access import has_premium_access


@pytest.fixture
def admin_ids(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    ids = [100]
    monkeypatch.setattr(settings, "admin_telegram_ids", ids)
    return ids


def _user(telegram_id: int, *, is_moderator: bool = False, is_premium: bool = False) -> User:
    return User(telegram_id=telegram_id, is_moderator=is_moderator, is_premium=is_premium)


def test_full_admin_passes_both_checks(admin_ids: list[int]) -> None:
    u = _user(100)
    assert is_admin(u) is True
    assert is_full_admin(u) is True


def test_moderator_has_panel_access_but_not_moderator_management(admin_ids: list[int]) -> None:
    u = _user(200, is_moderator=True)
    # Доступ к админ-панели — есть.
    assert is_admin(u) is True
    # Управление модераторами — нет (это только полный администратор).
    assert is_full_admin(u) is False


def test_regular_user_has_no_admin_access(admin_ids: list[int]) -> None:
    u = _user(300)
    assert is_admin(u) is False
    assert is_full_admin(u) is False


def test_moderator_gets_premium_access(admin_ids: list[int]) -> None:
    assert has_premium_access(_user(200, is_moderator=True)) is True
    assert has_premium_access(_user(300)) is False
    assert has_premium_access(_user(300, is_premium=True)) is True
