from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parent.parent

# Тестовая БД отдельно от dev-БД, чтобы не загаживать локальную разработку.
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "vibe_test")
ADMIN_DSN = os.environ.get("TEST_ADMIN_DSN", "postgresql://vibe:vibe@localhost:5432/postgres")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql+asyncpg://vibe:vibe@localhost:5432/{TEST_DB_NAME}",
)


async def _ensure_test_database() -> None:
    """Создаёт тестовую БД, если её ещё нет."""
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME)
        if not exists:
            # Имя базы безопасно — не пользовательский ввод.
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


def _run_alembic(command: str) -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        ["uv", "run", "alembic", "upgrade" if command == "upgrade" else command, "heads"]
        if command == "upgrade"
        else ["uv", "run", "alembic", command, "base"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _prepared_test_db() -> AsyncIterator[None]:
    await _ensure_test_database()
    _run_alembic("downgrade")
    _run_alembic("upgrade")
    yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(_prepared_test_db):  # type: ignore[no-untyped-def]
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    """Сессия с авто-rollback по окончании теста: внешняя транзакция + SAVEPOINT.

    Так seed-данные миграций сохраняются между тестами, а изменения теста — нет.
    """
    async with db_engine.connect() as connection:
        trans = await connection.begin()
        sessionmaker = async_sessionmaker(
            bind=connection, class_=AsyncSession, expire_on_commit=False
        )
        session = sessionmaker()
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
def fake_redis():
    """Мок-Redis для тестов settings_repo: in-memory dict-обёртка с TTL-неважно."""

    class _FakeRedis:
        def __init__(self) -> None:
            self._store: dict[str, str] = {}

        async def get(self, key: str) -> str | None:
            return self._store.get(key)

        async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
            self._store[key] = value

        async def delete(self, key: str) -> None:
            self._store.pop(key, None)

        async def incr(self, key: str) -> int:
            current = int(self._store.get(key, "0"))
            current += 1
            self._store[key] = str(current)
            return current

    return _FakeRedis()
