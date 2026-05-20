"""Рендер карточки анкеты (текст + meta медиа).

Утилита принимает все справочные сущности явно — её можно тестировать без БД.
SQL-запросы делает хэндлер через репозитории.

После отправки текстовой карточки хэндлер вызывает `send_premium_media`,
которая при наличии file_id отправляет аудио и/или кружок отдельными сообщениями.
TelegramAPIError при отправке (протухший file_id и т.п.) — лог + обнуление поля в БД.

 (тонкие хэндлеры) и §4 (тексты только из app/texts).
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dictionaries import Fandom, Gender, Interest, Vibe
from app.db.models.profile import Profile
from app.db.repositories.dictionary_repo import DictionaryRepository
from app.db.repositories.profile_repo import ProfileRepository
from app.texts import registration as texts


@dataclass(frozen=True, slots=True)
class RenderedProfile:
    """Готовая к отправке карточка анкеты.

    Поле `text` — caption либо тело сообщения; `media_type`/`media_file_id` —
    то, как именно отправлять медиа (`send_photo` / `send_video` / `send_animation`).
    """

    text: str
    media_type: str  # 'photo' | 'video' | 'gif'
    media_file_id: str


# Telegram ограничивает caption медиа-сообщения 1024 символами.
CAPTION_LIMIT = 1024
_CAPTION_ELLIPSIS = "…"


def truncate_caption(text: str, limit: int = CAPTION_LIMIT) -> str:
    """Обрезает caption до limit символов с многоточием.

    Подпись медиа в Telegram ограничена 1024 символами; длинная анкета
    (большой bio + много фандомов + бейдж города) может выйти за лимит и
    вызвать `MEDIA_CAPTION_TOO_LONG`. Вызывать перед любым `send_photo` /
    `send_video` / `send_animation` / `edit_media`.
    """
    if len(text) <= limit:
        return text
    return text[: limit - len(_CAPTION_ELLIPSIS)] + _CAPTION_ELLIPSIS


def _format_list(items: list[str]) -> str:
    if not items:
        return texts.RENDER_EMPTY_VALUE
    return ", ".join(items)


def render_profile_card(
    profile: Profile,
    *,
    gender: Gender,
    own_vibe: Vibe,
    desired_vibes: list[Vibe],
    fandoms: list[Fandom],
    desired_fandoms: list[Fandom],
    interests: list[Interest],
    looking_for_genders: list[Gender],
    viewer_is_self: bool = False,
) -> RenderedProfile:
    """Собирает текст карточки и метаданные медиа.

    `viewer_is_self=True` сейчас не отличается от False — задел на будущее
    (этап 3.4 и далее: скрытие чувствительных полей при просмотре чужой анкеты).

    `desired_vibes=[]` означает «ищу любой вайб» — валидное состояние, а не
    отсутствие данных; в карточке выводится как «любой».
    """
    # Заголовок: nickname, возраст.
    header = f"{profile.nickname}, {profile.age}"

    own_vibe_str = texts.RENDER_VIBE_NUMBER.format(number=own_vibe.number)

    if desired_vibes:
        desired_vibe_str = ", ".join(
            texts.RENDER_VIBE_NUMBER.format(number=v.number)
            for v in sorted(desired_vibes, key=lambda v: v.number)
        )
    else:
        desired_vibe_str = texts.RENDER_VIBE_ANY

    lines: list[str] = [header]
    lines.append(f"{texts.RENDER_FIELD_GENDER}: {gender.title}")
    lines.append(f"{texts.RENDER_FIELD_CITY}: {profile.city or texts.RENDER_EMPTY_VALUE}")
    lines.append(f"{texts.RENDER_FIELD_BIO}: {profile.bio}")
    lines.append(f"{texts.RENDER_FIELD_FANDOMS}: {_format_list([f.title for f in fandoms])}")
    lines.append(
        f"{texts.RENDER_FIELD_DESIRED_FANDOMS}: {_format_list([f.title for f in desired_fandoms])}"
    )
    lines.append(f"{texts.RENDER_FIELD_INTERESTS}: {_format_list([i.title for i in interests])}")
    lines.append(f"{texts.RENDER_FIELD_OWN_VIBE}: {own_vibe_str}")
    lines.append(f"{texts.RENDER_FIELD_DESIRED_VIBE}: {desired_vibe_str}")
    lines.append(
        f"{texts.RENDER_FIELD_LOOKING_FOR}: {_format_list([g.title for g in looking_for_genders])}"
    )
    lines.append(
        f"{texts.RENDER_FIELD_LOOKING_FOR_AGE}: "
        f"{profile.looking_for_age_min}–{profile.looking_for_age_max}"
    )
    # viewer_is_self пока не меняет содержимое, но фиксируем подпись параметра.
    _ = viewer_is_self

    return RenderedProfile(
        text="\n".join(lines),
        media_type=profile.main_media_type,
        media_file_id=profile.main_media_file_id,
    )


async def build_rendered_profile(
    db_session: AsyncSession,
    profile: Profile,
    *,
    viewer_is_self: bool = False,
) -> RenderedProfile | None:
    """Подгружает связные справочники и собирает `RenderedProfile`.

    Возвращает `None`, если в БД нет обязательного справочника (gender / own_vibe).

    Переиспользуется матчингом и админкой (карточка нарушителя в жалобах).
    """
    dict_repo = DictionaryRepository(db_session)
    profile_repo = ProfileRepository(db_session)

    gender = await dict_repo.get_by_id(Gender, profile.gender_id)
    own_vibe = await dict_repo.get_by_id(Vibe, profile.own_vibe_id)
    if gender is None or own_vibe is None:
        logger.error(
            "Missing dictionary entries when rendering profile user_id={}",
            profile.user_id,
        )
        return None

    all_fandoms = await dict_repo.list_active(Fandom)
    all_interests = await dict_repo.list_active(Interest)
    all_genders = await dict_repo.list_active(Gender)

    desired_vibe_ids = set(await profile_repo.get_desired_vibe_ids(profile.id))
    all_vibes = await dict_repo.list_active(Vibe)
    desired_vibes = [v for v in all_vibes if v.id in desired_vibe_ids]

    fandom_ids = set(await profile_repo.get_fandom_ids(profile.id))
    desired_fandom_ids = set(await profile_repo.get_desired_fandom_ids(profile.id))
    interest_ids = set(await profile_repo.get_interest_ids(profile.id))
    lfg_ids = set(await profile_repo.get_looking_for_gender_ids(profile.id))

    fandoms = [f for f in all_fandoms if f.id in fandom_ids]
    desired_fandoms = [f for f in all_fandoms if f.id in desired_fandom_ids]
    interests = [i for i in all_interests if i.id in interest_ids]
    looking_for_genders = [g for g in all_genders if g.id in lfg_ids]

    return render_profile_card(
        profile,
        gender=gender,
        own_vibe=own_vibe,
        desired_vibes=desired_vibes,
        fandoms=fandoms,
        desired_fandoms=desired_fandoms,
        interests=interests,
        looking_for_genders=looking_for_genders,
        viewer_is_self=viewer_is_self,
    )


async def send_premium_media(
    bot: Bot,
    chat_id: int,
    profile: Profile,
    db_session: AsyncSession,
    *,
    with_premium_media: bool = False,
) -> None:
    """Отправляет premium-медиа (аудио, кружок) после основной карточки.

    При TelegramAPIError (протухший file_id) — пишем warning-лог и обнуляем
    поле в БД. Пользователю ничего не показываем — доп. сообщение об ошибке
    только засорит чат.

    Параметр `with_premium_media=True` включает отправку. Для «Моя анкета» и
    матчинга передаём True (пока одинаково, в будущем можно разделить).
    """
    if not with_premium_media:
        return

    repo = ProfileRepository(db_session)

    if profile.music_file_id:
        try:
            await bot.send_audio(chat_id, profile.music_file_id)
        except TelegramAPIError as exc:
            logger.warning(
                "send_premium_media: failed to send audio for profile_id={}, error={}",
                profile.id,
                exc,
            )
            await repo.set_music(profile.id, None)

    if profile.video_note_file_id:
        try:
            await bot.send_video_note(chat_id, profile.video_note_file_id)
        except TelegramAPIError as exc:
            logger.warning(
                "send_premium_media: failed to send video_note for profile_id={}, error={}",
                profile.id,
                exc,
            )
            await repo.set_video_note(profile.id, None)
