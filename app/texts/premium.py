from __future__ import annotations

# Экран Premium — заголовок и преимущества
SCREEN_TITLE = "✨ Vibe Premium"

BENEFITS = (
    "💎 Премиум-подписка даёт:\n\n"
    "💚 Возможность публикации постов в «Ленте» 🌟\n"
    "💚 Увеличивает лимит комментариев в «Ленте»: с 70 до 300 в день ⭐️\n"
    "💚 Расширенная анкета: можно прикрепить кружок и видео ✨"
)

PRICE_TEMPLATE = "{price} ₽ / {days} дней"

BTN_BUY = "Оплатить"

# Данные инвойса Telegram Payments
INVOICE_TITLE = "Vibe Premium"
INVOICE_DESCRIPTION = "Посты в «Ленте», лимит комментариев 300/день, кружок и видео в анкете."
INVOICE_LABEL_PRICE = "Premium-подписка"

# Результаты оплаты
PAYMENT_SUCCESS_TEMPLATE = "Premium активен до {until}"
PAYMENT_FAILED = "Платёж не прошёл, попробуй ещё раз."

# Если Premium уже активен
ALREADY_PREMIUM_TEMPLATE = (
    "💎 Premium уже приобретён.\nДействует до {until} — осталось {days_left} дн."
)

# У администратора Premium-доступ априори, без подписки и срока
ADMIN_PREMIUM_NOTICE = (
    "💎 У тебя есть Premium-доступ как у администратора — бессрочно, покупка не нужна."
)

# Fallback если провайдер не настроен
PROVIDER_TOKEN_MISSING = "Оплата временно недоступна. Попробуй позже."
