"""Ограничение на вес загружаемого пользователем медиа.

Используется в шаге медиа анкеты (регистрация и редактирование профиля).
То же ограничение в 5 МБ действует для фото постов Ленты — см.
`app/api/routes/feed.py:_MAX_UPLOAD_BYTES`.
"""

from __future__ import annotations

from aiogram.types import Message

# Максимальный вес фото/GIF — 5 МБ.
MAX_PHOTO_BYTES = 5 * 1024 * 1024


def photo_size_exceeded(message: Message) -> bool:
    """True, если прикреплённое к сообщению фото или GIF тяжелее лимита.

    Видео намеренно не ограничиваем — оно объективно весит больше, а его
    модерация и так ручная. `file_size` иногда отсутствует в апдейте —
    в этом случае не блокируем (мягкая деградация).
    """
    size: int | None = None
    if message.photo:
        size = message.photo[-1].file_size
    elif message.animation is not None:
        size = message.animation.file_size
    return size is not None and size > MAX_PHOTO_BYTES
