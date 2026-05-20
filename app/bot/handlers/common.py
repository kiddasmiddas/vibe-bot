from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import main_menu_kb
from app.db.models.user import User
from app.db.repositories.profile_repo import ProfileRepository
from app.texts import common as texts

router = Router(name="common")


async def _is_registered(db_session: AsyncSession, user: User) -> bool:
    profile = await ProfileRepository(db_session).get_by_user_id(user.id)
    return profile is not None and profile.is_completed


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, db_session: AsyncSession) -> None:
    is_registered = await _is_registered(db_session, user)
    await message.answer(
        texts.WELCOME,
        reply_markup=main_menu_kb(is_registered=is_registered),
    )
