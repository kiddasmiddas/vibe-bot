"""Миграция Telegram-медиа на новый BOT_TOKEN.

Telegram `file_id` привязан к конкретному боту: после смены `BOT_TOKEN` все
сохранённые в БД `file_id` перестают резолвиться новым ботом. Скрипт:

  1. скачивает каждый файл СТАРЫМ ботом (`get_file` + `download_file`);
  2. заливает его НОВЫМ ботом в storage-чат (`send_photo` / `send_audio` / ...);
  3. записывает новый `file_id` обратно в БД (тот же row).

Запускать ОДИН РАЗ, пока в `.env` ещё стоит СТАРЫЙ токен.

    docker cp scripts/migrate_media.py vibe-bot:/app/scripts/migrate_media.py
    docker exec \\
        -e NEW_BOT_TOKEN=<new> \\
        -e STORAGE_CHAT_ID=<tg_id> \\
        vibe-bot python /app/scripts/migrate_media.py

`OLD_BOT_TOKEN` по умолчанию берётся из текущего `.env` (`settings.bot_token`).
`STORAGE_CHAT_ID` — чат, куда новый бот имеет право писать: нажмите у нового
бота `/start` и передайте свой Telegram ID. Сообщения после заливки удаляются.

`DRY_RUN=1` — только посчитать и скачать, без записи в БД и без заливки.

Идемпотентность: скрипт ОДНОРАЗОВЫЙ. Повторный запуск после смены токена
упадёт — старый бот уже не сможет скачать мигрированные file_id.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from dataclasses import dataclass

# Позволяем запускать как `python /app/scripts/migrate_media.py` из любого cwd.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BufferedInputFile
from loguru import logger
from sqlalchemy import text

from app.config import settings
from app.db.base import async_session_factory


@dataclass(frozen=True)
class MediaField:
    """Описание колонки с `file_id`, которую нужно мигрировать."""

    table: str
    file_id_col: str
    kind: str = "photo"  # фиксированный тип, если type_col не задан
    type_col: str | None = None  # колонка со значением photo/video/gif/...
    pk_col: str = "id"


# Все места в БД, где хранятся Telegram file_id.
TARGETS: list[MediaField] = [
    MediaField("profiles", "main_media_file_id", type_col="main_media_type"),
    MediaField("profiles", "music_file_id", kind="audio"),
    MediaField("profiles", "video_note_file_id", kind="video_note"),
    MediaField("creator_posts", "music_file_id", kind="audio"),
    MediaField("creator_post_photos", "file_id", kind="photo"),
    MediaField("feed_post_media", "file_id", type_col="media_type"),
    MediaField("feed_comments", "media_file_id", type_col="media_type"),
    MediaField("vibes", "image_file_id", kind="photo"),
    MediaField("promo_posts", "media_file_id", type_col="media_type"),
]

# Нормализация значений type-колонок в aiogram-метод отправки.
KIND_MAP: dict[str, str] = {
    "photo": "photo",
    "video": "video",
    "gif": "animation",
    "animation": "animation",
    "audio": "audio",
    "voice": "voice",
    "video_note": "video_note",
    "document": "document",
}


async def _download(old_bot: Bot, file_id: str) -> bytes:
    """Скачать файл старым ботом по его file_id."""
    tg_file = await old_bot.get_file(file_id)
    if not tg_file.file_path:
        raise TelegramBadRequest(method=None, message="empty file_path")  # type: ignore[arg-type]
    buf = await old_bot.download_file(tg_file.file_path)
    if buf is None:
        raise TelegramBadRequest(method=None, message="download returned None")  # type: ignore[arg-type]
    return buf.read()


async def _reupload(new_bot: Bot, chat_id: int, kind: str, data: bytes) -> tuple[str, int]:
    """Залить файл новым ботом. Возвращает (новый file_id, message_id)."""
    file = BufferedInputFile(data, filename="media")
    if kind == "photo":
        msg = await new_bot.send_photo(chat_id, file)
        return msg.photo[-1].file_id, msg.message_id
    if kind == "video":
        msg = await new_bot.send_video(chat_id, file)
        return msg.video.file_id, msg.message_id  # type: ignore[union-attr]
    if kind == "animation":
        msg = await new_bot.send_animation(chat_id, file)
        return msg.animation.file_id, msg.message_id  # type: ignore[union-attr]
    if kind == "audio":
        msg = await new_bot.send_audio(chat_id, file)
        return msg.audio.file_id, msg.message_id  # type: ignore[union-attr]
    if kind == "voice":
        msg = await new_bot.send_voice(chat_id, file)
        return msg.voice.file_id, msg.message_id  # type: ignore[union-attr]
    if kind == "video_note":
        msg = await new_bot.send_video_note(chat_id, file)
        return msg.video_note.file_id, msg.message_id  # type: ignore[union-attr]
    if kind == "document":
        msg = await new_bot.send_document(chat_id, file)
        return msg.document.file_id, msg.message_id  # type: ignore[union-attr]
    raise ValueError(f"unknown media kind: {kind}")


async def _reupload_with_retry(
    new_bot: Bot, chat_id: int, kind: str, data: bytes
) -> tuple[str, int]:
    """Заливка с обработкой flood-control (`TelegramRetryAfter`)."""
    for attempt in range(5):
        try:
            return await _reupload(new_bot, chat_id, kind, data)
        except TelegramRetryAfter as exc:
            logger.warning(f"flood control: ждём {exc.retry_after}s (попытка {attempt + 1})")
            await asyncio.sleep(exc.retry_after + 1)
    raise RuntimeError("reupload failed after retries")


async def main() -> int:
    old_token = os.environ.get("OLD_BOT_TOKEN") or settings.bot_token
    new_token = os.environ.get("NEW_BOT_TOKEN")
    storage_raw = os.environ.get("STORAGE_CHAT_ID")
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}

    if not new_token:
        logger.error("NEW_BOT_TOKEN не задан")
        return 2
    if not storage_raw:
        logger.error("STORAGE_CHAT_ID не задан")
        return 2
    storage_chat_id = int(storage_raw)

    old_bot = Bot(old_token)
    new_bot = Bot(new_token)

    cache: dict[str, str] = {}  # старый file_id -> новый file_id
    stats = {"ok": 0, "reused": 0, "skip": 0, "fail": 0}

    try:
        old_me = await old_bot.get_me()
        new_me = await new_bot.get_me()
        logger.info(f"старый бот: @{old_me.username} ({old_me.id})")
        logger.info(f"новый бот:  @{new_me.username} ({new_me.id})")
        if old_me.id == new_me.id:
            logger.error("OLD и NEW токены — один и тот же бот, миграция бессмысленна")
            return 2

        # Проверяем, что новый бот может писать в storage-чат.
        if not dry_run:
            probe = await new_bot.send_message(storage_chat_id, "migrate_media: storage ok")
            await new_bot.delete_message(storage_chat_id, probe.message_id)
        logger.info(f"storage-чат {storage_chat_id} доступен, dry_run={dry_run}")

        async with async_session_factory() as session:
            for field in TARGETS:
                cols = f"{field.pk_col}, {field.file_id_col}"
                if field.type_col:
                    cols += f", {field.type_col}"
                query = f"SELECT {cols} FROM {field.table} WHERE {field.file_id_col} IS NOT NULL"
                rows = (await session.execute(text(query))).all()
                if not rows:
                    continue
                logger.info(f"{field.table}.{field.file_id_col}: {len(rows)} строк")

                for row in rows:
                    pk = row[0]
                    old_fid = row[1]
                    raw_kind = row[2] if field.type_col else field.kind
                    kind = KIND_MAP.get(str(raw_kind).lower(), field.kind)
                    tag = f"{field.table}#{pk}.{field.file_id_col}"

                    if old_fid in cache:
                        new_fid = cache[old_fid]
                        stats["reused"] += 1
                    else:
                        try:
                            data = await _download(old_bot, old_fid)
                        except TelegramBadRequest as exc:
                            logger.error(f"{tag}: не скачать ({exc.message}) — пропуск")
                            stats["skip"] += 1
                            continue
                        if dry_run:
                            logger.info(f"{tag}: dry-run, скачано {len(data)} байт ({kind})")
                            stats["ok"] += 1
                            continue
                        try:
                            new_fid, msg_id = await _reupload_with_retry(
                                new_bot, storage_chat_id, kind, data
                            )
                        except (TelegramBadRequest, RuntimeError, ValueError) as exc:
                            logger.error(f"{tag}: не залить ({exc}) — пропуск")
                            stats["fail"] += 1
                            continue
                        cache[old_fid] = new_fid
                        try:
                            await new_bot.delete_message(storage_chat_id, msg_id)
                        except TelegramBadRequest:
                            pass

                    if dry_run:
                        continue
                    await session.execute(
                        text(
                            f"UPDATE {field.table} SET {field.file_id_col} = :fid "
                            f"WHERE {field.pk_col} = :pk"
                        ),
                        {"fid": new_fid, "pk": pk},
                    )
                    await session.commit()
                    logger.info(f"{tag}: ok ({kind})")
                    stats["ok"] += 1
                    await asyncio.sleep(0.4)
    finally:
        await old_bot.session.close()
        await new_bot.session.close()

    logger.info(
        f"ГОТОВО: ok={stats['ok']} reused={stats['reused']} "
        f"skip={stats['skip']} fail={stats['fail']}"
    )
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
