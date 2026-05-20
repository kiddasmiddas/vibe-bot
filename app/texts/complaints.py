"""Тексты раздела «Жалоба» (этап 5.1)."""

from __future__ import annotations

ASK_REASON = "Что не так с этой анкетой?"
BTN_CANCEL = "Отмена"
ASK_COMMENT = "Опиши проблему текстом или нажми «Пропустить»."
BTN_SKIP_COMMENT = "Пропустить"
COMPLAINT_SENT = "Спасибо, мы разберёмся."
COMPLAINT_CANCELLED = "Жалоба отменена."
COMMENT_REJECTED_STOP_WORD = "В комментарии нашлись запрещённые слова. Перепиши."
ADMIN_NOTIFY_TEMPLATE = (
    "🚩 Жалоба #{complaint_id}\n"
    'От: {from_nickname} (id={from_id}, tg=<a href="tg://user?id={from_tg_id}">{from_tg_id}</a>)\n'
    'На: {target_nickname} (id={target_id}, tg=<a href="tg://user?id={target_tg_id}">{target_tg_id}</a>)\n'
    "Причина: {reason}\n"
    "Комментарий: {comment}"
)
