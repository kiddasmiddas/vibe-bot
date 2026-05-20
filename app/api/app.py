from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import creators, feed, health
from app.config import settings

_LOCAL_DEV_ORIGIN = "http://localhost:5173"


def create_app() -> FastAPI:
    """Фабрика FastAPI-приложения для Mini App «Аллея креаторов»."""
    app = FastAPI(
        title="Vibe Bot Mini App API",
        docs_url="/api/docs" if settings.environment != "prod" else None,
        redoc_url=None,
    )

    # CORS: localhost Vite-dev — только вне prod. Всегда — configured MINIAPP_URL.
    origins: list[str] = []
    if settings.environment != "prod":
        origins.append(_LOCAL_DEV_ORIGIN)
    if settings.miniapp_url:
        # Берём только origin (схема + хост), без trailing slash / пути.
        from urllib.parse import urlparse

        parsed = urlparse(settings.miniapp_url)
        miniapp_origin = f"{parsed.scheme}://{parsed.netloc}"
        if miniapp_origin not in origins:
            origins.append(miniapp_origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(creators.router)
    app.include_router(feed.router)

    return app


app = create_app()
