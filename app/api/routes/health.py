from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, str]:
    """Проверка живости сервиса. Без аутентификации."""
    return {"status": "ok"}
