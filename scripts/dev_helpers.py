"""Dev-хелперы для ручного тестирования матчинга и уведомлений.

НЕ используется в проде. Создаёт фейковых пользователей с компатибельными
анкетами, чтобы можно было тестировать поиск/лайки/мэтчи без второго
Telegram-аккаунта.

Запуск:
    DATABASE_URL=... uv run python -m scripts.dev_helpers create-test-user \\
        --gender female --looking-for male,female --age 24

    DATABASE_URL=... uv run python -m scripts.dev_helpers fake-like \\
        --from-tg 999000001 --to-tg <твой_telegram_id> [--superlike "hi!"]

    DATABASE_URL=... uv run python -m scripts.dev_helpers list-users
    DATABASE_URL=... uv run python -m scripts.dev_helpers wipe-fake

    DATABASE_URL=... uv run python scripts/dev_helpers.py seed-creator-posts
    DATABASE_URL=... uv run python scripts/dev_helpers.py list-creator-posts
    DATABASE_URL=... uv run python scripts/dev_helpers.py wipe-creator-posts
"""

from __future__ import annotations

import argparse
import asyncio
import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import delete, func, select, update

from app.config import settings
from app.db.base import async_session_factory
from app.db.models.creators import CreatorPost, CreatorPostPhoto
from app.db.models.dictionaries import CreatorCategory, Fandom, Gender, Interest, Vibe
from app.db.models.feed import FeedPost, FeedPostMedia
from app.db.models.profile import (
    Profile,
    ProfileDesiredFandom,
    ProfileFandom,
    ProfileInterest,
    ProfileLookingForGender,
)
from app.db.models.user import User
from app.db.repositories.creator_repo import CreatorRepository
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.feed_repo import FeedRepository
from app.db.repositories.matching_repo import MatchingRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.db.repositories.settings_repo import SettingsRepository
from app.db.repositories.user_repo import UserRepository
from app.services.matching_service import MatchingService

# Фейковые tg_id: всё что выше 999_000_000 — наши тестовые юзеры.
FAKE_TG_BASE = 999_000_000

DEFAULT_NICKNAMES = [
    "Tsuki",
    "Aki",
    "Ryo",
    "Yuki",
    "Sora",
    "Hana",
    "Kai",
    "Ren",
    "Mei",
    "Nao",
]
DEFAULT_BIOS = [
    "Рисую, слушаю synthwave, ищу своих по вайбу.",
    "Аниме + книги. Открыта/открыт к новым знакомствам.",
    "Делаю music + digital art. Найди меня по совместимым фандомам.",
    "Cosplay, J-rock, indie games. Дружим, если совпадаем!",
]
DEFAULT_MEDIA_FILE_ID = "AgACAgIAAxkBAAIB"  # placeholder — Telegram отклонит,
# но для теста алгоритма мэтчинга достаточно. При отправке карточки бот
# поймает TelegramBadRequest и пошлёт текст без фото.


async def _get_or_create_user(session, telegram_id: int, username: str) -> User:
    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.flush()
    return user


async def _next_fake_tg(session) -> int:
    """Следующий свободный fake tg_id выше FAKE_TG_BASE."""
    max_tg = (
        (
            await session.execute(
                select(User.telegram_id)
                .where(User.telegram_id >= FAKE_TG_BASE)
                .order_by(User.telegram_id.desc())
            )
        )
        .scalars()
        .first()
    )
    return (max_tg or FAKE_TG_BASE) + 1


