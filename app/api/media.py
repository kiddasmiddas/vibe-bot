"""Резолв Telegram file_id в публичный URL для Mini App.

Telegram `file_id` нельзя вставить в `<img src>` — это внутренний идентификатор.
Реальный URL файла: `https://api.telegram.org/file/bot<TOKEN>/<file_path>`,
где `file_path` отдаёт метод `getFile`.

⚠️ ВАЖНО: этот URL НЕ вечен. Telegram гарантирует его валидность лишь ~1 час
(«valid for at least 1 hour»), после чего `file_path` протухает и ссылка отдаёт
404 — картинки в ленте/аллее становятся битыми. Поэтому кэш URL держим с TTL
меньше часа и по истечении перерезолвим через getFile заново.
"""

from __future__ import annotations

import time

from aiogram import Bot
from loguru import logger

from app.config import settings

# file_id -> (url, expires_at monotonic). Процесс-локальный кэш с TTL: снимает
# нагрузку getFile на каждый запрос ленты, но не даёт отдавать протухший URL.
# TTL с запасом меньше часового гарантийного окна Telegram file_path.
_URL_TTL_SECONDS = 45 * 60
_URL_CACHE_MAX = 1000
_url_cache: dict[str, tuple[str, float]] = {}
_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.bot_token)
    return _bot


async def resolve_file_url(file_id: str | None) -> str | None:
    """Возвращает свежий HTTP-URL картинки по Telegram file_id.

    Кэш с TTL: пока URL заведомо жив — отдаём из кэша, иначе перерезолвим.
    На любой ошибке (нет сети, битый file_id, плейсхолдер) возвращает None —
    фронт покажет fallback-плашку, лента не падает.
    """
    if not file_id:
        return None
    now = time.monotonic()
    cached = _url_cache.get(file_id)
    if cached is not None and cached[1] > now:
        return cached[0]
    try:
        tg_file = await _get_bot().get_file(file_id)
        if tg_file.file_path is None:
            return None
        url = f"https://api.telegram.org/file/bot{settings.bot_token}/{tg_file.file_path}"
        # Переполнение — сброс целиком (без внешних зависимостей на LRU).
        if len(_url_cache) >= _URL_CACHE_MAX:
            _url_cache.clear()
        _url_cache[file_id] = (url, now + _URL_TTL_SECONDS)
        return url
    except Exception as exc:
        logger.warning("resolve_file_url failed for file_id={}: {}", file_id[:16], exc)
        return None


async def resolve_many(file_ids: list[str]) -> list[str]:
    """Резолвит список file_id в URL, отбрасывая то, что не резолвится."""
    resolved: list[str] = []
    for fid in file_ids:
        url = await resolve_file_url(fid)
        if url is not None:
            resolved.append(url)
    return resolved
