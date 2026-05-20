"""Резолв Telegram file_id в публичный URL для Mini App.

Telegram `file_id` нельзя вставить в `<img src>` — это внутренний идентификатор.
Реальный URL файла: `https://api.telegram.org/file/bot<TOKEN>/<file_path>`,
где `file_path` отдаёт метод `getFile`. `file_path` для файла стабилен,
поэтому кэшируем в процессе, чтобы не дёргать getFile на каждый запрос ленты.
"""

from __future__ import annotations

from aiogram import Bot
from loguru import logger

from app.config import settings

# file_id -> готовый URL. Процесс-локальный кэш (file_path не меняется).
# При достижении _URL_CACHE_MAX записей кэш сбрасывается полностью, чтобы
# исключить неограниченный рост памяти без внешних зависимостей.
_URL_CACHE_MAX = 1000
_url_cache: dict[str, str] = {}
_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.bot_token)
    return _bot


async def resolve_file_url(file_id: str | None) -> str | None:
    """Возвращает HTTP-URL картинки по Telegram file_id.

    На любой ошибке (нет сети, битый file_id, плейсхолдер) возвращает None —
    фронт покажет fallback-плашку, лента не падает.
    """
    if not file_id:
        return None
    if file_id in _url_cache:
        return _url_cache[file_id]
    try:
        tg_file = await _get_bot().get_file(file_id)
        if tg_file.file_path is None:
            return None
        url = f"https://api.telegram.org/file/bot{settings.bot_token}/{tg_file.file_path}"
        if len(_url_cache) >= _URL_CACHE_MAX:
            _url_cache.clear()
        _url_cache[file_id] = url
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
