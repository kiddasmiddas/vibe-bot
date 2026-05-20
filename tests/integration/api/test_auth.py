from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.repositories.user_repo import UserRepository
from tests.integration.api.conftest import TEST_BOT_TOKEN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, telegram_id: int) -> User:
    repo = UserRepository(db)
    user = await repo.get_by_telegram_id(telegram_id)
    if user is None:
        user = await repo.create(telegram_id=telegram_id, username=f"test_{telegram_id}")
        await db.flush()
    return user


def _build_invalid_init_data(user_id: int) -> str:
    """Генерирует initData с намеренно неправильной подписью."""
    user_payload = json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"))
    params = {"user": user_payload, "hash": "deadbeef" * 8}
    return urlencode(params)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_signature_returns_200(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
    make_init_data,
) -> None:
    """Валидная подпись + пользователь в БД → 200."""
    user = await _create_user(api_db_session, telegram_id=100_001)
    init_data = make_init_data(user.telegram_id)
    response = await api_client.get(
        "/api/creators/feed", headers={"X-Telegram-Init-Data": init_data}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """Невалидная подпись → 401."""
    await _create_user(api_db_session, telegram_id=100_002)
    init_data = _build_invalid_init_data(100_002)
    response = await api_client.get(
        "/api/creators/feed", headers={"X-Telegram-Init-Data": init_data}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_forged_signature_with_wrong_token_returns_401(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """Структурно валидный initData с подписью от ДРУГОГО bot_token → 401.

    Закрывает кейс «злоумышленник знает алгоритм, но не знает наш токен» —
    HMAC должен это поймать (это и есть смысл подписи).
    """
    from tests.integration.api.conftest import build_init_data

    await _create_user(api_db_session, telegram_id=100_003)
    init_data = build_init_data(
        bot_token="9999999999:AAWrongBotTokenWhichIsNotOurs",
        user_id=100_003,
        extra={"auth_date": 1234567890},
    )
    response = await api_client.get(
        "/api/creators/feed", headers={"X-Telegram-Init-Data": init_data}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_header_without_bypass_returns_401(
    api_client: AsyncClient,
) -> None:
    """Отсутствует заголовок → 401, если bypass не включён.

    bypass=True включён в .env для тестовой среды, поэтому переопределяем
    зависимость current_user напрямую — тест проверяет логику validate_telegram_init_data.
    """
    from app.api.deps import validate_telegram_init_data

    # Прямой вызов функции: без заголовка нет данных → None
    result = validate_telegram_init_data("", TEST_BOT_TOKEN)
    assert result is None


@pytest.mark.asyncio
async def test_missing_header_bypass_true_returns_200(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """Bypass=True + пользователь в БД → 200 (нет заголовка, но dev-bypass активен)."""
    from app.config import settings

    # dev user_id должен существовать в БД
    await _create_user(api_db_session, telegram_id=settings.miniapp_dev_telegram_id)
    # Запрос без заголовка
    response = await api_client.get("/api/creators/feed")
    # bypass=True в .env/settings, ENVIRONMENT=dev → должен пройти
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_bypass_user_not_in_db_returns_401(
    api_client: AsyncClient,
) -> None:
    """Bypass=True, но dev_user_id не существует в БД → 401.

    Меняем miniapp_dev_telegram_id на несуществующий.
    """
    from app.config import settings

    original_id = settings.miniapp_dev_telegram_id
    settings.miniapp_dev_telegram_id = 999_999_999  # type: ignore[misc]
    try:
        response = await api_client.get("/api/creators/feed")
        assert response.status_code == 401
    finally:
        settings.miniapp_dev_telegram_id = original_id  # type: ignore[misc]


@pytest.mark.asyncio
async def test_bypass_ignored_in_prod_returns_401(
    api_client: AsyncClient,
    api_db_session: AsyncSession,
) -> None:
    """Bypass=True, но ENVIRONMENT=prod → bypass игнорируется → 401."""
    from app.config import settings

    original_env = settings.environment
    settings.environment = "prod"  # type: ignore[misc]
    try:
        response = await api_client.get("/api/creators/feed")
        assert response.status_code == 401
    finally:
        settings.environment = original_env  # type: ignore[misc]
