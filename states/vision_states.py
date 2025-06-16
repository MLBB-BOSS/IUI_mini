from aiogram.fsm.state import State, StatesGroup

# === СТАНИ FSM ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===
class VisionAnalysisStates(StatesGroup):
    awaiting_profile_screenshot = State()
    awaiting_analysis_trigger = State()
