"""FSM-состояния раздела «Искать своих» (этап 4.2).

Сам просмотр анкет state не требует — экшены идут через `CallbackData`. State
нужен только для одного сценария: «лайк с сообщением», когда пользователь
переходит в режим ожидания текста (superlike_message).
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MatchingStates(StatesGroup):
    superlike_message = State()
