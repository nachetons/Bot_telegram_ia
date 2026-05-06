import json
import logging
import requests
import threading
from itertools import combinations
from pathlib import Path
from app.config import TELEGRAM_BOT_TOKEN

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_MEDIA_TIMEOUT = 30
recent_bot_messages = {}
recent_bot_messages_lock = threading.Lock()

logger = logging.getLogger("telegram_client")



def _is_known_edit_race(response_payload):
    description = ((response_payload or {}).get("description") or "").lower()
    return "message_id_invalid" in description or "message to edit not found" in description


def _track_bot_message(chat_id, message_id):
    if chat_id is None or message_id is None:
        return
    chat_id = int(chat_id)
    message_id = int(message_id)
    with recent_bot_messages_lock:
        history = list(recent_bot_messages.get(chat_id, []))
        if message_id in history:
            history.remove(message_id)
        history.append(message_id)
        recent_bot_messages[chat_id] = history[-80:]


def _untrack_bot_message(chat_id, message_id):
    if chat_id is None or message_id is None:
        return
    chat_id = int(chat_id)
    message_id = int(message_id)
    with recent_bot_messages_lock:
        history = [value for value in recent_bot_messages.get(chat_id, []) if int(value) != message_id]
        if history:
            recent_bot_messages[chat_id] = history
        else:
            recent_bot_messages.pop(chat_id, None)


def pop_recent_bot_messages(chat_id):
    if chat_id is None:
        return []
    with recent_bot_messages_lock:
        return list(recent_bot_messages.pop(int(chat_id), []))


def send_message(chat_id: str, text: str):
    try:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        last_message_id = None

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
            data = r.json()
            if data.get("ok"):
                last_message_id = data.get("result", {}).get("message_id")
                _track_bot_message(chat_id, last_message_id)

        return last_message_id

    except Exception as e:
        print("send_message error:", e)
    return None


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
            message_id = data.get("result", {}).get("message_id")
            _track_bot_message(chat_id, message_id)
            return message_id
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
            message_id = data.get("result", {}).get("message_id")
            _track_bot_message(chat_id, message_id)
            return message_id
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
        data = r.json()
        if not _is_known_edit_race(data):
            print("TG EDIT:", r.status_code, r.text)
        if not data.get("ok"):
            if _is_known_edit_race(data):
                return False

        for chunk in chunks[1:]:
            send_message(chat_id, chunk)
        return bool(data.get("ok"))
    except Exception as e:
        print("edit_message error:", e)
    return False


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
        data = r.json()
        if not _is_known_edit_race(data):
            print("TG EDIT BUTTONS:", r.status_code, r.text)
        if not data.get("ok"):
            if _is_known_edit_race(data):
                return False
        return bool(data.get("ok"))
    except Exception as e:
        print("edit_message_with_buttons error:", e)
    return False


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
        data = r.json()
        if data.get("ok"):
            _untrack_bot_message(chat_id, message_id)
            return True
    except Exception as e:
        print("delete_message error:", e)
    return False


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
        data = response.json()
        if data.get("ok"):
            message_id = data.get("result", {}).get("message_id")
            _track_bot_message(chat_id, message_id)
            return message_id
    except Exception as e:
        print("send_photo error:", e)
    return None


def send_photo_with_buttons(chat_id: str, image_url: str, caption: str, buttons: list):
    try:
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": (caption or "")[:1024],
            "reply_markup": {"inline_keyboard": buttons} if buttons else None,
        }
        response = requests.post(
            f"{BASE_URL}/sendPhoto",
            json=payload,
            timeout=TELEGRAM_MEDIA_TIMEOUT,
        )
        data = response.json()
        if data.get("ok"):
            message_id = data.get("result", {}).get("message_id")
            _track_bot_message(chat_id, message_id)
            return message_id
    except Exception as e:
        print("send_photo_with_buttons error:", e)
    return None


def send_document(chat_id: str, file_path: str, caption: str = ""):
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        
        response = requests.post(
            f"{BASE_URL}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": (caption or "")[:1024],
            },
            files={
                "document": ("file.zip", file_bytes),
            },
            timeout=TELEGRAM_MEDIA_TIMEOUT,
        )
        print("TG DOCUMENT:", response.status_code, response.text)
        data = response.json()
        if data.get("ok"):
            message_id = data.get("result", {}).get("message_id")
            _track_bot_message(chat_id, message_id)
            return message_id
    except Exception as e:
        print("send_document error:", e)
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
            message_id = data.get("result", {}).get("message_id")
            _track_bot_message(chat_id, message_id)
            return message_id
    except Exception as e:
        print("send_photo_bytes_with_buttons error:", e)
    return None


