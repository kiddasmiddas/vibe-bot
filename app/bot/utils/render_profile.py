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
from html import escape as _html_escape

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

# «Умный бюджет» карточки: рендерим текст так, чтобы вместе с заголовком/бейджем,
# который допишет хэндлер, влезть в CAPTION_LIMIT. Запас покрывает все статичные
# заголовки; экстремальные случаи (длинное сообщение суперлайка в шапке) добьёт
# грубый truncate_caption на месте отправки.
_CAPTION_RESERVE = 160
_MIN_LIST_KEEP = 1  # меньше одного элемента список не сворачиваем
_MIN_BIO_KEEP = 40  # bio режем последним и не короче этого


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
    # Бот рендерит карточку с parse_mode=HTML (DefaultBotProperties), поэтому
    # любые строки из БД (в т.ч. справочники) экранируем, чтобы '<'/'&' не ломали
    # разметку и не позволяли инъекцию.
    return ", ".join(_html_escape(i) for i in items)


def _render_list_line(label: str, escaped_titles: list[str], keep: int) -> str:
    """Строка-список с частичным сворачиванием: «Фандомы: A, B …и ещё 7»."""
    if not escaped_titles:
        return f"{label}: {texts.RENDER_EMPTY_VALUE}"
    shown = ", ".join(escaped_titles[:keep])
    hidden = len(escaped_titles) - keep
    if hidden <= 0:
        return f"{label}: {shown}"
    return f"{label}: {shown} {texts.RENDER_LIST_MORE.format(n=hidden)}"


def _fit_card_lines(
    lines: list[str],
    *,
    list_slots: dict[int, tuple[str, list[str], int]],
    bio_slot: tuple[int, str, str],
    budget: int,
) -> list[str]:
    """Сжимает карточку под budget, не трогая структурные строки.

    Сначала сворачиваются списки (`list_slots`: index → (label, escaped_titles,
    keep)) — жадно, начиная с самой длинной строки, до «…и ещё N» с минимум
    одним видимым элементом. Если не хватило — режется bio (последним, не
    короче _MIN_BIO_KEEP). Дальше уже дело внешнего truncate_caption.
    """

    def total() -> int:
        return sum(len(line) for line in lines) + len(lines) - 1

    slots = {idx: [label, titles, keep] for idx, (label, titles, keep) in list_slots.items()}
    while total() > budget:
        shrinkable = [
            (len(lines[idx]), idx) for idx, (_, _, keep) in slots.items() if keep > _MIN_LIST_KEEP
        ]
        if not shrinkable:
            break
        _, idx = max(shrinkable)
        slot = slots[idx]
        slot[2] -= 1
        lines[idx] = _render_list_line(slot[0], slot[1], slot[2])

    if total() > budget:
        bio_idx, bio_label, bio_raw = bio_slot
        keep = len(bio_raw)
        # Обрезка сырого bio на N символов укорачивает экранированную строку
        # минимум на N — цикл сходится за 1-2 прохода.
        while total() > budget and keep > _MIN_BIO_KEEP:
            keep = max(_MIN_BIO_KEEP, keep - max(10, total() - budget))
            lines[bio_idx] = (
                f"{bio_label}: {_html_escape(bio_raw[:keep].rstrip())}{_CAPTION_ELLIPSIS}"
            )

    return lines


def render_profile_card(
    profile: Profile,
    *,
    gender: Gender,
    own_vibe: Vibe | None,
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
    # Заголовок: nickname, возраст. Карточка уходит с parse_mode=HTML, поэтому
    # ВСЕ пользовательские строки (nickname, city, bio) экранируем — иначе
    # '<', '>', '&' и теги (например, ссылка в свободно введённом городе)
    # отрендерятся/сломают разметку у всех, кто видит анкету.
    header = f"{_html_escape(profile.nickname)}, {profile.age}"

    # own_vibe=None — вайб ещё подбирает модератор («Вайб по фото»).
    # Название вайба — справочник, но экранируем как любой текст из БД.
    if own_vibe is not None:
        own_vibe_str = texts.RENDER_VIBE_NUMBER.format(
            number=own_vibe.number, title=_html_escape(own_vibe.title)
        )
    else:
        own_vibe_str = texts.RENDER_VIBE_PENDING

    if desired_vibes:
        desired_vibe_str = ", ".join(
            texts.RENDER_VIBE_NUMBER.format(number=v.number, title=_html_escape(v.title))
            for v in sorted(desired_vibes, key=lambda v: v.number)
        )
    else:
        desired_vibe_str = texts.RENDER_VIBE_ANY

    fandom_titles = [_html_escape(f.title) for f in fandoms]
    desired_titles = [_html_escape(f.title) for f in desired_fandoms]
    interest_titles = [_html_escape(i.title) for i in interests]

    lines: list[str] = [header]
    lines.append(f"{texts.RENDER_FIELD_GENDER}: {_html_escape(gender.title)}")
    city_str = _html_escape(profile.city) if profile.city else texts.RENDER_EMPTY_VALUE
    lines.append(f"{texts.RENDER_FIELD_CITY}: {city_str}")
    bio_index = len(lines)
    lines.append(f"{texts.RENDER_FIELD_BIO}: {_html_escape(profile.bio)}")
    list_slots: dict[int, tuple[str, list[str], int]] = {}
    list_slots[len(lines)] = (texts.RENDER_FIELD_FANDOMS, fandom_titles, len(fandom_titles))
    lines.append(_render_list_line(texts.RENDER_FIELD_FANDOMS, fandom_titles, len(fandom_titles)))
    list_slots[len(lines)] = (
        texts.RENDER_FIELD_DESIRED_FANDOMS,
        desired_titles,
        len(desired_titles),
    )
    lines.append(
        _render_list_line(texts.RENDER_FIELD_DESIRED_FANDOMS, desired_titles, len(desired_titles))
    )
    list_slots[len(lines)] = (texts.RENDER_FIELD_INTERESTS, interest_titles, len(interest_titles))
    lines.append(
        _render_list_line(texts.RENDER_FIELD_INTERESTS, interest_titles, len(interest_titles))
    )
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

    # Умное сжатие под caption-лимит: длинные анкеты (старые, до лимитов 15/200)
    # сворачивают списки «…и ещё N», bio режется последним; структура целая.
    lines = _fit_card_lines(
        lines,
        list_slots=list_slots,
        bio_slot=(bio_index, texts.RENDER_FIELD_BIO, profile.bio),
        budget=CAPTION_LIMIT - _CAPTION_RESERVE,
    )

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
    # own_vibe_id IS NULL — валидное состояние (ждёт модератора), не ошибка.
    own_vibe = (
        await dict_repo.get_by_id(Vibe, profile.own_vibe_id)
        if profile.own_vibe_id is not None
        else None
    )
    if gender is None or (profile.own_vibe_id is not None and own_vibe is None):
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
