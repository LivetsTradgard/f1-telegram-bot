from aiogram.fsm.state import State, StatesGroup

class Archive(StatesGroup):
    waiting_for_year = State()

class Predict(StatesGroup):
    waiting_p1 = State()
    waiting_p2 = State()
    waiting_p3 = State()