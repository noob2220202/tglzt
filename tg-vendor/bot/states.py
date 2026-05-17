from aiogram.fsm.state import State, StatesGroup


class RegisterAddress(StatesGroup):
    waiting = State()


class ChangeAddress(StatesGroup):
    waiting_admin_approval = State()
