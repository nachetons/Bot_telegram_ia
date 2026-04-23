import json
import requests
from itertools import combinations
from pathlib import Path
from app.config import TELEGRAM_BOT_TOKEN

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_MEDIA_TIMEOUT = 30


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


def send_message_with_reply_keyboard(chat_id: str, text: str, keyboard: list, one_time_keyboard: bool = True):
    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text[:4000],
                "reply_markup": {
                    "keyboard": keyboard,
                    "resize_keyboard": True,
                    "one_time_keyboard": one_time_keyboard,
                }
            },
            timeout=10
        )
        print("TG REPLY KEYBOARD:", response.status_code, response.text)
        data = response.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")
    except Exception as e:
        print("send_message_with_reply_keyboard error:", e)
    return None


def remove_reply_keyboard(chat_id: str):
    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "\u2063",
                "reply_markup": {
                    "remove_keyboard": True
                }
            },
            timeout=10
        )
        print("TG REMOVE KEYBOARD:", response.status_code, response.text)
        data = response.json()
        message_id = data.get("result", {}).get("message_id") if data.get("ok") else None
        if message_id:
            delete_message(chat_id, message_id)
        return bool(data.get("ok"))
    except Exception as e:
        print("remove_reply_keyboard error:", e)
        return False


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

        response = requests.post(
            f"{BASE_URL}/sendPhoto",
            json=payload,
            timeout=TELEGRAM_MEDIA_TIMEOUT
        )
        print("TG PHOTO:", response.status_code, response.text)
    except Exception as e:
        print("send_photo error:", e)


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

        response = requests.post(
            f"{BASE_URL}/sendPhoto",
            json=payload,
            timeout=TELEGRAM_MEDIA_TIMEOUT
        )
        print("TG PHOTO BUTTONS:", response.status_code, response.text)
        data = response.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")
    except Exception as e:
        print("send_photo_with_buttons error:", e)
    return None


def send_photo_bytes_with_buttons(chat_id: str, photo_bytes: bytes, filename: str, caption: str, buttons: list):
    try:
        response = requests.post(
            f"{BASE_URL}/sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": (caption or "")[:1024],
                "reply_markup": json.dumps({"inline_keyboard": buttons}, ensure_ascii=False),
            },
            files={
                "photo": (filename or "image.jpg", photo_bytes),
            },
            timeout=TELEGRAM_MEDIA_TIMEOUT,
        )
        print("TG PHOTO BYTES BUTTONS:", response.status_code, response.text)
        data = response.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")
    except Exception as e:
        print("send_photo_bytes_with_buttons error:", e)
    return None


def _build_media_group(images):
    media = []
    for image in images:
        item = {
            "type": "photo",
            "media": image["url"]
        }
        if image.get("caption"):
            item["caption"] = image["caption"]
        media.append(item)
    return media


def _try_send_media_group(chat_id, images):
    media = _build_media_group(images)
    response = requests.post(
        f"{BASE_URL}/sendMediaGroup",
        json={
            "chat_id": chat_id,
            "media": media
        },
        timeout=15
    )
    print("TG MEDIA GROUP:", response.status_code, response.text)
    return response


def send_images(chat_id, images):
    source_labels = []
    candidate_images = []

    for index, image in enumerate(images[:10]):
        if isinstance(image, dict):
            image_url = image.get("image_url") or image.get("thumbnail_url")
            if not image_url:
                continue

            candidate_images.append(
                {
                    "url": image_url,
                    "caption": None,
                    "title": image.get("title"),
                    "source_domain": image.get("source_domain"),
                }
            )
        elif image:
            candidate_images.append(
                {
                    "url": image,
                    "caption": None,
                }
            )

        if isinstance(image, dict):
            domain = image.get("source_domain")
            if domain and domain not in source_labels:
                source_labels.append(domain)

    if not candidate_images:
        return

    selected_images = candidate_images[:6]

    if isinstance(images[0], dict) and selected_images:
        first_caption = []
        first_title = selected_images[0].get("title") or images[0].get("title")

        if first_title:
            first_caption.append(first_title[:180])

        if source_labels:
            first_caption.append("Fuentes: " + " | ".join(source_labels[:3]))

        if first_caption:
            caption = "\n".join(first_caption)[:1024]
            selected_images[0]["caption"] = caption

    album_attempts = []
    if len(selected_images) >= 3:
        album_attempts.append(selected_images[:3])

        for combo in combinations(selected_images, 3):
            combo_list = list(combo)
            if combo_list == album_attempts[0]:
                continue
            if selected_images[0] in combo_list:
                combo_list = [selected_images[0]] + [img for img in combo_list if img is not selected_images[0]]
            album_attempts.append(combo_list)
    elif selected_images:
        album_attempts.append(selected_images[:])

    for attempt in album_attempts[:8]:
        try:
            response = _try_send_media_group(chat_id, attempt)
            if response.ok:
                return
        except Exception as e:
            print("send_images media group error:", e)

    for image in selected_images[:3]:
        try:
            send_photo(chat_id, image["url"], image.get("caption"))
        except Exception as e:
            print("send_images fallback error:", e)


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


def send_local_document(chat_id: str, file_path: str, caption: str = None):
    try:
        path = Path(file_path)
        if not path.exists():
            print("send_local_document error: file not found", file_path)
            return

        with path.open("rb") as document_file:
            response = requests.post(
                f"{BASE_URL}/sendDocument",
                data={
                    "chat_id": chat_id,
                    "caption": (caption or "")[:1024],
                },
                files={
                    "document": document_file
                },
                timeout=120
            )
            print("TG LOCAL DOCUMENT:", response.status_code, response.text)
    except Exception as e:
        print("send_local_document error:", e)


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
        data = r.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")

    except Exception as e:
        print("Error send buttons:", e)
    return None


def edit_photo_with_buttons(chat_id: str, message_id: int, image_url: str, caption: str, buttons: list):
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "media": {
                "type": "photo",
                "media": image_url,
                "caption": (caption or "")[:1024],
            },
            "reply_markup": {
                "inline_keyboard": buttons
            }
        }

        response = requests.post(
            f"{BASE_URL}/editMessageMedia",
            json=payload,
            timeout=10
        )
        print("TG EDIT PHOTO BUTTONS:", response.status_code, response.text)
        return response.ok
    except Exception as e:
        print("edit_photo_with_buttons error:", e)
        return False

def answer_callback_query(callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
        
    requests.post(url, json=payload)
