from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """FSM-состояния регистрации анкеты.

    Этап 3.1 покрывает шаги до `interests` включительно. Этап 3.2 добавляет
    шаги `own_vibe`/`desired_vibe`. Шаги медиа добавятся в 3.3.
    Этап 3.x: капча (антибот) идёт первым, до nickname.
    """

    captcha = State()
    nickname = State()
    age = State()
    gender = State()
    looking_for_genders = State()
    looking_for_age_min = State()
    looking_for_age_max = State()
    bio = State()
    city = State()
    fandoms = State()
    desired_fandoms = State()
    interests = State()
    own_vibe = State()
    desired_vibe = State()
    main_media = State()
    # Premium-фича: пользователь загружает 1-3 фото, модератор подбирает вайб.
    vibe_by_photo_upload = State()
