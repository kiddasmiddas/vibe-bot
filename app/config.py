from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["dev", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str = Field(..., description="Telegram bot token from @BotFather")

    webhook_host: str = ""
    webhook_path: str = "/webhook"
    webhook_secret: str = ""

    database_url: str = Field(
        default="postgresql+asyncpg://vibe:vibe@localhost:5432/vibe",
        description="Async SQLAlchemy URL (postgresql+asyncpg://...)",
    )
    redis_url: str = "redis://localhost:6379/0"

    yookassa_provider_token: str = ""

    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    log_level: str = "INFO"
    environment: Environment = "dev"

    miniapp_url: str = ""
    api_base_url: str = ""

    nudenet_model_path: str = "models/nudenet.onnx"
    nsfw_threshold: float = 0.7

    # Mini App API — dev helpers
    miniapp_dev_bypass_auth: bool = False
    # Хранит TELEGRAM_ID (а не внутренний User.id) — для get_by_telegram_id.
    miniapp_dev_telegram_id: int = 0
    miniapp_session_ttl_seconds: int = 3600

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @model_validator(mode="after")
    def _guard_dev_bypass_in_prod(self) -> Settings:
        """Защита от случайного деплоя dev-bypass в прод.

        miniapp_dev_bypass_auth=True означает, что Mini App API авторизует
        запросы без подписи. В prod это дыра — падаем на старте, а не молча.
        """
        if self.environment == "prod" and self.miniapp_dev_bypass_auth:
            raise ValueError(
                "MINIAPP_DEV_BYPASS_AUTH=true несовместим с ENVIRONMENT=prod — "
                "отключите bypass перед продакшн-деплоем"
            )
        return self

    @property
    def alembic_database_url(self) -> str:
        """Sync URL for Alembic (psycopg)."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
