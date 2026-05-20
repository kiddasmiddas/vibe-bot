from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.profile import (
    Profile,
    ProfileDesiredFandom,
    ProfileDesiredVibe,
    ProfileFandom,
    ProfileInterest,
    ProfileLookingForGender,
)


class ProfileRepository:
    """Доступ к таблице profiles и связным M2M. Только через эту прослойку."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: int) -> Profile | None:
        stmt = select(Profile).where(Profile.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, profile_id: int) -> Profile | None:
        return await self._session.get(Profile, profile_id)

    async def create(self, *, user_id: int, **fields: Any) -> Profile:
        profile = Profile(user_id=user_id, **fields)
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def update(self, profile_id: int, **fields: Any) -> Profile:
        if fields:
            stmt = update(Profile).where(Profile.id == profile_id).values(**fields)
            await self._session.execute(stmt)
            await self._session.flush()
        profile = await self._session.get(Profile, profile_id)
        if profile is None:
            raise LookupError(f"profile_id={profile_id} not found")
        await self._session.refresh(profile)
        return profile

    async def _replace_links(
        self,
        link_model: type[Any],
        profile_id: int,
        ids: list[int],
        *,
        ref_column: str,
    ) -> None:
        """Atomic replace: удалить все связи и вставить новые в одной транзакции."""
        await self._session.execute(delete(link_model).where(link_model.profile_id == profile_id))
        if ids:
            # Дедупликация на случай дублей во входе.
            unique_ids = list(dict.fromkeys(ids))
            self._session.add_all(
                [link_model(profile_id=profile_id, **{ref_column: ref_id}) for ref_id in unique_ids]
            )
        await self._session.flush()

    async def set_fandoms(self, profile_id: int, fandom_ids: list[int]) -> None:
        await self._replace_links(ProfileFandom, profile_id, fandom_ids, ref_column="fandom_id")

    async def set_desired_fandoms(self, profile_id: int, fandom_ids: list[int]) -> None:
        await self._replace_links(
            ProfileDesiredFandom, profile_id, fandom_ids, ref_column="fandom_id"
        )

    async def set_interests(self, profile_id: int, interest_ids: list[int]) -> None:
        await self._replace_links(
            ProfileInterest, profile_id, interest_ids, ref_column="interest_id"
        )

    async def set_looking_for_genders(self, profile_id: int, gender_ids: list[int]) -> None:
        await self._replace_links(
            ProfileLookingForGender, profile_id, gender_ids, ref_column="gender_id"
        )

    async def mark_completed(self, profile_id: int) -> None:
        stmt = update(Profile).where(Profile.id == profile_id).values(is_completed=True)
        await self._session.execute(stmt)

    async def set_hidden(self, profile_id: int, hidden: bool) -> None:
        stmt = update(Profile).where(Profile.id == profile_id).values(is_hidden=hidden)
        await self._session.execute(stmt)

    async def delete_by_user_id(self, user_id: int) -> None:
        """Удаляет профиль и каскадно все его M2M-связи (ondelete=CASCADE)."""
        await self._session.execute(delete(Profile).where(Profile.user_id == user_id))

    async def get_fandom_ids(self, profile_id: int) -> list[int]:
        stmt = select(ProfileFandom.fandom_id).where(ProfileFandom.profile_id == profile_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_desired_fandom_ids(self, profile_id: int) -> list[int]:
        stmt = select(ProfileDesiredFandom.fandom_id).where(
            ProfileDesiredFandom.profile_id == profile_id
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_interest_ids(self, profile_id: int) -> list[int]:
        stmt = select(ProfileInterest.interest_id).where(ProfileInterest.profile_id == profile_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_looking_for_gender_ids(self, profile_id: int) -> list[int]:
        stmt = select(ProfileLookingForGender.gender_id).where(
            ProfileLookingForGender.profile_id == profile_id
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_desired_vibe_ids(self, profile_id: int) -> list[int]:
        stmt = select(ProfileDesiredVibe.vibe_id).where(ProfileDesiredVibe.profile_id == profile_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_desired_vibe_ids(self, profile_id: int, vibe_ids: list[int]) -> None:
        """Full replace: удалить все желаемые вайбы и вставить новые."""
        await self._replace_links(ProfileDesiredVibe, profile_id, vibe_ids, ref_column="vibe_id")

    async def set_vibes_need_review(self, profile_id: int, value: bool) -> None:
        """Устанавливает флаг vibes_need_review для профиля."""
        stmt = update(Profile).where(Profile.id == profile_id).values(vibes_need_review=value)
        await self._session.execute(stmt)
        await self._session.flush()

    async def set_music(self, profile_id: int, file_id: str | None) -> None:
        """Сохраняет или обнуляет music_file_id у профиля."""
        stmt = update(Profile).where(Profile.id == profile_id).values(music_file_id=file_id)
        await self._session.execute(stmt)
        await self._session.flush()
        profile = await self._session.get(Profile, profile_id)
        if profile is not None:
            await self._session.refresh(profile)

    async def set_video_note(self, profile_id: int, file_id: str | None) -> None:
        """Сохраняет или обнуляет video_note_file_id у профиля."""
        stmt = update(Profile).where(Profile.id == profile_id).values(video_note_file_id=file_id)
        await self._session.execute(stmt)
        await self._session.flush()
        profile = await self._session.get(Profile, profile_id)
        if profile is not None:
            await self._session.refresh(profile)
