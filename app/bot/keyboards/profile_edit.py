"""Inline-клавиатуры раздела «Моя анкета» (этап 3.4 + 8)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import premium_media as pm_texts
from app.texts import profile_edit as texts


class ProfileEditCb(CallbackData, prefix="pedit"):
    """Callback для всех действий на карточке «Моя анкета».

    Возможные `action`:
      'edit_fields' | 'back_to_card' |
      'nickname' | 'age' | 'gender' | 'looking_for_genders' |
      'la_range' | 'bio' | 'city' | 'fandoms' | 'desired_fandoms' |
      'interests' | 'own_vibe' | 'desired_vibe' | 'media' |
      'toggle_hidden' | 'delete' | 'cancel_delete' | 'confirm_delete' |
      'add_music' | 'remove_music' | 'add_video_note' | 'remove_video_note'.
    """

    action: str


def profile_card_kb(
    *,
    is_hidden: bool,
    has_music: bool = False,
    has_video_note: bool = False,
) -> InlineKeyboardMarkup:
    """Компактная клавиатура карточки «Моя анкета».

    12 кнопок редактирования полей спрятаны за «Изменить анкету»
    (см. profile_fields_kb) — на самой карточке только редкие действия.
    Кнопки premium-медиа отображаются всегда; обработчики проверяют is_premium.
    """
    builder = InlineKeyboardBuilder()

    builder.button(text=texts.BTN_EDIT_PROFILE, callback_data=ProfileEditCb(action="edit_fields"))

    # Premium: музыка
    music_btn_text = pm_texts.BTN_CHANGE_MUSIC if has_music else pm_texts.BTN_ADD_MUSIC
    builder.button(text=music_btn_text, callback_data=ProfileEditCb(action="add_music"))
    if has_music:
        builder.button(
            text=pm_texts.BTN_REMOVE_MUSIC, callback_data=ProfileEditCb(action="remove_music")
        )

    # Premium: кружок
    vn_btn_text = pm_texts.BTN_CHANGE_VIDEO_NOTE if has_video_note else pm_texts.BTN_ADD_VIDEO_NOTE
    builder.button(text=vn_btn_text, callback_data=ProfileEditCb(action="add_video_note"))
    if has_video_note:
        builder.button(
            text=pm_texts.BTN_REMOVE_VIDEO_NOTE,
            callback_data=ProfileEditCb(action="remove_video_note"),
        )

    toggle_text = texts.BTN_SHOW if is_hidden else texts.BTN_HIDE
    builder.button(text=toggle_text, callback_data=ProfileEditCb(action="toggle_hidden"))
    builder.button(text=texts.BTN_DELETE, callback_data=ProfileEditCb(action="delete"))

    # Раскладка: «Изменить анкету» (1), музыка (1/2), кружок (1/2), скрыть (1), удалить (1).
    music_row = 2 if has_music else 1
    vn_row = 2 if has_video_note else 1
    builder.adjust(1, music_row, vn_row, 1, 1)
    return builder.as_markup()


def profile_fields_kb() -> InlineKeyboardMarkup:
    """12 кнопок редактирования отдельных полей анкеты + «Назад» к карточке.

    Открывается по кнопке «Изменить анкету» на карточке.
    """
    builder = InlineKeyboardBuilder()

    builder.button(text=texts.BTN_EDIT_NICKNAME, callback_data=ProfileEditCb(action="nickname"))
    builder.button(text=texts.BTN_EDIT_AGE, callback_data=ProfileEditCb(action="age"))
    builder.button(text=texts.BTN_EDIT_GENDER, callback_data=ProfileEditCb(action="gender"))
    builder.button(
        text=texts.BTN_EDIT_LFG, callback_data=ProfileEditCb(action="looking_for_genders")
    )
    builder.button(text=texts.BTN_EDIT_LA_RANGE, callback_data=ProfileEditCb(action="la_range"))
    builder.button(text=texts.BTN_EDIT_BIO, callback_data=ProfileEditCb(action="bio"))
    builder.button(text=texts.BTN_EDIT_CITY, callback_data=ProfileEditCb(action="city"))
    builder.button(text=texts.BTN_EDIT_FANDOMS, callback_data=ProfileEditCb(action="fandoms"))
    builder.button(
        text=texts.BTN_EDIT_DESIRED_FANDOMS,
        callback_data=ProfileEditCb(action="desired_fandoms"),
    )
    builder.button(text=texts.BTN_EDIT_INTERESTS, callback_data=ProfileEditCb(action="interests"))
    builder.button(text=texts.BTN_EDIT_OWN_VIBE, callback_data=ProfileEditCb(action="own_vibe"))
    builder.button(
        text=texts.BTN_EDIT_DESIRED_VIBE, callback_data=ProfileEditCb(action="desired_vibe")
    )
    builder.button(text=texts.BTN_EDIT_MEDIA, callback_data=ProfileEditCb(action="media"))
    builder.button(text=texts.BTN_BACK_TO_CARD, callback_data=ProfileEditCb(action="back_to_card"))

    # 13 кнопок редактирования + 1 «Назад» → по 2 в строке, последний ряд может быть 1+1.
    builder.adjust(2, 2, 2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def confirm_delete_kb() -> InlineKeyboardMarkup:
    """Подтверждение удаления: 2 кнопки в одном ряду."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_CONFIRM_DELETE,
        callback_data=ProfileEditCb(action="confirm_delete"),
    )
    builder.button(
        text=texts.BTN_CANCEL_DELETE,
        callback_data=ProfileEditCb(action="cancel_delete"),
    )
    builder.adjust(2)
    return builder.as_markup()
