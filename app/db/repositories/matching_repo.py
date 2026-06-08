from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.matching import (
    Block,
    Dislike,
    Like,
    Match,
    ViewedProfile,
)
from app.db.models.profile import (
    Profile,
    ProfileDesiredFandom,
    ProfileDesiredVibe,
    ProfileFandom,
    ProfileInterest,
    ProfileLookingForGender,
)

if TYPE_CHECKING:
    from app.services.matching_service import CandidateRelations

# Через сколько дней просмотренная анкета может появиться снова — fallback,
# если значение не передано явно из MatchingService (тот читает app_settings).
# Согласован с MatchingService.DEFAULT_VIEW_COOLDOWN_DAYS.
DEFAULT_VIEW_COOLDOWN_DAYS: int = 2


class MatchingRepository:
    """Доступ к таблицам мэтчинга: лайки, дизлайки, мэтчи, просмотры, блокировки."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_like(
        self,
        from_user_id: int,
        to_user_id: int,
        kind: str,
        message: str | None = None,
    ) -> Like:
        like = Like(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            kind=kind,
            message=message,
        )
        self._session.add(like)
        await self._session.flush()
        return like

    async def add_dislike(self, from_user_id: int, to_user_id: int) -> Dislike:
        dislike = Dislike(from_user_id=from_user_id, to_user_id=to_user_id)
        self._session.add(dislike)
        await self._session.flush()
        return dislike

    async def has_reciprocal_like(
        self,
        from_user_id: int,
        to_user_id: int,
    ) -> Like | None:
        """Возвращает лайк, который to_user_id поставил from_user_id (встречный)."""
        stmt = select(Like).where(
            Like.from_user_id == to_user_id,
            Like.to_user_id == from_user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_match(
        self,
        user_a_id: int,
        user_b_id: int,
        initial_message: str | None = None,
    ) -> Match:
        """Создаёт мэтч, гарантируя порядок user_a_id < user_b_id."""
        if user_a_id == user_b_id:
            raise ValueError("Cannot create a match with the same user on both sides")
        a, b = (user_a_id, user_b_id) if user_a_id < user_b_id else (user_b_id, user_a_id)
        match = Match(user_a_id=a, user_b_id=b, initial_message=initial_message)
        self._session.add(match)
        await self._session.flush()
        return match

    async def list_matches_for_user(self, user_id: int) -> list[Match]:
        stmt = (
            select(Match)
            .where(or_(Match.user_a_id == user_id, Match.user_b_id == user_id))
            .order_by(Match.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_incoming_likes(self, user_id: int) -> list[Like]:
        """Входящие лайки, на которые я ещё не ответил:
        нет встречного Like/Dislike от меня к автору лайка, нет Match с ним
        и нет двусторонней блокировки (ни я его, ни он меня)."""
        my_like_subq = select(Like.to_user_id).where(Like.from_user_id == user_id)
        my_dislike_subq = select(Dislike.to_user_id).where(Dislike.from_user_id == user_id)
        match_a_subq = select(Match.user_b_id).where(Match.user_a_id == user_id)
        match_b_subq = select(Match.user_a_id).where(Match.user_b_id == user_id)
        i_blocked_subq = select(Block.blocked_user_id).where(Block.blocker_user_id == user_id)
        blocked_me_subq = select(Block.blocker_user_id).where(Block.blocked_user_id == user_id)

        stmt = (
            select(Like)
            .where(
                Like.to_user_id == user_id,
                Like.from_user_id.notin_(my_like_subq),
                Like.from_user_id.notin_(my_dislike_subq),
                Like.from_user_id.notin_(match_a_subq),
                Like.from_user_id.notin_(match_b_subq),
                Like.from_user_id.notin_(i_blocked_subq),
                Like.from_user_id.notin_(blocked_me_subq),
            )
            .order_by(Like.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_viewed(self, viewer_id: int, target_id: int) -> None:
        """Upsert: если запись была — обновляем viewed_at на now()."""
        stmt = pg_insert(ViewedProfile).values(
            viewer_user_id=viewer_id,
            target_user_id=target_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                ViewedProfile.viewer_user_id,
                ViewedProfile.target_user_id,
            ],
            set_={"viewed_at": func.now()},
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def add_block(self, blocker_id: int, blocked_id: int) -> Block:
        block = Block(blocker_user_id=blocker_id, blocked_user_id=blocked_id)
        self._session.add(block)
        await self._session.flush()
        return block

    async def get_excluded_user_ids(
        self,
        user_id: int,
        *,
        view_cooldown_days: int = DEFAULT_VIEW_COOLDOWN_DAYS,
    ) -> set[int]:
        """Кого нельзя показывать пользователю при выдаче анкет:
        - сам пользователь;
        - кого он лайкнул;
        - кого он дизлайкнул;
        - кого он заблокировал;
        - кто заблокировал его;
        - кого он просматривал за последние `view_cooldown_days` дней.
        """
        excluded: set[int] = {user_id}

        liked_stmt = select(Like.to_user_id).where(Like.from_user_id == user_id)
        excluded.update((await self._session.execute(liked_stmt)).scalars().all())

        disliked_stmt = select(Dislike.to_user_id).where(Dislike.from_user_id == user_id)
        excluded.update((await self._session.execute(disliked_stmt)).scalars().all())

        blocked_by_me_stmt = select(Block.blocked_user_id).where(Block.blocker_user_id == user_id)
        excluded.update((await self._session.execute(blocked_by_me_stmt)).scalars().all())

        blocked_me_stmt = select(Block.blocker_user_id).where(Block.blocked_user_id == user_id)
        excluded.update((await self._session.execute(blocked_me_stmt)).scalars().all())

        cooldown_threshold = func.now() - timedelta(days=view_cooldown_days)
        viewed_stmt = select(ViewedProfile.target_user_id).where(
            and_(
                ViewedProfile.viewer_user_id == user_id,
                ViewedProfile.viewed_at >= cooldown_threshold,
            )
        )
        excluded.update((await self._session.execute(viewed_stmt)).scalars().all())

        return excluded

    async def find_candidates(
        self,
        *,
        my_profile: Profile,
        my_looking_for_gender_ids: list[int],
        excluded_user_ids: set[int],
        limit: int = 200,
        desired_vibe_ids: frozenset[int] | None = None,
        city_filter: list[str] | None = None,
        desired_fandom_ids: frozenset[int] | None = None,
    ) -> list[Profile]:
        """Жёсткие фильтры мэтчинга. Скоринг — на стороне сервиса.

        Условия:
        * Анкета активна, не скрыта, заполнена, не «на проверке» (NSFW manual review).
        * `Profile.user_id` не входит в `excluded_user_ids` (включая нас самих).
        * Совместимость по полу: мой пол ∈ `their.looking_for_genders` И
          её/его пол ∈ моих `looking_for_genders` (передаются как параметр).
        * Возраст: обе стороны попадают друг к другу в диапазон.
        * `desired_vibe_ids` (optional): кандидат's `own_vibe_id` должен входить
          в набор желаемых вайбов. Пустой frozenset или None означают «любой вайб»
          — фильтр по вайбу не применяется.
        * `city_filter` (optional): кандидат's `city` должен входить в список.
          Если None — фильтр по городу не применяется (глобальная выдача).
        * `desired_fandom_ids` (optional): набор моих _желаемых_ фандомов
          (источник — `ProfileDesiredFandom` вызывающего). Хотя бы один из
          фандомов КАНДИДАТА (из `ProfileFandom`) должен входить в этот набор —
          то есть совпадение «их фандом ∈ мои желаемые». Пустой frozenset
          или None означают «фильтр не применяется». Используется в Stage 2/3
          каскада: когда выходим за пределы города, оставляем только тех,
          у кого совпадает хоть один фандом из моих desired.
        """
        # Подзапрос: профили, у которых мой пол стоит в desired-полях.
        subq_their_lfg = select(ProfileLookingForGender.profile_id).where(
            ProfileLookingForGender.gender_id == my_profile.gender_id
        )

        conditions = [
            Profile.is_active.is_(True),
            Profile.is_hidden.is_(False),
            Profile.is_completed.is_(True),
            Profile.is_pending_review.is_(False),
            Profile.gender_id.in_(my_looking_for_gender_ids),
            Profile.id.in_(subq_their_lfg),
            # Мой возраст попадает в их диапазон.
            Profile.looking_for_age_min <= my_profile.age,
            Profile.looking_for_age_max >= my_profile.age,
            # Их возраст попадает в мой диапазон.
            Profile.age >= my_profile.looking_for_age_min,
            Profile.age <= my_profile.looking_for_age_max,
        ]
        if excluded_user_ids:
            conditions.append(Profile.user_id.notin_(excluded_user_ids))

        # Hard vibe filter: применяется только когда searcher указал хотя бы один вайб.
        # Пустой set или None → «любой вайб» → фильтр НЕ добавляется.
        if desired_vibe_ids:
            conditions.append(Profile.own_vibe_id.in_(desired_vibe_ids))

        # City filter: применяется только когда передан непустой список городов.
        if city_filter:
            conditions.append(Profile.city.in_(city_filter))

        # Квалифицированный fallback по фандомам: при выходе за свой город
        # (Stage 2/3 каскада) оставляем только тех, у кого хотя бы один из
        # фандомов входит в мои desired_fandom_ids. Пустой/None — фильтр не
        # применяется.
        if desired_fandom_ids:
            subq_their_fandoms = select(ProfileFandom.profile_id).where(
                ProfileFandom.fandom_id.in_(desired_fandom_ids)
            )
            conditions.append(Profile.id.in_(subq_their_fandoms))

        stmt = select(Profile).where(*conditions).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def load_candidates_with_relations(
        self, profile_ids: list[int]
    ) -> dict[int, CandidateRelations]:
        """Возвращает {profile_id: CandidateRelations} четырьмя SELECT'ами вместо
        N+1 (по 4 запроса на каждого кандидата).

        Используется в скоринге мэтчинга. Тип возвращаемого dict-значения
        совпадает с `app.services.matching_service.CandidateRelations`.
        """
        # Импорт внутри функции, чтобы избежать циклической зависимости
        # repo -> service -> repo при импорте модуля.
        from app.services.matching_service import CandidateRelations

        if not profile_ids:
            return {}

        fandom_map: dict[int, set[int]] = {pid: set() for pid in profile_ids}
        desired_map: dict[int, set[int]] = {pid: set() for pid in profile_ids}
        interest_map: dict[int, set[int]] = {pid: set() for pid in profile_ids}
        desired_vibe_map: dict[int, set[int]] = {pid: set() for pid in profile_ids}

        rows_f = await self._session.execute(
            select(ProfileFandom.profile_id, ProfileFandom.fandom_id).where(
                ProfileFandom.profile_id.in_(profile_ids)
            )
        )
        for profile_id, fandom_id in rows_f.all():
            fandom_map[profile_id].add(fandom_id)

        rows_d = await self._session.execute(
            select(ProfileDesiredFandom.profile_id, ProfileDesiredFandom.fandom_id).where(
                ProfileDesiredFandom.profile_id.in_(profile_ids)
            )
        )
        for profile_id, fandom_id in rows_d.all():
            desired_map[profile_id].add(fandom_id)

        rows_i = await self._session.execute(
            select(ProfileInterest.profile_id, ProfileInterest.interest_id).where(
                ProfileInterest.profile_id.in_(profile_ids)
            )
        )
        for profile_id, interest_id in rows_i.all():
            interest_map[profile_id].add(interest_id)

        rows_v = await self._session.execute(
            select(ProfileDesiredVibe.profile_id, ProfileDesiredVibe.vibe_id).where(
                ProfileDesiredVibe.profile_id.in_(profile_ids)
            )
        )
        for profile_id, vibe_id in rows_v.all():
            desired_vibe_map[profile_id].add(vibe_id)

        return {
            pid: CandidateRelations(
                fandom_ids=frozenset(fandom_map[pid]),
                desired_fandom_ids=frozenset(desired_map[pid]),
                interest_ids=frozenset(interest_map[pid]),
                desired_vibe_ids=frozenset(desired_vibe_map[pid]),
            )
            for pid in profile_ids
        }

    async def delete_user_social_data(self, user_id: int) -> None:
        """Удаляет все Like/Dislike/Match/Block/ViewedProfile, где user — участник.

        Используется в GDPR-удалении профиля (этап 3.4). Связные данные сносятся
        физически, чтобы не вечно тащить лайки от/к удалённой анкете.
        """
        await self._session.execute(
            delete(Like).where(or_(Like.from_user_id == user_id, Like.to_user_id == user_id))
        )
        await self._session.execute(
            delete(Dislike).where(
                or_(Dislike.from_user_id == user_id, Dislike.to_user_id == user_id)
            )
        )
        await self._session.execute(
            delete(Match).where(or_(Match.user_a_id == user_id, Match.user_b_id == user_id))
        )
        await self._session.execute(
            delete(Block).where(
                or_(Block.blocker_user_id == user_id, Block.blocked_user_id == user_id)
            )
        )
        await self._session.execute(
            delete(ViewedProfile).where(
                or_(
                    ViewedProfile.viewer_user_id == user_id,
                    ViewedProfile.target_user_id == user_id,
                )
            )
        )
        await self._session.flush()
