"""FSM-состояния потока «Жалоба» (этап 5.1)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ComplaintStates(StatesGroup):
    choosing_reason = State()
    writing_comment = State()
