from __future__ import annotations

from html import escape as _html_escape

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.settings_repo import SettingsRepository
from app.services import bot_texts
from app.texts import common as texts

router = Router(name="support")

# Ключ настройки контакта поддержки в таблице app_settings.
SUPPORT_CONTACT_KEY = "support_contact"


@router.message(F.text == texts.BTN_SUPPORT)
async def on_support(message: Message, db_session: AsyncSession) -> None:
    settings_repo = SettingsRepository(db_session)
    contact = await settings_repo.get(SUPPORT_CONTACT_KEY)
    if not contact:
        contact = texts.RULES_FALLBACK_CONTACT
    # Контакт — значение настройки, экранируем: сообщение уходит с parse_mode=HTML.
    body = await bot_texts.render_text(
        settings_repo, bot_texts.KEY_RULES, contact=_html_escape(contact)
    )
    await message.answer(body)