async def cmd_create_test_user(args) -> None:
    """Создаёт фейкового юзера с полной анкетой."""
    async with async_session_factory() as session:
        # Resolve справочники по code.
        genders = {g.code: g for g in (await session.execute(select(Gender))).scalars().all()}
        vibes = list((await session.execute(select(Vibe).order_by(Vibe.number))).scalars())
        fandoms = list((await session.execute(select(Fandom).order_by(Fandom.id))).scalars())
        interests = list((await session.execute(select(Interest).order_by(Interest.id))).scalars())

        if args.gender not in genders:
            print(f"Unknown gender '{args.gender}'. Available: {list(genders)}")
            return
        gender = genders[args.gender]
        lfg_codes = [c.strip() for c in args.looking_for.split(",") if c.strip()]
        lfg = [genders[c] for c in lfg_codes if c in genders]
        if not lfg:
            print("looking-for must contain at least one valid gender code.")
            return

        tg_id = args.telegram_id or await _next_fake_tg(session)
        nickname = args.nickname or random.choice(DEFAULT_NICKNAMES)
        bio = args.bio or random.choice(DEFAULT_BIOS)

        user = await _get_or_create_user(session, tg_id, username=f"test_{tg_id}")

        # Удалить старую анкету, если была.
        await session.execute(delete(Profile).where(Profile.user_id == user.id))
        await session.flush()

        own_vibe = vibes[args.own_vibe_number - 1] if args.own_vibe_number else random.choice(vibes)
        desired_vibe = (
            vibes[args.desired_vibe_number - 1]
            if args.desired_vibe_number
            else random.choice(vibes)
        )

        profile = Profile(
            user_id=user.id,
            nickname=nickname,
            age=args.age,
            gender_id=gender.id,
            looking_for_age_min=args.la_min,
            looking_for_age_max=args.la_max,
            bio=bio,
            city="Москва",  # все тестовые анкеты — в Москве, чтобы городской фильтр их находил
            own_vibe_id=own_vibe.id,
            desired_vibe_id=desired_vibe.id,
            main_media_type="photo",
            main_media_file_id=DEFAULT_MEDIA_FILE_ID,
            is_completed=True,
        )
        session.add(profile)
        await session.flush()

        # M2M: фандомы (3 случайных), интересы (3), looking_for_genders (из args).
        picked_fandoms = random.sample(fandoms, k=min(3, len(fandoms)))
        for f in picked_fandoms:
            session.add(ProfileFandom(profile_id=profile.id, fandom_id=f.id))
        picked_desired = random.sample(fandoms, k=min(3, len(fandoms)))
        for f in picked_desired:
            session.add(ProfileDesiredFandom(profile_id=profile.id, fandom_id=f.id))
        picked_interests = random.sample(interests, k=min(3, len(interests)))
        for i in picked_interests:
            session.add(ProfileInterest(profile_id=profile.id, interest_id=i.id))
        for g in lfg:
            session.add(ProfileLookingForGender(profile_id=profile.id, gender_id=g.id))

        await session.commit()
        print(
            f"OK: fake user created. telegram_id={tg_id} user_id={user.id} "
            f"nickname={nickname!r} gender={gender.code} age={args.age} "
            f"looking_for={[g.code for g in lfg]} own_vibe={own_vibe.code} "
            f"desired_vibe={desired_vibe.code}"
        )


async def cmd_fake_like(args) -> None:
    """От лица фейкового юзера ставит лайк через matching_service.process_like.

    Если получается reciprocal-мэтч — отправляет уведомление РЕАЛЬНОМУ пользователю
    через bot.send_message (Aika и прочие фейки не существуют в Telegram, им
    уведомление не пошлёшь, но это и не нужно — мы тестируем UX реального юзера).
    """
    async with async_session_factory() as session:
        from_user = (
            await session.execute(select(User).where(User.telegram_id == args.from_tg))
        ).scalar_one_or_none()
        to_user = (
            await session.execute(select(User).where(User.telegram_id == args.to_tg))
        ).scalar_one_or_none()
        if from_user is None:
            print(f"User with telegram_id={args.from_tg} not found.")
            return
        if to_user is None:
            print(f"User with telegram_id={args.to_tg} not found.")
            return

        service = MatchingService(
            profile_repo=ProfileRepository(session),
            matching_repo=MatchingRepository(session),
            settings_repo=SettingsRepository(session),
            dictionary_repo=DictionaryRepository(session),
            user_repo=UserRepository(session),
            session=session,
        )
        outcome = await service.process_like(
            from_user_id=from_user.id,
            to_user_id=to_user.id,
            kind="superlike" if args.superlike else "like",
            message=args.superlike,
        )
        await session.commit()
        print(
            f"like_recorded={outcome.like_recorded} match_created={outcome.match_created} "
            f"match_id={outcome.match_id} initial_message={outcome.initial_message!r}"
        )
        if not outcome.match_created:
            return

        # Match создан — шлём уведомление реальному пользователю (to_user).
        # Фейку (from_user) уведомление не нужно — его не существует в Telegram.
        from_profile = await ProfileRepository(session).get_by_user_id(from_user.id)
        if from_profile is None:
            print("Match created, но у инициатора нет профиля — нечего рендерить.")
            return

        nickname = from_profile.nickname
        if outcome.initial_message:
            text = f"У вас мэтч с {nickname}!\n\nСообщение: {outcome.initial_message}"
        else:
            text = f"У вас мэтч с {nickname}!"

        # Кнопка «Открыть профиль» — t.me/username или tg://user?id (для фейка
        # резолва не будет, но протестируем рендер кнопки).
        if from_user.username:
            url = f"https://t.me/{from_user.username}"
        else:
            url = f"tg://user?id={from_user.telegram_id}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть профиль", url=url)]]
        )

        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await bot.send_message(chat_id=to_user.telegram_id, text=text, reply_markup=kb)
            print(f"Notification sent to telegram_id={to_user.telegram_id}.")
        finally:
            await bot.session.close()


