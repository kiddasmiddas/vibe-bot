"""Тексты Premium-фичи «Вайб по фото».

Юзер шлёт 1-3 фото, модератор подбирает вайб по картинкам в личке (или
открывает запрос из /admin) и присваивает профилю. Staging-чат — тупо
архив медиа без управления. Все строки, видимые пользователю и модератору,
— здесь.
"""

from __future__ import annotations

# --- кнопка-инициатор в пикере own_vibe ---
BTN_VIBE_BY_PHOTO = "🖼 Вайб по фото"

# --- кнопки в state vibe_by_photo_upload ---
BTN_VIBE_BY_PHOTO_DONE = "✅ Отправить"
BTN_VIBE_BY_PHOTO_CANCEL = "Отменить"

# --- сообщения пользователю ---
ASK_PHOTOS = (
    "🖼 <b>Вайб по фото</b>\n\n"
    "Загрузи 1-3 свои фотографии — модератор подберёт вайб.\n\n"
    "Команды:\n"
    "• /done — отправить\n"
    "• /cancel — отменить"
)
PHOTO_RECEIVED_TEMPLATE = "Получено {received}/3. Можешь прислать ещё или нажать «Отправить»."
PHOTO_MAX_REACHED = "Достаточно — у тебя уже 3 фото. Нажми «Отправить» или «Отменить»."
PHOTO_NEED_AT_LEAST_ONE = "Сначала пришли хотя бы одно фото."
WRONG_TYPE = "Это не фото. Пришли изображение."
SENT_TO_MOD = (
    "Спасибо! Фото отправлены модератору. Как только подберём вайб — пришлю результат сюда."
)
RESULT_TEMPLATE = "✨ Модератор подобрал тебе вайб: <b>{vibe_title}</b>."
REJECTED = (
    "К сожалению, по присланным фото вайб подобрать не удалось. "
    "Выбери, пожалуйста, вайб вручную в пикере ниже."
)
CANCELLED = "Окей, возвращаемся к обычному выбору вайба."
NOT_PREMIUM = "Эта функция доступна только с Premium."

# --- staging-чат: подпись (КНОПКИ не прикладываем; чат — архив медиа) ---
# Bot работает с parse_mode=HTML. {username} приходит уже экранированный.
STAGING_CAPTION_TEMPLATE = (
    "🗂 Архив: запрос #{request_id}\nuser_id={user_id} username={username}\norigin: {origin}"
)

# --- сообщение модератору в личке: заголовок над фотками ---
ADMIN_REQUEST_HEADER_TEMPLATE = (
    "🖼 <b>Запрос #{request_id}</b> — вайб по фото\n"
    "От: {username} (user_id={user_id})\n"
    "Источник: {origin}{profile_block}"
)
# Опциональный блок про существующий профиль (если origin=profile_edit).
ADMIN_REQUEST_PROFILE_BLOCK_TEMPLATE = (
    "\n\n<b>Текущий профиль:</b> {nickname}, {age}, {city}\nСейчас выбран вайб: {current_vibe}"
)
ADMIN_REQUEST_PROFILE_BLOCK_NO_PROFILE = ""  # для origin=registration

# --- сообщение модератору в личке: пикер вайбов ---
ADMIN_PICK_VIBE_HEADER_TEMPLATE = (
    "Выбери вайб для запроса #{request_id} (страница {page_num}/{total_pages}):"
)
ADMIN_PAGE_INDICATOR_TEMPLATE = "{page_num}/{total_pages}"

ADMIN_BTN_PAGE_PREV = "‹"
ADMIN_BTN_PAGE_NEXT = "›"
ADMIN_BTN_PREV_REQUEST = "↩️ К прошлой"
ADMIN_BTN_SKIP_REQUEST = "⏭ Пропустить"
ADMIN_BTN_REJECT = "❌ Отклонить"

ADMIN_NO_PREV_REQUEST = "Это первый запрос в очереди."
ADMIN_NO_NEXT_REQUEST = "Это последний запрос в очереди."
ADMIN_QUEUE_EMPTY_AFTER_ACTION = "✅ Готово. Больше pending-запросов нет."

# Ошибки при тапе по устаревшей кнопке.
ADMIN_REQUEST_NOT_FOUND = "Запрос не найден или уже обработан."
ADMIN_ALREADY_HANDLED = "Запрос уже обработан другим модератором."
ADMIN_NOT_AUTHORIZED = "Доступно только модераторам и админам."

ADMIN_ASSIGNED_TEMPLATE = "✅ Вайб «{vibe_title}» назначен пользователю user_id={user_id}."
ADMIN_REJECTED_TEMPLATE = "❌ Запрос #{request_id} отклонён."

# --- раздел /admin → «Вайб по фото» ---
ADMIN_QUEUE_TITLE = "🖼 <b>Очередь «Вайб по фото»</b>"
ADMIN_QUEUE_EMPTY = "Нет запросов, ожидающих модерации."
ADMIN_QUEUE_FOUND_TEMPLATE = "Найдено: {count}"
ADMIN_QUEUE_ITEM_TEMPLATE = "#{request_id} · {username} · {photos_count} фото · {origin}"
ADMIN_QUEUE_BTN_OPEN_TEMPLATE = "#{request_id} {username}"
