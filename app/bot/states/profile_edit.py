from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ProfileEditStates(StatesGroup):
    """FSM-состояния редактирования полей анкеты (этап 3.4)."""

    edit_nickname = State()
    edit_age = State()
    edit_gender = State()
    edit_looking_for_genders = State()
    edit_la_min = State()
    edit_la_max = State()
    edit_bio = State()
    edit_city = State()
    edit_fandoms = State()
    edit_desired_fandoms = State()
    edit_interests = State()
    edit_own_vibe = State()
    edit_desired_vibe = State()
    edit_media = State()
    confirm_delete = State()
    # Premium-фичи (Этап 8)
    waiting_music = State()
    waiting_video_note = State()
    # Premium: «Вайб по фото» — загрузка 1-3 фото для модератора.
    vibe_by_photo_upload = State()
