"""Тексты раздела «Искать своих» (этап 4.2)."""

from __future__ import annotations

NO_PROFILE_YET = "Сначала создай анкету через /start."
PROFILE_PENDING_REVIEW_BLOCKED = (
    "Твоя анкета на ручной проверке у модератора. Поиск откроется, как только медиа одобрят."
)
NO_CANDIDATES = "Пока никого нового. Загляни позже или расширь параметры в «Моя анкета»."
NO_MORE_CANDIDATES = "На сегодня анкеты закончились. Возвращайся завтра или меняй параметры."

ASK_SUPERLIKE_MESSAGE = (
    "Напиши короткое сообщение для собеседника (до 200 символов).\n"
    "Или нажми «Отмена», чтобы вернуться к просмотру анкет."
)
SUPERLIKE_MESSAGE_TOO_LONG = "Слишком длинное. Уложись в 200 символов."
SUPERLIKE_SENT = "Лайк с сообщением отправлен."
SUPERLIKE_CANCELLED = "Отменили лайк с сообщением."
BTN_CANCEL_SUPERLIKE = "✖️ Отмена"

COMPLAIN_STUB = "Жалобы появятся в следующем обновлении."

MODERATION_REJECTED_STOP_WORD = "Сообщение не прошло модерацию. Попробуй переформулировать."
MODERATION_REJECTED_LINK = "Ссылки в сообщениях запрещены. Без ссылки и попробуй ещё раз."

# Заголовок над карточкой кандидата (для caption).
CANDIDATE_HEADER = "Анкета:"

# Кнопки.
BTN_LIKE = "❤️ Лайк"
BTN_SUPERLIKE = "💬 С сообщением"
BTN_DISLIKE = "👎 Дизлайк"
BTN_COMPLAIN = "🚩 Жалоба"
BTN_BLOCK = "🚫 Блок"
BTN_SKIP = "⏭"

# Максимальная длина сообщения для superlike.
SUPERLIKE_MESSAGE_MAX_LENGTH = 200

# --------------------------- 4.3: уведомления и «Мои лайки / мэтчи» ---------------------------

MATCH_HEADER = "У вас мэтч с {nickname}!"
MATCH_WITH_MESSAGE = "У вас мэтч с {nickname}!\n\nСообщение: {message}"
BTN_OPEN_PROFILE = "Открыть профиль"

MATCHES_MENU_HEADER = "Что смотрим?"
MATCHES_BTN_INCOMING = "Кто меня лайкнул ({n})"
MATCHES_BTN_MATCHES = "Мои мэтчи ({n})"
NO_INCOMING_LIKES = "Никого, кто бы тебя лайкнул. Заглядывай позже."
NO_MATCHES_YET = "Пока нет мэтчей. Лайкай ещё!"
INCOMING_LIKE_HEADER = "Тебя лайкнул:"
INCOMING_LIKE_WITH_MESSAGE = "Тебя лайкнул, написав:\n«{message}»"
NEXT_BTN = "➡️ Дальше"
LIKE_BACK_BTN = "❤️ В ответ"
DISLIKE_INCOMING_BTN = "👎"

# --- City proximity badges ---
# Prepended to the candidate card when the candidate is not from the searcher's city.
CANDIDATE_BADGE_NEIGHBOR_CITY = "Из соседнего города\n"
CANDIDATE_BADGE_OTHER_REGION = "Из другого региона\n"
