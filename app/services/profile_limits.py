"""Лимиты анкеты, редактируемые админом (/admin → ⚙️ Настройки → 📏 Лимиты).

Значения живут в app_settings; кривое/нулевое значение трактуется как
«нет значения» → дефолт кода. Используются и в регистрации, и в
редактировании профиля.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.settings_repo import (
    DEFAULT_BIO_MAX_LENGTH,
    DEFAULT_FANDOMS_MAX_SELECTED,
    SETTING_BIO_MAX_LENGTH,
    SETTING_FANDOMS_MAX_SELECTED,
    SettingsRepository,
)


async def fandoms_max_selected(db_session: AsyncSession) -> int:
    """Максимум выбранных фандомов (и «свои», и «ищу»)."""
    value = await SettingsRepository(db_session).get_int(SETTING_FANDOMS_MAX_SELECTED)
    return value if value is not None and value > 0 else DEFAULT_FANDOMS_MAX_SELECTED


async def bio_max_length(db_session: AsyncSession) -> int:
    """Максимальная длина «О себе»."""
    value = await SettingsRepository(db_session).get_int(SETTING_BIO_MAX_LENGTH)
    return value if value is not None and value > 0 else DEFAULT_BIO_MAX_LENGTH
