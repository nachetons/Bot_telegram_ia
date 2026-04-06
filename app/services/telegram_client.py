import requests
from app.config import TELEGRAM_BOT_TOKEN

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(chat_id: str, text: str):
    try:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]

        for chunk in chunks:
            r = requests.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk
                },
                timeout=5
            )

            print("TG:", r.status_code, r.text)

    except Exception as e:
        print("send_message error:", e)


def send_photo(chat_id: str, image_url: str):
    try:
        requests.post(
            f"{BASE_URL}/sendPhoto",
            json={
                "chat_id": chat_id,
                "photo": image_url
            },
            timeout=10
        )
    except Exception:
        pass


# 👇 ESTE ES EL QUE PREGUNTAS
def send_images(chat_id, images):
    import requests

    media = [{"type": "photo", "media": img} for img in images[:10]]

    try:
        requests.post(
            f"{BASE_URL}/sendMediaGroup",
            json={
                "chat_id": chat_id,
                "media": media
            },
            timeout=10
        )
    except Exception:
        pass


def send_video(chat_id: str, video_url: str, caption: str = None):
    try:
        requests.post(
        f"{BASE_URL}/sendVideo",
        json={
            "chat_id": chat_id,
            "video": video_url,
            "caption": caption
        }
    )
    except Exception as e:
        print("Error enviando video:", e)


def send_message_with_buttons(chat_id: str, text: str, buttons: list):

    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": buttons
        }
    }

    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json=payload,
            timeout=10
        )

        # 🔥 DEBUG REAL (CLAVE)
        print("TELEGRAM RESPONSE:", r.status_code, r.text)

    except Exception as e:
        print("Error send buttons:", e)


import requests

def answer_callback_query(callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
        
    requests.post(url, json=payload)