async def cmd_list_users(args) -> None:
    async with async_session_factory() as session:
        users = (await session.execute(select(User).order_by(User.telegram_id))).scalars().all()
        for u in users:
            tag = "FAKE" if u.telegram_id >= FAKE_TG_BASE else "REAL"
            print(
                f"[{tag}] id={u.id} tg={u.telegram_id} username={u.username} "
                f"banned={u.is_banned} premium={u.is_premium}"
            )


async def cmd_wipe_fake(args) -> None:
    """Удаляет всех фейковых юзеров (tg_id >= FAKE_TG_BASE) и их анкеты."""
    async with async_session_factory() as session:
        # CASCADE на User.id уберёт всё связное.
        result = await session.execute(delete(User).where(User.telegram_id >= FAKE_TG_BASE))
        await session.commit()
        print(f"Removed {result.rowcount} fake users.")


# ---------------------------------------------------------------------------
# Seed data for «Аллея креаторов» demo
# ---------------------------------------------------------------------------

# category_code -> list of (author_display_name, description, tg_link_suffix,
#                            is_premium, photo_count, published_days_ago)
SEED_POSTS: list[tuple[str, str, str, str, bool, int, int]] = [
    (
        "artists",
        "Аки иллюстрирует",
        (
            "Привет! Я Аки — цифровой иллюстратор, влюблённый в аниме-эстетику и пастельные"
            " палитры. Рисую фан-арты по популярным тайтлам, персонажей на заказ и личные"
            " арт-проекты. В канале — процессы, скетчи, туториалы по Clip Studio Paint и"
            " немного закулисья творческой жизни. Буду рада новым подписчикам и коллегам по цеху!"
        ),
        "aki_illustrates",
        False,
        2,
        6,
    ),
    (
        "artists",
        "Манга Лаб",
        (
            "Манга Лаб — студия, где мы пишем и рисуем оригинальную мангу на русском языке."
            " Сейчас в работе три тайтла: романтическая школьная история, тёмное фэнтези и"
            " комедийный слайс-оф-лайф. Выкладываем главы по расписанию каждую пятницу."
            " Здесь же — концепт-арты, ранние черновики и голосования за сюжетные повороты."
        ),
        "manga_lab_ru",
        True,
        3,
        5,
    ),
    (
        "musicians",
        "Звуки Аниме",
        (
            "Канал Звуки Аниме — это каверы на опенинги и эндинги любимых сериалов, аранжировки"
            " для фортепиано и электрогитары, а иногда полностью оригинальные треки в"
            " аниме-стиле. Работаю в FL Studio, делюсь процессом создания музыки и иногда"
            " провожу лайвы, где разбираю чужие биты. Подпишись — вместе исследуем саундтрек"
            " нашей жизни."
        ),
        "anime_sounds_ch",
        False,
        1,
        4,
    ),
    (
        "musicians",
        "Рейко Синти",
        (
            "Vocaloid-продюсер и синти-поп композитор. Создаю музыку на стыке J-pop и"
            " электроники, вдохновляясь Hatsune Miku, DECO*27 и Kenshi Yonezu. В канале"
            " выхожу с новыми треками, WIP-клипами и разборами того, как устроены мои"
            " любимые вокалоидные биты. Для коллабов — всегда открыт, пишите в лс!"
        ),
        "reiko_synth",
        True,
        2,
        3,
    ),
    (
        "writers",
        "Лайт-новеллы от Юко",
        (
            "Юко пишет лайт-новеллы в жанрах исекай, романтика и мистика. Публикую главы"
            " бесплатно, обновления два раза в неделю. Все истории оригинальные — никакого"
            " фанфика. Очень люблю проработанных персонажей и атмосферные описания."
            " Если ищешь что почитать между сезонами аниме — загляни, не пожалеешь."
        ),
        "yuko_light_novels",
        False,
        1,
        2,
    ),
    (
        "writers",
        "Фанфик Дом",
        (
            "Фанфик Дом — уютное место для авторов и читателей фанфиков по аниме и манге."
            " Публикую собственные работы по Jujutsu Kaisen, Attack on Titan и Hunter x Hunter,"
            " а также собираю подборки лучших фиков от русскоязычных авторов. Есть рубрика"
            " «Советы начинающим» — разбираю типичные ошибки и делюсь техниками нарратива."
        ),
        "fanfic_dom",
        False,
        2,
        1,
    ),
    (
        "cosplayers",
        "Косплей Дом",
        (
            "Косплей Дом — здесь живёт моя страсть к перевоплощениям! Шью костюмы самостоятельно"
            " от эскиза до финального образа. В портфолио — более 30 персонажей из аниме, манги"
            " и игр. Делюсь мастер-классами по изготовлению брони из EVA-foam, работе с термо-"
            "пластиком и созданию реалистичного грима. Участвую в фест-конкурсах по всей стране."
        ),
        "cosplay_dom",
        True,
        3,
        7,
    ),
    (
        "streamers",
        "Сёма Анимешник",
        (
            "Сёма стримит аниме-марафоны, JRPG и визуальные новеллы каждые выходные."
            " Атмосфера на стриме — уютная, без токсика. Обсуждаем сюжеты, теории,"
            " сравниваем аниме и мангу. Иногда устраиваем совместные просмотры с"
            " подписчиками через watch-party. Подпишись и приходи — у нас всегда весело!"
        ),
        "syoma_animeboy",
        False,
        1,
        3,
    ),
    (
        "streamers",
        "ВайбКаст",
        (
            "ВайбКаст — подкаст и стрим-канал об аниме-культуре, манге и творческих"
            " профессиях. Приглашаем художников, косплееров, музыкантов — разговариваем"
            " об их пути, вдохновении и провалах. Раз в неделю — новый эпизод на YouTube"
            " и Telegram. Идеально для фонового прослушивания во время рисования или шитья."
        ),
        "vibecast_pod",
        False,
        2,
        0,
    ),
]

