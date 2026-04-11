# app/config.py

import os

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
MODEL_NAME = os.getenv("MODEL_NAME_LLM")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = os.getenv("OPENROUTER_URL")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

JELLYFIN_USER_ID = os.getenv("JELLYFIN_USER_ID", "").strip()
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "").strip()
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "").strip()
HEADERS = {"User-Agent": "Mozilla/5.0"}

YOUTUBE_MAX_HEIGHT = int(os.getenv("YOUTUBE_MAX_HEIGHT", "720").strip() or "720")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base").strip() or "base"
