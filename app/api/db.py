from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends: одна сессия на HTTP-запрос, закрывается автоматически."""
    async with async_session_factory() as session:
        yield session