# Display names used by seed — needed for idempotency check and wipe.
SEED_DISPLAY_NAMES = [row[1] for row in SEED_POSTS]


async def cmd_seed_creator_posts(args) -> None:
    """Сидит 9 демо-постов в БД для Аллеи креаторов."""
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(days=30)

    async with async_session_factory() as session:
        # Resolve category codes -> ids once.
        categories: dict[str, int] = {
            row.code: row.id
            for row in (await session.execute(select(CreatorCategory))).scalars().all()
        }
        if not categories:
            print("ERROR: creator_categories table is empty. Run alembic upgrade head first.")
            return

        repo = CreatorRepository(session)
        created = 0
        skipped = 0

        for (
            cat_code,
            display_name,
            description,
            tg_suffix,
            is_premium,
            photo_count,
            days_ago,
        ) in SEED_POSTS:
            # Idempotency: skip if post with this display_name already exists.
            existing = (
                await session.execute(
                    select(CreatorPost).where(CreatorPost.author_display_name == display_name)
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(f"  SKIP (exists): {display_name!r}")
                skipped += 1
                continue

            category_id = categories.get(cat_code)
            if category_id is None:
                print(f"  SKIP (unknown category {cat_code!r}): {display_name!r}")
                skipped += 1
                continue

            # Spread published_at across the last 7 days.
            published_at = now - timedelta(days=days_ago, hours=random.randint(0, 6))

            post = await repo.create_post(
                author_user_id=None,
                author_display_name=display_name,
                category_id=category_id,
                description=description,
                telegram_link=f"https://t.me/{tg_suffix}",
                is_premium_post=is_premium,
                is_published=True,
                is_pending_review=False,
                published_at=published_at,
                expires_at=expires_at,
            )

            for pos in range(photo_count):
                placeholder = f"PLACEHOLDER_PHOTO_{created * 3 + pos + 1}"
                await repo.add_photo(post_id=post.id, file_id=placeholder, position=pos)

            print(
                f"  CREATED: id={post.id} {display_name!r} cat={cat_code}"
                f" premium={is_premium} photos={photo_count}"
            )
            created += 1

        await session.commit()
        print(f"\nDone: {created} created, {skipped} skipped.")


async def cmd_wipe_creator_posts(args) -> None:
    """Удаляет все посты, посеянные seed-creator-posts (по display_name)."""
    async with async_session_factory() as session:
        result = await session.execute(
            delete(CreatorPost).where(CreatorPost.author_display_name.in_(SEED_DISPLAY_NAMES))
        )
        await session.commit()
        print(f"Removed {result.rowcount} seeded creator post(s).")


async def cmd_list_creator_posts(args) -> None:
    """Выводит все посты из creator_posts с числом фотографий."""
    async with async_session_factory() as session:
        # Count photos per post in a single query.
        photo_counts: dict[int, int] = {
            row.post_id: row.cnt
            for row in (
                await session.execute(
                    select(
                        CreatorPostPhoto.post_id,
                        func.count(CreatorPostPhoto.id).label("cnt"),
                    ).group_by(CreatorPostPhoto.post_id)
                )
            ).all()
        }

        posts = list(
            (await session.execute(select(CreatorPost).order_by(CreatorPost.id))).scalars().all()
        )

        if not posts:
            print("No creator posts in the database.")
            return

        # Resolve category ids -> codes.
        categories: dict[int, str] = {
            row.id: row.code
            for row in (await session.execute(select(CreatorCategory))).scalars().all()
        }

        col_id = f"{'id':>4}"
        col_name = f"{'author_display_name':<28}"
        col_cat = f"{'category':<12}"
        col_pub = f"{'pub':>3}"
        col_prem = f"{'premium':>7}"
        col_ph = f"{'photos':>6}"
        header = f"{col_id}  {col_name}  {col_cat}  {col_pub}  {col_prem}  {col_ph}  expires_at"
        print(header)
        print("-" * len(header))
        for post in posts:
            cat_code = categories.get(post.category_id, "?")
            cnt = photo_counts.get(post.id, 0)
            expires = post.expires_at.strftime("%Y-%m-%d") if post.expires_at else "none"
            print(
                f"{post.id:>4}  {post.author_display_name:<28}  {cat_code:<12}  "
                f"{'yes' if post.is_published else 'no':>3}  "
                f"{'yes' if post.is_premium_post else 'no':>7}  "
                f"{cnt:>6}  {expires}"
            )
        print(f"\nTotal: {len(posts)} post(s).")


# ---------------------------------------------------------------------------
# Seed data for «Лента» demo
# ---------------------------------------------------------------------------

SEED_FEED_POSTS: list[tuple[str, str, int, int]] = [
    (
        "Цукимару",
        (
            "Привет, лента! Я наконец-то дорисовал серию фан-артов по Chainsaw Man — "
            "целых пять страниц в чернильной технике. Мотивировался паузой между "
            "арками манги. Если вы тоже ждёте продолжения и скучаете — загляните, "
            "буду рад обратной связи! Рисую в основном по тёмным тайтлам, иногда "
            "выхожу в сёнэн-комедии. Всем добра и хорошего вайба."
        ),
        1,  # photo count
        3,  # hours ago
    ),
    (
        "Аки_Нодзоми",
        (
            "Сегодня записала кавер на опенинг Spy x Family — первый вокальный трек, "
            "который я решилась выложить публично. Долго откладывала из-за мандража, "
            "но подруга убедила. Аранжировка своя, акустическая гитара + немного синтезатора. "
            "Буду рада услышать, как вам! Слушаю любой жанр, но душой — в аниме-саундтреках "
            "и lo-fi. Давайте дружить по музыкальному вайбу."
        ),
        0,  # no photos
        7,
    ),
    (
        "RenStudio",
        (
            "Выложил первые три главы оригинальной манги «Соль и Сталь» — постапокалипсис "
            "с элементами меха и романтики. Рисую уже полтора года, наконец решился показать "
            "публике. Глава выходит раз в две недели. Если вам близка атмосфера тёмного "
            "будущего, одиночества и надежды — возможно, мы на одной волне. Очень жду реакций!"
        ),
        2,  # photos
        12,
    ),
    (
        "Хана_косплей",
        (
            "Закончила костюм Фриерен из «Магии на закате»! Плащ сшила сама из шерстяного "
            "драпа, уши — из термопластика, парик — заказной. Ушло около трёх недель. "
            "Очень люблю этот тайтл за атмосферу грусти и нежности одновременно. "
            "Планирую следующим делать Химэль — кто тоже фанат, пишите, может, устроим "
            "совместную съёмку на каком-нибудь фесте."
        ),
        0,  # no photos
        1,
    ),
]

SEED_FEED_AUTHOR_NAMES = [row[0] for row in SEED_FEED_POSTS]


async def cmd_seed_feed_posts(args) -> None:
    """Сидит 4 демо-поста в БД для Ленты."""
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(hours=48)

    async with async_session_factory() as session:
        repo = FeedRepository(session)
        created = 0
        skipped = 0

        for idx, (author_name, text, photo_count, hours_ago) in enumerate(SEED_FEED_POSTS):
            # Idempotency: skip if post with this author_name already exists.
            existing = (
                await session.execute(select(FeedPost).where(FeedPost.author_name == author_name))
            ).scalar_one_or_none()
            if existing is not None:
                print(f"  SKIP (exists): {author_name!r}")
                skipped += 1
                continue

            published_at = now - timedelta(hours=hours_ago)

            post = await repo.create_post(
                author_user_id=None,
                author_name=author_name,
                text=text,
                status="active",
                published_at=published_at,
                expires_at=expires_at,
            )

            for pos in range(photo_count):
                placeholder = f"PLACEHOLDER_FEED_{idx + 1}_{pos + 1}"
                await repo.add_photo(post_id=post.id, file_id=placeholder, position=pos)

            print(
                f"  CREATED: id={post.id} {author_name!r} photos={photo_count}"
                f" published={published_at.strftime('%H:%M')} ago={hours_ago}h"
            )
            created += 1

        await session.commit()
        print(f"\nDone: {created} created, {skipped} skipped.")


async def cmd_seed_media(args) -> None:
    """Заменяет плейсхолдер-file_id в постах Аллеи и Ленты на реальные картинки.

    Telegram `send_photo` принимает прямой URL — Telegram сам скачивает файл и
    отдаёт `file_id`. Берём картинки с picsum.photos (детерминированный seed),
    отправляем их в чат админа, забираем `file_id` и прописываем в БД.
    """
    admin_ids = settings.admin_telegram_ids
    if not admin_ids:
        print("ERROR: ADMIN_TELEGRAM_IDS пуст — некуда отправлять картинки.")
        return
    chat_id = admin_ids[0]

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    updated = 0
    try:
        async with async_session_factory() as session:
            creator_photos = list(
                (
                    await session.execute(
                        select(CreatorPostPhoto).where(
                            CreatorPostPhoto.file_id.like("PLACEHOLDER%")
                        )
                    )
                )
                .scalars()
                .all()
            )
            feed_media = list(
                (
                    await session.execute(
                        select(FeedPostMedia).where(FeedPostMedia.file_id.like("PLACEHOLDER%"))
                    )
                )
                .scalars()
                .all()
            )

            targets: list[tuple[str, int, str]] = [
                *[("creator", p.id, f"creator-{p.id}") for p in creator_photos],
                *[("feed", m.id, f"feed-{m.id}") for m in feed_media],
            ]
            print(f"Нашёл плейсхолдеров: {len(targets)} (Аллея + Лента).")

            for kind, row_id, seed in targets:
                url = f"https://picsum.photos/seed/{seed}/800/600"
                try:
                    msg = await bot.send_photo(chat_id=chat_id, photo=url)
                except Exception as exc:  # dev-скрипт: одна ошибка не валит весь прогон
                    print(f"  SKIP {kind}#{row_id}: send_photo упал ({exc})")
                    continue
                if not msg.photo:
                    print(f"  SKIP {kind}#{row_id}: ответ без photo")
                    continue
                file_id = msg.photo[-1].file_id
                model = CreatorPostPhoto if kind == "creator" else FeedPostMedia
                await session.execute(
                    update(model).where(model.id == row_id).values(file_id=file_id)
                )
                updated += 1
                print(f"  OK {kind}#{row_id} → file_id={file_id[:16]}…")
                await asyncio.sleep(0.4)  # не упираться в flood-лимит

            await session.commit()
    finally:
        await bot.session.close()

    print(f"\nDone: обновлено {updated} картинок.")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dev helpers for manual matching tests.")
    sub = p.add_subparsers(dest="command", required=True)

    ctu = sub.add_parser("create-test-user", help="Create a fake user with a profile.")
    ctu.add_argument(
        "--telegram-id", type=int, default=None, help="explicit tg_id; auto if omitted"
    )
    ctu.add_argument("--nickname", default=None)
    ctu.add_argument("--bio", default=None)
    ctu.add_argument("--age", type=int, default=24)
    ctu.add_argument("--la-min", dest="la_min", type=int, default=18)
    ctu.add_argument("--la-max", dest="la_max", type=int, default=40)
    ctu.add_argument("--gender", required=True, choices=["male", "female", "other"])
    ctu.add_argument(
        "--looking-for",
        required=True,
        help="comma-separated gender codes: male,female,other",
    )
    ctu.add_argument("--own-vibe-number", type=int, default=None, help="1..9")
    ctu.add_argument("--desired-vibe-number", type=int, default=None)

    fl = sub.add_parser("fake-like", help="Fake user likes a real user.")
    fl.add_argument("--from-tg", type=int, required=True)
    fl.add_argument("--to-tg", type=int, required=True)
    fl.add_argument("--superlike", default=None, help="text of superlike (otherwise plain like)")

    sub.add_parser("list-users", help="List all users.")
    sub.add_parser("wipe-fake", help="Delete all fake users (tg_id >= 999000000).")

    sub.add_parser("seed-creator-posts", help="Seed 9 demo creator posts (idempotent).")
    sub.add_parser("wipe-creator-posts", help="Delete all seeded creator posts by display name.")
    sub.add_parser("list-creator-posts", help="List all creator posts with photo counts.")

    sub.add_parser("seed-feed-posts", help="Seed 4 demo feed posts (idempotent).")

    sub.add_parser(
        "seed-media",
        help="Replace PLACEHOLDER file_ids in Alley/Feed posts with real picsum images.",
    )

    return p


async def _main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    handlers = {
        "create-test-user": cmd_create_test_user,
        "fake-like": cmd_fake_like,
        "list-users": cmd_list_users,
        "wipe-fake": cmd_wipe_fake,
        "seed-creator-posts": cmd_seed_creator_posts,
        "wipe-creator-posts": cmd_wipe_creator_posts,
        "list-creator-posts": cmd_list_creator_posts,
        "seed-feed-posts": cmd_seed_feed_posts,
        "seed-media": cmd_seed_media,
    }
    await handlers[args.command](args)


if __name__ == "__main__":
    asyncio.run(_main())
