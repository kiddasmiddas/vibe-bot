from __future__ import annotations

# Экран Premium — заголовок и преимущества
SCREEN_TITLE = "✨ Vibe Premium"

BENEFITS = (
    "Что даёт Premium:\n\n"
    "🎵 Музыка в анкете — добавь трек, который звучит в твоей голове\n"
    "🎥 Кружок — запись-приветствие прямо в анкете\n"
    "🚫 Без рекламы — никаких промо-постов в ленте\n"
    "🌟 Расширенная карточка в Аллее — твой пост заметнее"
)

PRICE_TEMPLATE = "{price} ₽ / {days} дней"

BTN_BUY = "Оплатить"

# Данные инвойса Telegram Payments
INVOICE_TITLE = "Vibe Premium"
INVOICE_DESCRIPTION = "Музыка, кружок, без рекламы и расширенная карточка в Аллее креаторов."
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
