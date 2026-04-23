# app/config.py

import os

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
MODEL_NAME = os.getenv("MODEL_NAME_LLM")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = os.getenv("OPENROUTER_URL")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_ADMIN_CHAT_IDS = [
    int(value.strip())
    for value in os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "").split(",")
    if value.strip().isdigit()
]
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
MEDIA_PROXY_SECRET = os.getenv("MEDIA_PROXY_SECRET", "").strip()
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Europe/Madrid").strip() or "Europe/Madrid"

JELLYFIN_USER_ID = os.getenv("JELLYFIN_USER_ID", "").strip()
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "").strip()
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "").strip()
HEADERS = {"User-Agent": "Mozilla/5.0"}

YOUTUBE_MAX_HEIGHT = int(os.getenv("YOUTUBE_MAX_HEIGHT", "1080").strip() or "1080")
YOUTUBE_SEND_AS_DOCUMENT = os.getenv("YOUTUBE_SEND_AS_DOCUMENT", "false").strip().lower() in {"1", "true", "yes", "on"}
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base").strip() or "base"
WALLAPOP_ALERT_INTERVAL_HOURS = int(os.getenv("WALLAPOP_ALERT_INTERVAL_HOURS", "8").strip() or "8")
WALLAPOP_ALERT_INTERVAL_MINUTES = int(os.getenv("WALLAPOP_ALERT_INTERVAL_MINUTES", "0").strip() or "0")
WALLAPOP_ALERT_JITTER_MINUTES = int(os.getenv("WALLAPOP_ALERT_JITTER_MINUTES", "90").strip() or "90")
WALLAPOP_ALERT_BATCH_SIZE = int(os.getenv("WALLAPOP_ALERT_BATCH_SIZE", "3").strip() or "3")
