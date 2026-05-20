from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.settings_repo import SettingsRepository
from app.texts import common as texts

router = Router(name="support")

# Ключ настройки контакта поддержки в таблице app_settings.
SUPPORT_CONTACT_KEY = "support_contact"


@router.message(F.text == texts.BTN_SUPPORT)
async def on_support(message: Message, db_session: AsyncSession) -> None:
    contact = await SettingsRepository(db_session).get(SUPPORT_CONTACT_KEY)
    if not contact:
        contact = texts.RULES_FALLBACK_CONTACT
    await message.answer(texts.RULES_BODY.format(contact=contact))