def send_local_photo_with_buttons(chat_id: str, image_path: str, caption: str, buttons: list):
    try:
        path = Path(image_path)
        if not path.exists():
            print("send_local_photo_with_buttons error: file not found", image_path)
            return None

        with path.open("rb") as image_file:
            response = requests.post(
                f"{BASE_URL}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": (caption or "")[:1024],
                    "reply_markup": json.dumps({"inline_keyboard": buttons}, ensure_ascii=False),
                },
                files={
                    "photo": image_file,
                },
                timeout=TELEGRAM_MEDIA_TIMEOUT,
            )
            print("TG LOCAL PHOTO BUTTONS:", response.status_code, response.text)
            data = response.json()
            if data.get("ok"):
                message_id = data.get("result", {}).get("message_id")
                _track_bot_message(chat_id, message_id)
                return message_id
    except Exception as e:
        print("send_local_photo_with_buttons error:", e)
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


def _try_send_media_group(chat_id, images, manga_chat_id=None):
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
    try:
        data = response.json()
        if data.get("ok"):
            manga_message_ids = []
            for item in data.get("result", []):
                mid = item.get("message_id")
                _track_bot_message(chat_id, mid)
                # Guardar message_ids para menus manga (para poder eliminarlos despues)
                if manga_chat_id:
                    manga_message_ids.append(mid)
            # Guardar todos los message_ids del album en state_manager
            if manga_message_ids and manga_chat_id:
                try:
                    from app.core.state_manager import state_manager
                    lock = state_manager._get_lock(manga_chat_id)
                    with lock:
                        if manga_chat_id not in state_manager.sessions:
                            state_manager.sessions[manga_chat_id] = {}
                        state_manager.sessions[manga_chat_id]["manga_menu_messages"] = manga_message_ids
                except Exception as exc:
                    logger.debug(f"No se pudo guardar message_ids del album manga: {exc}")
    except Exception:
        pass
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
    """EnvÃ­a video como Video o Document segÃºn el tamaÃ±o."""
    logger.info(f"📚 SEND VIDEO: chat={chat_id}, path={video_path}")

    # Obtener tamaÃ±o del archivo
    try:
        file_size = Path(video_path).stat().st_size
        size_mb = file_size / (1024 * 1024)
        logger.info(f"📌 FILE SIZE: {size_mb:.2f} MB")

        # Si es > 50MB, enviar como documento directamente
        if size_mb > 50:
            return _send_video_as_document(chat_id, video_path, caption, size_mb)
    except Exception as e:
        logger.warning(f"📩ï¸ Error getting file size: {e}")

    # Intentar primero con sendVideo (hasta 20MB)
    try:
        result = _send_video_as_video(chat_id, video_path, caption)
        if result:
            return result
    except Exception as e:
        logger.warning(f"📩ï¸ Video too large for sendVideo: {e}")

    # Si falla, intentar como documento (hasta 50MB)
    try:
        _send_video_as_document(chat_id, video_path, caption)
    except Exception as e:
        logger.error(f"❌ Document upload failed: {e}")


def _send_video_as_video(chat_id: str, video_path: str, caption: str = None):
    """EnvÃ­a el video como tipo Video (hasta 20MB)."""
    path = Path(video_path)
    if not path.exists():
        logger.error(f"❌ FILE NOT FOUND: {video_path}")
        return False

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
        logger.info(f"📩 TG VIDEO RESPONSE: {response.status_code} - {response.text[:200]}")
        data = response.json()

        if data.get("ok"):
            _track_bot_message(chat_id, data.get("result", {}).get("message_id"))
            return True

        # Si es 413 (Request Entity Too Large), devolver False para intentar como documento
        if data.get("error_code") == 413:
            logger.warning(f"📩ï¸ Video too large ({data.get('description')})")
            return False

        return False


def _send_video_as_document(chat_id: str, video_path: str, caption: str = None, size_mb: float = None):
    """EnvÃ­a el video como Document (hasta 50MB)."""
    path = Path(video_path)
    if not path.exists():
        logger.error(f"❌ FILE NOT FOUND: {video_path}")
        return False

    # Si no se pasÃ³ size_mb, calcularlo
    if size_mb is None:
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
        except:
            size_mb = "desconocido"

    with path.open("rb") as video_file:
        response = requests.post(
            f"{BASE_URL}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": (caption or "")[:1024],
                "file_name": Path(video_path).name,
            },
            files={
                "document": video_file
            },
            timeout=120
        )
        logger.info(f"📩 TG DOCUMENT RESPONSE: {response.status_code} - {response.text[:200]}")
        data = response.json()

        if data.get("ok"):
            _track_bot_message(chat_id, data.get("result", {}).get("message_id"))
            return True

        # Si falla por tamaÃ±o > 50MB
        if data.get("error_code") == 413:
            logger.error(f"❌ Document too large ({size_mb:.2f} MB > 50 MB limit)")

            # Enviar mensaje al usuario con el peso del archivo
            from app.services.telegram_client import send_message

            msg = (
                f"📩ï¸ El video es muy pesado para enviarlo como documento.\n\n"
                f"📌 Peso: {size_mb:.2f} MB\n"
                f"📙 LÃ­mite Telegram: 50 MB\n\n"
                f"📙 Sugerencia: Usa un compresor de video o busca una versiÃ³n mÃ¡s corta."
            )

            send_message(chat_id, msg)
            return False

        return False



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
            data = response.json()
            if data.get("ok"):
                _track_bot_message(chat_id, data.get("result", {}).get("message_id"))
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
            data = response.json()
            if data.get("ok"):
                _track_bot_message(chat_id, data.get("result", {}).get("message_id"))
    except Exception as e:
        print("send_local_audio error:", e)


