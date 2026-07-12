"""ВРЕМЕННЫЙ сид для теста авто-рекламы: 30 анкет, совместимых с анкетой Никиты,
+ пара рекламных креативов в пул + ads_rotation_every_n=5.

Запуск ВНУТРИ контейнера бота (есть app + сессия к БД):
    docker exec vibe-bot python /app/scripts/seed_test_candidates.py

Тестовые юзеры — telegram_id 700000001..700000030 (легко удалить потом).
НЕ запускать на проде.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.base import async_session_factory
from app.db.models.ads_rotation import AdRotationPost
from app.db.models.dictionaries import Vibe
from app.db.models.profile import Profile, ProfileLookingForGender
from app.db.models.settings import AppSetting
from app.db.models.user import User

NIKITA_TG = 637931973
TG_BASE = 700000000
N = 30
EVERY_N = "5"


async def main() -> None:
    async with async_session_factory() as s:
        nik = (await s.execute(select(User).where(User.telegram_id == NIKITA_TG))).scalar_one()
        nikp = (await s.execute(select(Profile).where(Profile.user_id == nik.id))).scalar_one()

        my_gender = nikp.gender_id
        their_lfg = (
            (
                await s.execute(
                    select(ProfileLookingForGender.gender_id).where(
                        ProfileLookingForGender.profile_id == nikp.id
                    )
                )
            )
            .scalars()
            .all()
        )
        their_gender = their_lfg[0] if their_lfg else (2 if my_gender == 1 else 1)
        their_age = max(nikp.looking_for_age_min, min(nikp.looking_for_age_max, 20))
        vibe_ids = (await s.execute(select(Vibe.id).order_by(Vibe.id).limit(12))).scalars().all()
        if not vibe_ids:
            raise SystemExit("no vibes in DB")

        created = 0
        for i in range(1, N + 1):
            tg = TG_BASE + i
            exists = (
                await s.execute(select(User.id).where(User.telegram_id == tg))
            ).scalar_one_or_none()
            if exists is not None:
                continue
            u = User(telegram_id=tg, username=f"adtest{i}")
            s.add(u)
            await s.flush()
            p = Profile(
                user_id=u.id,
                nickname=f"Тест {i}",
                age=their_age,
                gender_id=their_gender,
                looking_for_age_min=14,
                looking_for_age_max=99,
                bio="Тестовая анкета для проверки авто-рекламы.",
                city=nikp.city,
                own_vibe_id=vibe_ids[i % len(vibe_ids)],
                main_media_type=nikp.main_media_type,
                main_media_file_id=nikp.main_media_file_id,
                is_active=True,
                is_hidden=False,
                is_completed=True,
                is_pending_review=False,
            )
            s.add(p)
            await s.flush()
            s.add(ProfileLookingForGender(profile_id=p.id, gender_id=my_gender))
            created += 1

        ads_count = (await s.execute(select(func.count(AdRotationPost.id)))).scalar_one()
        if ads_count == 0:
            s.add(
                AdRotationPost(
                    text="🔥 Реклама №1: загляни к нашему спонсору — там кое-что интересное!",
                    button_label="Перейти",
                    button_target="url",
                    button_url="https://example.com",
                )
            )
            s.add(
                AdRotationPost(
                    text=(
                        "✨ Устал от лимитов и рекламы? Оформи Premium — безлимит лайков и тишина!"
                    ),
                    button_label="Купить Premium",
                    button_target="premium",
                )
            )
            s.add(
                AdRotationPost(
                    text="📣 Тестовое объявление без кнопки перехода (только «Не интересно»)."
                )
            )

        await s.execute(
            pg_insert(AppSetting)
            .values(
                key="ads_rotation_every_n", value=EVERY_N, description="тест: показ каждые N анкет"
            )
            .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": EVERY_N})
        )
        await s.commit()

        total_ads = (await s.execute(select(func.count(AdRotationPost.id)))).scalar_one()
        print(
            f"OK: created {created} candidates (tg {TG_BASE + 1}..{TG_BASE + N}), "
            f"ads in pool={total_ads}, ads_rotation_every_n={EVERY_N}"
        )


if __name__ == "__main__":
    asyncio.run(main())
