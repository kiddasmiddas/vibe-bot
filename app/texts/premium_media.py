"""Тексты Premium-фич в анкете: музыка и кружок (Этап 8)."""

from __future__ import annotations

# --- Общее ---
NEED_PREMIUM = (
    "🔒 Эта функция доступна только с Premium.\nОткрой раздел Premium, чтобы подключить подписку."
)

# --- Музыка ---
MUSIC_INSTRUCTION = (
    "🎵 Добавь музыку в анкету!\n\n"
    "Как это сделать:\n"
    "1. Открой бота @TgSoundBot\n"
    "2. Найди нужный трек\n"
    "3. Нажми «Поделиться» и перешли аудио в этот чат\n\n"
    "Жду твоё аудио. Для отмены — /cancel"
)
MUSIC_WAITING_AUDIO = "Жду аудио из @TgSoundBot, или /cancel"
MUSIC_SAVED = "🎵 Музыка добавлена в анкету!"
MUSIC_REMOVED = "Музыка убрана из анкеты."

# --- Кружок ---
VIDEO_NOTE_INSTRUCTION = (
    "🎬 Добавь кружок в анкету!\n\n"
    "Запиши круглое видео-сообщение (кружок) и пришли мне.\n"
    "Для отмены — /cancel"
)
VIDEO_NOTE_WAITING = "Жду круглое видео-сообщение (кружок), или /cancel"
VIDEO_NOTE_SAVED = "🎬 Кружок добавлен в анкету!"
VIDEO_NOTE_REMOVED = "Кружок убран из анкеты."
VIDEO_NOTE_WRONG_TYPE = (
    "Это обычное видео, а не кружок.\n"
    "Пришли именно круглое видео-сообщение (video_note), или /cancel"
)

# --- Кнопки ---
BTN_ADD_MUSIC = "🎵 Добавить музыку"
BTN_CHANGE_MUSIC = "🎵 Изменить музыку"
BTN_REMOVE_MUSIC = "❌ Убрать музыку"

BTN_ADD_VIDEO_NOTE = "🎬 Добавить кружок"
BTN_CHANGE_VIDEO_NOTE = "🎬 Изменить кружок"
BTN_REMOVE_VIDEO_NOTE = "❌ Убрать кружок"
