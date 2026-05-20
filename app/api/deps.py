from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl, unquote

from fastapi import Depends, Header, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.db import get_db_session
from app.config import settings
from app.db.models.profile import Profile
from app.db.models.user import User
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.user_repo import UserRepository
from app.services.access import has_premium_access

# Максимальный возраст initData. Telegram рекомендует отклонять старые подписи,
# чтобы перехваченный/утёкший initData нельзя было реплеить вечно.
_INIT_DATA_MAX_AGE_SECONDS = 86400


def validate_telegram_init_data(init_data: str, bot_token: str) -> dict[str, Any] | None:
    """Валидация подписи initData по схеме Telegram Mini App.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Возвращает распарсенные данные (включая `user` как dict) или None при невалидной подписи.
    """
    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = params.pop("hash", None)
    if not received_hash:
        return None
    # Telegram-клиент шлёт hex в lowercase, но нормализуем на всякий случай.
    received_hash = received_hash.strip().lower()

    # data_check_string: отсортированные пары key=value через \n
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    calc_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    # Защита от replay: отклоняем подпись старше суток. auth_date — Unix-время
    # генерации initData Telegram-клиентом.
    auth_date_raw = params.get("auth_date")
    if auth_date_raw is None:
        return None
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        return None
    if time.time() - auth_date > _INIT_DATA_MAX_AGE_SECONDS:
        logger.warning("init_data rejected: auth_date too old ({})", auth_date)
        return None

    # Разворачиваем вложенные JSON-поля (user — JSON-строка)
    parsed: dict[str, Any] = dict(params)
    if "user" in parsed:
        try:
            parsed["user"] = json.loads(unquote(parsed["user"]))
        except (ValueError, KeyError):
            pass

    return parsed


def _make_dev_user_data(user_id: int) -> dict[str, Any]:
    return {"user": {"id": user_id, "first_name": "DevUser"}}


async def current_user(
    x_telegram_init_data: str | None = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """FastAPI Depends: извлекает и возвращает аутентифицированного пользователя.

    Dev-bypass: если `settings.miniapp_dev_bypass_auth=True` и среда не prod —
    при отсутствующем/невалидном заголовке используется `settings.miniapp_dev_telegram_id`.
    """
    telegram_id: int | None = None

    if x_telegram_init_data:
        data = validate_telegram_init_data(x_telegram_init_data, settings.bot_token)
        if data and isinstance(data.get("user"), dict):
            telegram_id = data["user"].get("id")

    # Dev-bypass: только при bypass=True И не в prod
    if telegram_id is None:
        bypass_allowed = settings.miniapp_dev_bypass_auth and settings.environment != "prod"
        if bypass_allowed:
            logger.debug(
                "miniapp dev bypass active, using user_id={}", settings.miniapp_dev_telegram_id
            )
            telegram_id = settings.miniapp_dev_telegram_id
        else:
            raise HTTPException(status_code=401, detail="Unauthorized")

    repo = UserRepository(db)
    user = await repo.get_by_telegram_id(telegram_id)
    if user is None or user.is_banned:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return user


async def current_user_with_profile(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> tuple[User, Profile]:
    """FastAPI Depends: аутентифицированный пользователь с завершённой анкетой.

    403 если анкета не существует или `is_completed=False`.
    """
    profile_repo = ProfileRepository(db)
    profile = await profile_repo.get_by_user_id(user.id)
    if profile is None or not profile.is_completed:
        raise HTTPException(status_code=403, detail="Profile not completed")
    return user, profile


async def current_premium_user_with_profile(
    pair: tuple[User, Profile] = Depends(current_user_with_profile),
) -> tuple[User, Profile]:
    """FastAPI Depends: Premium-пользователь с завершённой анкетой.

    403 если пользователь не Premium.
    """
    user, profile = pair
    if not has_premium_access(user):
        raise HTTPException(status_code=403, detail="Premium required")
    return user, profile
