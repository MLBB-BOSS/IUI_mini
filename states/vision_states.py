"""
States for the GPT Vision Beta feature.
"""
from aiogram.fsm.state import State, StatesGroup

class VisionBetaStates(StatesGroup):
    """
    Manages states for the GPT Vision beta image analysis process.
    """
    AWAITING_IMAGE = State()  # User has initiated vision analysis and bot is waiting for an image