def send_message_with_buttons(chat_id: str, text: str, buttons: list, edit: bool = False, manga_menu: bool = False):
    """Envia un mensaje con botones o edita el ultimo si edit=True."""

    last_msg_id = None
    
    # Cleanup old manga menu if tracking is enabled
    if manga_menu:
        from app.core.state_manager import state_manager
        old_manga_id = state_manager.get_manga_menu_message(chat_id)
        if old_manga_id:
            try:
                requests.post(
                    f"{BASE_URL}/deleteMessage",
                    json={"chat_id": chat_id, "message_id": old_manga_id},
                    timeout=5
                )
                logger.info(f"🗑️ Eliminado menu manga anterior (msg {old_manga_id})")
            except Exception:
                pass
            finally:
                state_manager.clear_manga_menu_message(chat_id)

    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": buttons
        }
    }

    try:
        if edit:
            # Borrar el mensaje anterior antes de enviar el nuevo
            from app.core.chat_state import get_last_message_id, set_last_message_id

            last_msg_id = get_last_message_id(chat_id)
            logger.info(f"— EDIT MODE: chat={chat_id}, last_msg_id={last_msg_id}")

            if last_msg_id:
                # Primero borra el mensaje anterior
                resp = requests.post(
                    f"{BASE_URL}/deleteMessage",
                    json={"chat_id": chat_id, "message_id": last_msg_id},
                    timeout=5
                )
                logger.info(f"— DELETE RESPONSE: {resp.status_code} - {resp.text}")

            # Siempre usar sendMessage para enviar el nuevo mensaje despues de borrar
            endpoint = "sendMessage"
        else:
            endpoint = "sendMessage"

        r = requests.post(
            f"{BASE_URL}/{endpoint}",
            json=payload,
            timeout=10
        )

        # 🔑 DEBUG REAL (CLAVE)
        logger.info(f"📩 TELEGRAM {endpoint}: {r.status_code} - {r.text[:200]}")
        data = r.json()
        if data.get("ok"):
            message_id = data.get("result", {}).get("message_id") or last_msg_id

            # Si era edit pero no habia mensaje anterior, usar el nuevo message_id
            if edit and not last_msg_id:
                message_id = data.get("result", {}).get("message_id")

            _track_bot_message(chat_id, message_id)

            # Actualizar el ultimo message_id para la proxima edicion
            from app.core.chat_state import set_last_message_id
            set_last_message_id(chat_id, message_id)
            
            # Track manga menu messages for cleanup
            if manga_menu:
                from app.core.state_manager import state_manager
                state_manager.set_manga_menu_message(chat_id, message_id)
                logger.info(f"📌 Menu manga tracked: msg {message_id}")

            logger.info(f"✅ MESSAGE SAVED: msg_id={message_id}")
            return message_id


    except Exception as e:
        logger.error(f"❌ Error send buttons: {e}")
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


# Final Telegram size policy for local YouTube videos.
# <= 20 MB: sendVideo. > 20 MB and <= 50 MB: sendDocument. > 50 MB: reject.
def send_local_video(chat_id: str, video_path: str, caption: str = None):
    path = Path(video_path)
    if not path.exists():
        logger.error(f"FILE NOT FOUND: {video_path}")
        return False

    size_bytes = path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    logger.info(f"SEND VIDEO: chat={chat_id}, path={video_path}, size={size_mb:.2f} MB")

    if size_bytes > 50_000_000:
        send_message(
            chat_id,
            (
                "El video es demasiado pesado para Telegram.\n\n"
                f"Peso: {size_mb:.2f} MB\n"
                "Limite como documento: 50 MB"
            ),
        )
        return False

    if size_bytes > 20_000_000:
        return _send_video_as_document(chat_id, video_path, caption, size_mb)

    sent = _send_video_as_video(chat_id, video_path, caption)
    if sent:
        return sent

    return _send_video_as_document(chat_id, video_path, caption, size_mb)
