from aiogram.fsm.state import StatesGroup, State

class UploadState(StatesGroup):
    waiting_for_file = State()