from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Тестовый токен — не должен совпадать с prod-токеном.
# Передаём через env-переменную TEST_BOT_TOKEN или используем хардкоданный стаб.
TEST_BOT_TOKEN = "1234567890:AATestFakeTokenForTestingOnlyVibeBot"

# URL тестовой БД берём из глобального conftest
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vibe:vibe@localhost:5432/vibe_test",
)


def build_init_data(bot_token: str, user_id: int, extra: dict[str, Any] | None = None) -> str:
    """Генерирует корректно подписанный initData-заголовок для тестов.

    Повторяет алгоритм подписи из validate_telegram_init_data в обратную сторону.
    """
    user_payload = json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"))
    # auth_date — свежий timestamp, иначе валидатор отклонит как просроченный.
    params: dict[str, str] = {"user": user_payload, "auth_date": str(int(time.time()))}
    if extra:
        params.update({k: str(v) for k, v in extra.items()})

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    sig = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    params["hash"] = sig
    return urlencode(params)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _test_engine(_prepared_test_db: None):  # type: ignore[no-untyped-def]
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def api_db_session(_test_engine) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    """Сессия для API-тестов: rollback по окончании теста."""
    async with _test_engine.connect() as connection:
        trans = await connection.begin()
        factory = async_sessionmaker(bind=connection, class_=AsyncSession, expire_on_commit=False)
        session = factory()
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def api_client(
    api_db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient с ASGI transport.

    Переопределяет:
    - `get_db_session` → тестовая сессия с rollback
    - `settings.bot_token` → TEST_BOT_TOKEN (через прямой патч атрибута)
    """
    from app.api.app import app as fastapi_app
    from app.api.db import get_db_session
    from app.config import settings

    # Патчим bot_token на тестовый, чтобы generate/validate использовали один ключ
    original_token = settings.bot_token
    settings.bot_token = TEST_BOT_TOKEN  # type: ignore[misc]

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield api_db_session

    fastapi_app.dependency_overrides[get_db_session] = _override_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        fastapi_app.dependency_overrides.clear()
        settings.bot_token = original_token  # type: ignore[misc]


@pytest.fixture(scope="session")
def bot_token() -> str:
    return TEST_BOT_TOKEN


@pytest.fixture
def make_init_data():
    """Фабрика: `make_init_data(user_id)` → подписанный initData-заголовок (TEST_BOT_TOKEN)."""

    def _factory(user_id: int, extra: dict[str, Any] | None = None) -> str:
        return build_init_data(TEST_BOT_TOKEN, user_id, extra)

    return _factory


@pytest.fixture(autouse=True)
def _stub_media_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """В тестах нет реального Telegram — getFile недоступен.

    Подменяем резолв file_id→URL на passthrough, чтобы роуты отдавали
    file_id как есть и тесты могли проверять состав фото.
    """

    async def _resolve_one(file_id: str | None) -> str | None:
        return file_id

    async def _resolve_many(file_ids: list[str]) -> list[str]:
        return list(file_ids)

    for module in ("app.api.routes.feed", "app.api.routes.creators"):
        monkeypatch.setattr(f"{module}.resolve_file_url", _resolve_one)
        monkeypatch.setattr(f"{module}.resolve_many", _resolve_many)
