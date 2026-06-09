"""Seed-скрипт: создаёт 5 тестовых анкет на test-стенде.

Запуск (только на test-сервере, внутри vibe-bot контейнера):
    docker exec vibe-bot python /opt/app/scripts/seed_test_profiles.py

Что делает:
1. Генерирует 5 PIL-картинок (цветной квадрат с инициалом).
2. Шлёт каждую через @Testvibedaiv_bot в MEDIA_STAGING_CHAT_ID — получает
   валидный file_id, привязанный к текущему боту.
3. Создаёт user (если нет) + profile + M2M-связки в БД.

Идемпотентно: если user с telegram_id уже есть — старый профиль удаляется
и создаётся новый. file_ids перезагружаются заново (Telegram их не «помнит»
для нашего бота при повторных запусках, но это безопасно).

Safety net: скрипт падает, если бот не @Testvibedaiv_bot.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys

from aiogram import Bot
from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

EXPECTED_BOT_USERNAME = "Testvibedaiv_bot"

SEEDS: list[dict] = [
    {
        "telegram_id": 900001, "username": "seed_mira", "nickname": "Мира",
        "age": 21, "gender_id": 2, "city": "Москва",
        "bio": "Рисую, смотрю аниме, ищу того, с кем можно вечером бродить и говорить о всякой ерунде.",
        "own_vibe_id": 3, "lf_age_min": 18, "lf_age_max": 30,
        "lf_genders": [1, 3],
        "fandoms": [1, 2, 8], "desired_fandoms": [1, 8], "interests": [1, 10],
        "desired_vibes": [1, 3, 7, 9],
        "color": (255, 130, 180), "label": "M",
    },
    {
        "telegram_id": 900002, "username": "seed_aki", "nickname": "Аки",
        "age": 24, "gender_id": 1, "city": "Москва",
        "bio": "Косплею, играю в JRPG. Ищу спокойную компанию.",
        "own_vibe_id": 7, "lf_age_min": 19, "lf_age_max": 28,
        "lf_genders": [2],
        "fandoms": [1, 8, 13], "desired_fandoms": [1, 8], "interests": [5, 8, 10],
        "desired_vibes": [3, 7, 9],
        "color": (90, 130, 230), "label": "A",
    },
    {
        "telegram_id": 900003, "username": "seed_yume", "nickname": "Юме",
        "age": 19, "gender_id": 2, "city": "Санкт-Петербург",
        "bio": "Учу японский, фанатею от Vocaloid'а. Лучше друзей по душе, чем людей просто рядом.",
        "own_vibe_id": 9, "lf_age_min": 18, "lf_age_max": 25,
        "lf_genders": [1, 2, 3],
        "fandoms": [1, 4, 6], "desired_fandoms": [1, 4, 6], "interests": [4, 10, 15],
        "desired_vibes": [3, 9, 5],
        "color": (180, 220, 255), "label": "Y",
    },
    {
        "telegram_id": 900004, "username": "seed_ren", "nickname": "Рен",
        "age": 26, "gender_id": 3, "city": "Казань",
        "bio": "Пишу музыку и фанфики. Ищу единомышленника — поговорить, поделиться.",
        "own_vibe_id": 6, "lf_age_min": 20, "lf_age_max": 32,
        "lf_genders": [1, 2, 3],
        "fandoms": [2, 5, 7], "desired_fandoms": [2, 7], "interests": [2, 3],
        "desired_vibes": [1, 6, 8],
        "color": (130, 220, 130), "label": "R",
    },
    {
        "telegram_id": 900005, "username": "seed_kira", "nickname": "Кира",
        "age": 22, "gender_id": 2, "city": "Москва",
        "bio": "Animation, motion design, чай с молоком. Ищу того, кто умеет молча сидеть рядом.",
        "own_vibe_id": 11, "lf_age_min": 19, "lf_age_max": 27,
        "lf_genders": [1, 2],
        "fandoms": [1, 9, 10], "desired_fandoms": [9, 10], "interests": [1, 9, 11],
        "desired_vibes": [3, 6, 9, 11],
        "color": (240, 200, 100), "label": "K",
    },
]


def make_image(color: tuple[int, int, int], label: str) -> bytes:
    img = Image.new("RGB", (1080, 1080), color)
    d = ImageDraw.Draw(img)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(path, 600)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), label, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    d.text(
        ((1080 - w) / 2 - bbox[0], (1080 - h) / 2 - bbox[1]),
        label,
        fill=(255, 255, 255),
        font=font,
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


async def upload_to_telegram(bot: Bot, chat_id: int) -> dict[int, str]:
    file_ids: dict[int, str] = {}
    for s in SEEDS:
        photo_bytes = make_image(s["color"], s["label"])
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(photo_bytes, filename=f"{s['username']}.jpg"),
            caption=f"seed: {s['nickname']} ({s['username']})",
        )
        biggest = msg.photo[-1].file_id
        file_ids[s["telegram_id"]] = biggest
        print(f"  uploaded {s['username']}: {biggest[:32]}…")
    return file_ids


async def insert_into_db(file_ids: dict[int, str], database_url: str) -> None:
    engine = create_async_engine(database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        for s in SEEDS:
            file_id = file_ids[s["telegram_id"]]

            result = await session.execute(
                text("SELECT id FROM users WHERE telegram_id = :tg"),
                {"tg": s["telegram_id"]},
            )
            user_id = result.scalar()
            if user_id is None:
                result = await session.execute(
                    text(
                        "INSERT INTO users "
                        "(telegram_id, username, is_banned, is_premium, is_moderator, "
                        " created_at, updated_at) "
                        "VALUES (:tg, :un, false, false, false, now(), now()) "
                        "RETURNING id"
                    ),
                    {"tg": s["telegram_id"], "un": s["username"]},
                )
                user_id = result.scalar()
                print(f"  user created id={user_id} telegram_id={s['telegram_id']}")
            else:
                await session.execute(
                    text("DELETE FROM profiles WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                print(f"  user id={user_id} exists — profile reset")

            result = await session.execute(
                text(
                    "INSERT INTO profiles ("
                    "  user_id, nickname, age, gender_id, "
                    "  looking_for_age_min, looking_for_age_max, "
                    "  bio, city, own_vibe_id, "
                    "  main_media_type, main_media_file_id, "
                    "  is_hidden, is_active, is_completed, "
                    "  is_pending_review, vibes_need_review, "
                    "  created_at, updated_at"
                    ") VALUES ("
                    "  :uid, :nick, :age, :gid, :lf_min, :lf_max, "
                    "  :bio, :city, :vibe, 'photo', :fid, "
                    "  false, true, true, false, false, "
                    "  now(), now()"
                    ") RETURNING id"
                ),
                {
                    "uid": user_id, "nick": s["nickname"], "age": s["age"],
                    "gid": s["gender_id"], "lf_min": s["lf_age_min"],
                    "lf_max": s["lf_age_max"], "bio": s["bio"], "city": s["city"],
                    "vibe": s["own_vibe_id"], "fid": file_id,
                },
            )
            profile_id = result.scalar()

            for gid in s["lf_genders"]:
                await session.execute(
                    text(
                        "INSERT INTO profile_looking_for_genders "
                        "(profile_id, gender_id) VALUES (:p, :g)"
                    ),
                    {"p": profile_id, "g": gid},
                )
            for fid in s["fandoms"]:
                await session.execute(
                    text(
                        "INSERT INTO profile_fandoms (profile_id, fandom_id) "
                        "VALUES (:p, :f)"
                    ),
                    {"p": profile_id, "f": fid},
                )
            for fid in s["desired_fandoms"]:
                await session.execute(
                    text(
                        "INSERT INTO profile_desired_fandoms (profile_id, fandom_id) "
                        "VALUES (:p, :f)"
                    ),
                    {"p": profile_id, "f": fid},
                )
            for iid in s["interests"]:
                await session.execute(
                    text(
                        "INSERT INTO profile_interests (profile_id, interest_id) "
                        "VALUES (:p, :i)"
                    ),
                    {"p": profile_id, "i": iid},
                )
            for vid in s["desired_vibes"]:
                await session.execute(
                    text(
                        "INSERT INTO profile_desired_vibes (profile_id, vibe_id) "
                        "VALUES (:p, :v)"
                    ),
                    {"p": profile_id, "v": vid},
                )

            print(
                f"  profile id={profile_id} {s['nickname']} ({s['city']}) inserted"
            )
        await session.commit()
    await engine.dispose()


async def main() -> None:
    bot_token = os.environ["BOT_TOKEN"]
    staging_chat_id = int(os.environ["MEDIA_STAGING_CHAT_ID"])
    database_url = os.environ["DATABASE_URL"]

    print(f"BOT_TOKEN={bot_token[:14]}…  staging_chat_id={staging_chat_id}")

    bot = Bot(token=bot_token)
    try:
        me = await bot.get_me()
        print(f"bot: @{me.username} (id={me.id})")
        if me.username != EXPECTED_BOT_USERNAME:
            print(
                f"!!! ABORT: this script only runs as @{EXPECTED_BOT_USERNAME}, "
                f"got @{me.username}."
            )
            sys.exit(1)
        file_ids = await upload_to_telegram(bot, staging_chat_id)
        await insert_into_db(file_ids, database_url)
        print(f"\nDone — {len(SEEDS)} test profiles seeded.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
