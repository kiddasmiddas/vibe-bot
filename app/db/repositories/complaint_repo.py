from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.moderation import Complaint
from app.db.models.profile import Profile
from app.db.models.user import User


@dataclass(frozen=True, slots=True)
class ComplaintWithDetails:
    """Жалоба с подгруженными смежными записями для отображения в карточке.

    `violator_profile` может быть None — если нарушитель не заполнял анкету.
    `violator_username` и `reporter_username` — из таблицы users (может быть None).
    `reason_id` — для формирования подписи причины жалобы без отдельного запроса.
    """

    complaint: Complaint
    violator: User
    violator_profile: Profile | None
    reporter: User


class ComplaintRepository:
    """Доступ к таблице complaints. Управление статусами обработки."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        from_user_id: int,
        target_user_id: int,
        reason_id: int,
        comment: str | None = None,
    ) -> Complaint:
        complaint = Complaint(
            from_user_id=from_user_id,
            target_user_id=target_user_id,
            reason_id=reason_id,
            comment=comment,
        )
        self._session.add(complaint)
        await self._session.flush()
        return complaint

    async def get_by_id(self, complaint_id: int) -> Complaint | None:
        return await self._session.get(Complaint, complaint_id)

    async def list_by_status(
        self,
        status: str,
        limit: int,
        offset: int = 0,
    ) -> list[Complaint]:
        stmt = (
            select(Complaint)
            .where(Complaint.status == status)
            .order_by(Complaint.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_against_user(self, target_user_id: int) -> int:
        stmt = select(func.count(Complaint.id)).where(Complaint.target_user_id == target_user_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def set_in_progress(self, complaint_id: int, moderator_user_id: int) -> None:
        stmt = (
            update(Complaint)
            .where(Complaint.id == complaint_id)
            .values(status="in_progress", moderator_user_id=moderator_user_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def resolve(
        self,
        complaint_id: int,
        moderator_user_id: int,
        note: str | None = None,
    ) -> None:
        stmt = (
            update(Complaint)
            .where(Complaint.id == complaint_id)
            .values(
                status="resolved",
                resolved_at=func.now(),
                moderator_user_id=moderator_user_id,
                moderator_note=note,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def delete_by_user(self, user_id: int) -> None:
        """Удаляет все жалобы, где user_id участвует как автор или цель.

        Используется в GDPR-удалении профиля (этап 3.4).
        """
        await self._session.execute(
            delete(Complaint).where(
                or_(
                    Complaint.from_user_id == user_id,
                    Complaint.target_user_id == user_id,
                )
            )
        )
        await self._session.flush()

    async def list_paginated(
        self,
        status: str,
        offset: int = 0,
        limit: int = 10,
    ) -> list[Complaint]:
        """Список жалоб с пагинацией — алиас для list_by_status (10.4)."""
        return await self.list_by_status(status, limit=limit, offset=offset)

    async def set_status(
        self,
        complaint_id: int,
        status: str,
        resolver_id: int,
        *,
        note: str | None = None,
    ) -> None:
        """Универсальная смена статуса (10.4)."""
        stmt = (
            update(Complaint)
            .where(Complaint.id == complaint_id)
            .values(
                status=status,
                resolved_at=func.now(),
                moderator_user_id=resolver_id,
                moderator_note=note,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def reject(
        self,
        complaint_id: int,
        moderator_user_id: int,
        note: str | None = None,
    ) -> None:
        stmt = (
            update(Complaint)
            .where(Complaint.id == complaint_id)
            .values(
                status="rejected",
                resolved_at=func.now(),
                moderator_user_id=moderator_user_id,
                moderator_note=note,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_with_details(
        self,
        status: str,
        offset: int = 0,
        limit: int = 20,
    ) -> list[ComplaintWithDetails]:
        """Жалобы, joinед с нарушителем, его анкетой и репортером.

        Результат детерминированно упорядочен по (created_at ASC, id ASC),
        чтобы модератор всегда двигался «вперёд» во времени и offset был стабильным.

        Нарушитель и репортер подключены INNER JOIN — жалобы без любого из них
        не попадают в выдачу. Это согласовано с `count_with_details`, поэтому
        offset считается по тому же набору, и пагинация «page/total» не врёт.
        """
        violator = aliased(User)
        reporter = aliased(User)
        stmt = (
            select(Complaint, violator, Profile, reporter)
            .join(violator, Complaint.target_user_id == violator.id)
            .join(reporter, Complaint.from_user_id == reporter.id)
            .outerjoin(Profile, Profile.user_id == violator.id)
            .where(Complaint.status == status)
            .order_by(Complaint.created_at.asc(), Complaint.id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            ComplaintWithDetails(
                complaint=complaint,
                violator=violator_user,
                violator_profile=profile,
                reporter=reporter_user,
            )
            for complaint, violator_user, profile, reporter_user in rows
        ]

    async def count_with_details(self, status: str) -> int:
        """Количество жалоб, отображаемых карточкой: нарушитель И репортер есть.

        Зеркалит INNER JOIN-семантику `list_with_details`, чтобы `total` в
        пагинации совпадал с реально доступным числом карточек.
        """
        violator = aliased(User)
        reporter = aliased(User)
        stmt = (
            select(func.count(Complaint.id))
            .join(violator, Complaint.target_user_id == violator.id)
            .join(reporter, Complaint.from_user_id == reporter.id)
            .where(Complaint.status == status)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_by_status(self, status: str) -> int:
        """Количество жалоб с данным статусом (без join'ов).

        Для пагинации карточек использовать `count_with_details` — оно
        согласовано с `list_with_details`.
        """
        stmt = select(func.count(Complaint.id)).where(Complaint.status == status)
        return int((await self._session.execute(stmt)).scalar_one())
