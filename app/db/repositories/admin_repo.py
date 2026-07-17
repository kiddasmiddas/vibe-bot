"""Репозиторий для операций, специфичных для админского раздела бота (Этап 10).

Содержит методы, которые не относятся к одному репозиторию — например,
агрегированная аналитика по нескольким таблицам, поиск пользователя по
нескольким полям (users + profiles).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analytics import AnalyticsEvent
from app.db.models.moderation import Complaint, StopWord
from app.db.models.profile import Profile
from app.db.models.user import User


class AdminRepository:
    """Административные запросы: поиск, аналитика, агрегации."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Поиск пользователей (10.3)
    # ------------------------------------------------------------------ #

    async def search_users(self, query: str, *, limit: int = 20) -> list[User]:
        """Поиск по telegram_id (если query — число), username или profile.nickname.

        Case-insensitive LIKE %query% для текстовых полей.
        """
        query = query.strip()
        if not query:
            return []

        # Попытка числового поиска по telegram_id.
        if query.lstrip("@").isdigit():
            tg_id = int(query.lstrip("@"))
            stmt = select(User).where(User.telegram_id == tg_id).limit(limit)
            rows = list((await self._session.execute(stmt)).scalars().all())
            if rows:
                return rows

        # Нормализуем @ для username.
        username_query = query.lstrip("@")
        pattern = f"%{username_query}%"

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

    async def list_all_users_for_export(self) -> list[tuple[User, str | None]]:
        """Все пользователи + nickname из профиля — для выгрузки списком (10.3).

        Возвращает пары (User, nickname|None), отсортированные по User.id.
        """
        stmt = (
            select(User, Profile.nickname)
            .outerjoin(Profile, Profile.user_id == User.id)
            .order_by(User.id)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    # ------------------------------------------------------------------ #
    # Аналитика (10.10)
    # ------------------------------------------------------------------ #

    async def aggregate_by_event_type(
        self,
        since: datetime,
        until: datetime,
    ) -> dict[str, int]:
        """COUNT(*) по event_type за период [since, until)."""
        stmt = (
            select(
                AnalyticsEvent.event_type,
                func.count(AnalyticsEvent.id).label("cnt"),
            )
            .where(
                AnalyticsEvent.created_at >= since,
                AnalyticsEvent.created_at < until,
            )
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.event_type: row.cnt for row in rows}

    async def top_violators(self, *, limit: int = 10) -> list[tuple[int, int]]:
        """Топ-нарушители: (telegram_id, complaint_count) DESC.

        Возвращает Telegram ID (а не внутренний User.id), чтобы админ мог
        перейти к пользователю по кликабельной ссылке.
        """
        stmt = (
            select(
                User.telegram_id,
                func.count(Complaint.id).label("cnt"),
            )
            .join(User, User.id == Complaint.target_user_id)
            .group_by(User.telegram_id)
            .order_by(func.count(Complaint.id).desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row.telegram_id, row.cnt) for row in rows]

    # ------------------------------------------------------------------ #
    # Стоп-слова: поиск по подстроке (10.8.2)
    # ------------------------------------------------------------------ #

    async def search_stop_words(
        self,
        substring: str,
        *,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StopWord]:
        """Поиск стоп-слов по подстроке в pattern, с опциональным фильтром по category."""
        pattern = f"%{substring}%"
        stmt = select(StopWord).where(StopWord.pattern.ilike(pattern))
        if category:
            stmt = stmt.where(StopWord.category == category)
        stmt = stmt.order_by(StopWord.id).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_stop_words(
        self,
        *,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StopWord]:
        """Список всех стоп-слов (включая неактивные), с фильтром по категории."""
        stmt = select(StopWord)
        if category:
            stmt = stmt.where(StopWord.category == category)
        stmt = stmt.order_by(StopWord.id).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_stop_words(self, *, category: str | None = None) -> int:
        """Количество стоп-слов (включая неактивные) — для пагинации раздела."""
        stmt = select(func.count()).select_from(StopWord)
        if category:
            stmt = stmt.where(StopWord.category == category)
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_stop_word(self, sw_id: int) -> StopWord | None:
        return await self._session.get(StopWord, sw_id)

    # ------------------------------------------------------------------ #
    # Настройки: список всех ключей (10.9)
    # ------------------------------------------------------------------ #

    async def list_all_settings(self) -> list[tuple[str, str]]:
        """Возвращает все (key, value) пары из app_settings."""
        from app.db.models.settings import AppSetting

        stmt = select(AppSetting).order_by(AppSetting.key)
        rows = list((await self._session.execute(stmt)).scalars().all())
        return [(row.key, row.value) for row in rows]

    # ------------------------------------------------------------------ #
    # Profiles pending review (10.8.1)
    # ------------------------------------------------------------------ #

    async def list_pending_profiles(self, *, limit: int = 50, offset: int = 0) -> list[Profile]:
        stmt = (
            select(Profile)
            .where(
                Profile.is_pending_review.is_(True),
                Profile.is_completed.is_(True),
            )
            .order_by(Profile.created_at.asc(), Profile.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_pending_profiles(self) -> int:
        """COUNT(*) анкет, ожидающих ручной проверки (is_pending_review + is_completed)."""
        stmt = select(func.count(Profile.id)).where(
            Profile.is_pending_review.is_(True),
            Profile.is_completed.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
