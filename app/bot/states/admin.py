"""FSM-состояния для админского режима (Этап 10)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminUserStates(StatesGroup):
    search_user_query = State()


class AdminComplaintStates(StatesGroup):
    viewing = State()


class AdminAlleyStates(StatesGroup):
    ask_author = State()
    ask_category = State()
    ask_description = State()
    ask_link = State()
    uploading_photos = State()
    ask_duration = State()
    # Продление существующего поста
    extend_ask_duration = State()


class AdminPremiumStates(StatesGroup):
    search_user_query = State()
    ask_duration = State()


class AdminPromoStates(StatesGroup):
    ask_text = State()
    ask_media = State()
    ask_segment = State()
    ask_schedule = State()


class AdminDictStates(StatesGroup):
    ask_code = State()
    ask_title = State()
    # Vibe-специфичные шаги
    ask_number = State()
    ask_image = State()
    # Редактирование
    edit_ask_title = State()
    edit_ask_image = State()


class AdminStopWordStates(StatesGroup):
    ask_pattern = State()
    ask_kind = State()
    ask_category = State()
    search_query = State()
    # Редактирование
    edit_ask_pattern = State()


class AdminSettingsStates(StatesGroup):
    edit_ask_value = State()


class AdminReviewStates(StatesGroup):
    ask_reject_reason = State()


class AdminFeedStates(StatesGroup):
    # Ограничение пользователя в комментариях: FSM спрашивает кол-во часов
    restrict_ask_hours = State()
    # Удаление комментария: FSM спрашивает ID комментария
    ask_comment_id = State()
