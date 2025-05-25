# ... інші твої налаштування ...

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VISION_BETA_MODEL_NAME = os.getenv("VISION_BETA_MODEL_NAME", "gpt-4o") # gpt-4o або gpt-4-vision-preview

# ... інші твої налаштування ...
