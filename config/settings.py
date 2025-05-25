# ... інші твої налаштування ...

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VISION_MODEL_4 = os.getenv("VISION_MODEL_4", "GPT-4.1") # gpt-4o або gpt-4-vision-preview

# ... інші твої налаштування ...
