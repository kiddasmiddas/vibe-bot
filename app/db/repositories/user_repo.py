from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.profile import Profile
from app.db.models.user import User


class UserRepository:
    """Доступ к таблице users. Только через эту прослойку, без сырых select в хэндлерах."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def create(self, *, telegram_id: int, username: str | None = None) -> User:
        user = User(telegram_id=telegram_id, username=username)
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_premium(
        self,
        user_id: int,
        *,
        is_premium: bool,
        premium_until: datetime | None,
    ) -> None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(is_premium=is_premium, premium_until=premium_until)
        )
        await self._session.execute(stmt)

    async def set_banned(self, user_id: int, *, banned: bool) -> None:
        stmt = update(User).where(User.id == user_id).values(is_banned=banned)
        await self._session.execute(stmt)

    async def set_moderator(self, user_id: int, *, moderator: bool) -> None:
        """Назначает/снимает роль модератора. Вызывается только полным админом."""
        stmt = update(User).where(User.id == user_id).values(is_moderator=moderator)
        await self._session.execute(stmt)

    async def list_expired_premium(self, now: datetime) -> list[User]:
        """Возвращает пользователей с истёкшим Premium (для шедулера premium_expiry).

        Условие: is_premium=True AND premium_until < now.
        """
        stmt = select(User).where(
            User.is_premium.is_(True),
            User.premium_until < now,
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_premium(self, user_id: int, until: datetime) -> None:
        """Выставляет is_premium=True и premium_until=until."""
        stmt = update(User).where(User.id == user_id).values(is_premium=True, premium_until=until)
        await self._session.execute(stmt)

    async def clear_premium(self, user_id: int) -> None:
        """Снимает Premium (is_premium=False), не трогает premium_until как историческое."""
        stmt = update(User).where(User.id == user_id).values(is_premium=False)
        await self._session.execute(stmt)

    async def hard_delete(self, user_id: int) -> None:
        """Полное физическое удаление пользователя (для тестов / админских операций)."""
        await self._session.execute(delete(User).where(User.id == user_id))

    async def search(self, query: str, *, limit: int = 20) -> list[User]:
        """Поиск пользователей по telegram_id (числовой запрос), username или nickname.

        Используется в админском разделе (10.3).
        """
        query = query.strip()
        if not query:
            return []

        clean = query.lstrip("@")
        if clean.isdigit():
            tg_id = int(clean)
            stmt = select(User).where(User.telegram_id == tg_id).limit(limit)
            rows = list((await self._session.execute(stmt)).scalars().all())
            if rows:
                return rows

        username_q = query.lstrip("@")
        pattern = f"%{username_q}%"
        stmt = (
            select(User)
            .outerjoin(Profile, Profile.user_id == User.id)
            .where(
                or_(
                    User.username.ilike(pattern),
                    Profile.nickname.ilike(pattern),
                )
            )
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_by_segment(self, segment: str) -> list[User]:
        """Возвращает пользователей для рассылки по сегменту.

        Segment values:
        - ``all``     — все не забаненные пользователи.
        - ``free``    — не забаненные без Premium.
        - ``premium`` — не забаненные с Premium.

        Для сегмента ``custom`` метод возвращает пустой список — получатели
        берутся из таблицы promo_post_recipients напрямую (broadcast_service).
        Исключение Premium-пользователей из ``all`` / ``free`` — на стороне
        broadcast_service согласно §9.2 ТЗ.
        """
        if segment == "custom":
            return []
        base = select(User).where(User.is_banned.is_(False))
        if segment == "free":
            base = base.where(User.is_premium.is_(False))
        elif segment == "premium":
            base = base.where(User.is_premium.is_(True))
        # segment == "all" — только фильтр is_banned=False, нет дополнительных ограничений
        return list((await self._session.execute(base)).scalars().all())

    async def list_announcement_recipients(
        self, *, exclude_user_id: int | None = None
    ) -> list[User]:
        """Получатели объявления: все незабаненные пользователи, кроме автора."""
        stmt = select(User).where(User.is_banned.is_(False))
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_moderators(self) -> list[User]:
        """Возвращает активных модераторов (is_moderator=True, is_banned=False).

        Используется для рассылки уведомлений о новых анкетах и постах Ленты
        на проверку — вместе с env-адресами admin_telegram_ids.
        """
        stmt = select(User).where(
            User.is_moderator.is_(True),
            User.is_banned.is_(False),
        )
        return list((await self._session.execute(stmt)).scalars().all())
