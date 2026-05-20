from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_no_auth(api_client: AsyncClient) -> None:
    """GET /api/health доступен без аутентификации и возвращает {"status": "ok"}."""
    response = await api_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
