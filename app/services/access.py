"""Проверки уровня доступа пользователя.

Единое место, чтобы и бот, и API одинаково отвечали на вопросы
«это администратор?» и «есть ли доступ к premium-функциям?».
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.db.models.user import User


def is_admin_user(user: User) -> bool:
    """Администратор — по telegram_id из ADMIN_TELEGRAM_IDS."""
    return user.telegram_id in settings.admin_telegram_ids


def has_premium_access(user: User) -> bool:
    """Доступ к premium-функциям.

    Активная Premium-подписка ИЛИ администратор ИЛИ модератор: у персонала
    доступ ко всем premium-функциям априори, подписку выдавать не нужно.
    """
    return user.is_premium or is_admin_user(user) or bool(user.is_moderator)
