import requests
from pathlib import Path
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


def get_file_path(file_id: str):
    try:
        r = requests.post(
            f"{BASE_URL}/getFile",
            json={"file_id": file_id},
            timeout=10
        )
        data = r.json()
        if data.get("ok"):
            return data.get("result", {}).get("file_path")
    except Exception as e:
        print("get_file_path error:", e)
    return None


def download_telegram_file(file_id: str, destination_path: str):
    try:
        file_path = get_file_path(file_id)
        if not file_path:
            return None

        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        response = requests.get(file_url, timeout=120)
        response.raise_for_status()

        path = Path(destination_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return str(path)
    except Exception as e:
        print("download_telegram_file error:", e)
        return None


def send_temp_message(chat_id: str, text: str = "Buscando..."):
    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text
            },
            timeout=5
        )
        print("TG TEMP:", r.status_code, r.text)

        data = r.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")
    except Exception as e:
        print("send_temp_message error:", e)

    return None


def edit_message(chat_id: str, message_id: int, text: str):
    try:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)] or [""]
        first_chunk = chunks[0]

        r = requests.post(
            f"{BASE_URL}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": first_chunk
            },
            timeout=5
        )
        print("TG EDIT:", r.status_code, r.text)

        for chunk in chunks[1:]:
            send_message(chat_id, chunk)
    except Exception as e:
        print("edit_message error:", e)


def edit_message_with_buttons(chat_id: str, message_id: int, text: str, buttons: list):
    try:
        r = requests.post(
            f"{BASE_URL}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text[:4000],
                "reply_markup": {
                    "inline_keyboard": buttons
                }
            },
            timeout=5
        )
        print("TG EDIT BUTTONS:", r.status_code, r.text)
    except Exception as e:
        print("edit_message_with_buttons error:", e)


def delete_message(chat_id: str, message_id: int):
    try:
        r = requests.post(
            f"{BASE_URL}/deleteMessage",
            json={
                "chat_id": chat_id,
                "message_id": message_id
            },
            timeout=5
        )
        print("TG DELETE:", r.status_code, r.text)
    except Exception as e:
        print("delete_message error:", e)


def send_chat_action(chat_id: str, action: str = "typing"):
    try:
        r = requests.post(
            f"{BASE_URL}/sendChatAction",
            json={
                "chat_id": chat_id,
                "action": action
            },
            timeout=5
        )
        print("TG ACTION:", r.status_code, r.text)
    except Exception as e:
        print("send_chat_action error:", e)


def send_photo(chat_id: str, image_url: str, caption: str = None):
    try:
        payload = {
            "chat_id": chat_id,
            "photo": image_url
        }

        if caption:
            payload["caption"] = caption[:1024]

        requests.post(
            f"{BASE_URL}/sendPhoto",
            json=payload,
            timeout=10
        )
    except Exception:
        pass


def send_photo_with_buttons(chat_id: str, image_url: str, caption: str, buttons: list):
    try:
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": (caption or "")[:1024],
            "reply_markup": {
                "inline_keyboard": buttons
            }
        }

        requests.post(
            f"{BASE_URL}/sendPhoto",
            json=payload,
            timeout=10
        )
    except Exception as e:
        print("send_photo_with_buttons error:", e)


def send_images(chat_id, images):
    media = []
    source_labels = []

    for index, image in enumerate(images[:10]):
        if isinstance(image, dict):
            image_url = image.get("image_url") or image.get("thumbnail_url")
            if not image_url:
                continue

            item = {
                "type": "photo",
                "media": image_url
            }

            if index == 0:
                caption_parts = []
                title = image.get("title")

                if title:
                    caption_parts.append(title[:180])

            media.append(item)
        elif image:
            media.append({"type": "photo", "media": image})

        if isinstance(image, dict):
            domain = image.get("source_domain")
            if domain and domain not in source_labels:
                source_labels.append(domain)

    if not media:
        return

    if isinstance(images[0], dict):
        first_caption = []
        first_title = images[0].get("title")

        if first_title:
            first_caption.append(first_title[:180])

        if source_labels:
            first_caption.append("Fuentes: " + " | ".join(source_labels[:3]))

        if first_caption:
            media[0]["caption"] = "\n".join(first_caption)[:1024]

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


def send_local_video(chat_id: str, video_path: str, caption: str = None):
    try:
        path = Path(video_path)
        if not path.exists():
            print("send_local_video error: file not found", video_path)
            return

        with path.open("rb") as video_file:
            response = requests.post(
                f"{BASE_URL}/sendVideo",
                data={
                    "chat_id": chat_id,
                    "caption": (caption or "")[:1024],
                    "supports_streaming": "true",
                },
                files={
                    "video": video_file
                },
                timeout=120
            )
            print("TG LOCAL VIDEO:", response.status_code, response.text)
    except Exception as e:
        print("send_local_video error:", e)


def send_local_audio(chat_id: str, audio_path: str, title: str = None, performer: str = None):
    try:
        path = Path(audio_path)
        if not path.exists():
            print("send_local_audio error: file not found", audio_path)
            return

        with path.open("rb") as audio_file:
            response = requests.post(
                f"{BASE_URL}/sendAudio",
                data={
                    "chat_id": chat_id,
                    "title": (title or "")[:256],
                    "performer": (performer or "")[:256],
                },
                files={
                    "audio": audio_file
                },
                timeout=120
            )
            print("TG LOCAL AUDIO:", response.status_code, response.text)
    except Exception as e:
        print("send_local_audio error:", e)


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

def answer_callback_query(callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
        
    requests.post(url, json=payload)
