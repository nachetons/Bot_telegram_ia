from fastapi import APIRouter, Request
import threading
import logging
import traceback

from app.services.agent import agent
from app.services.telegram_client import (
    send_message,
    send_photo,
    send_images,
    send_chat_action,
    send_temp_message,
    edit_message,
    edit_message_with_buttons,
    delete_message,
    send_message_with_buttons,
    answer_callback_query
)
from app.tools.jellyfin import jellyfin
from app.core.callback_handler import handle_callback

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

pending_followups = {}
pending_followups_lock = threading.Lock()


def set_pending_followup(chat_id, intent):
    with pending_followups_lock:
        pending_followups[chat_id] = intent


def pop_pending_followup(chat_id):
    with pending_followups_lock:
        return pending_followups.pop(chat_id, None)


def clear_pending_followup(chat_id):
    with pending_followups_lock:
        pending_followups.pop(chat_id, None)


def run_direct_intent(intent, query):
    if intent == "movies":
        return jellyfin.run(query), ["jellyfin_tool"]

    if intent == "images":
        from app.tools.images import get_images

        images = get_images(query)
        return {"type": "images", "images": images}, ["images_tool"]

    if intent == "wiki":
        from app.tools.wiki import wikipedia

        result, sources = wikipedia(query)
        return result, sources

    if intent == "weather":
        from app.tools.weather import get_weather

        result, sources = get_weather(query)
        return result, sources

    return agent(query)


def _format_image_caption(image_result):
    if not isinstance(image_result, dict):
        return None

    parts = []
    title = image_result.get("title")
    domain = image_result.get("source_domain")

    if title:
        parts.append(title[:180])

    if domain:
        parts.append(f"Fuente: {domain}")

    return "\n".join(parts) if parts else None


def _build_image_buttons(images):
    buttons = []

    for index, image in enumerate(images[:3], start=1):
        if not isinstance(image, dict):
            continue

        source_url = image.get("source_url")
        if not source_url:
            continue

        domain = image.get("source_domain") or "fuente"
        buttons.append([
            {
                "text": f"🔗 Fuente {index} ({domain})",
                "url": source_url
            }
        ])

    return buttons


def _typing_indicator(chat_id, stop_event):
    while not stop_event.is_set():
        send_chat_action(chat_id, "typing")
        stop_event.wait(4)


def _placeholder_indicator(chat_id, message_id, stop_event):
    frames = [
        "Buscando",
        "Buscando.",
        "Buscando..",
        "Buscando..."
    ]
    index = 0

    while not stop_event.is_set() and message_id:
        edit_message(chat_id, message_id, frames[index])
        index = (index + 1) % len(frames)
        stop_event.wait(0.8)


# =======================
# PROCESS MAIN MESSAGE
# =======================
def _finalize_text_response(chat_id, result, placeholder_message_id=None, stop_placeholder=None):
    message_text = str(result)

    if stop_placeholder:
        stop_placeholder.set()

    if placeholder_message_id:
        edit_message(chat_id, placeholder_message_id, message_text)
    else:
        send_message(chat_id, message_text)


def _clear_placeholder(chat_id, placeholder_message_id=None, stop_placeholder=None):
    if stop_placeholder:
        stop_placeholder.set()

    if placeholder_message_id:
        delete_message(chat_id, placeholder_message_id)


def _needs_placeholder(text):
    normalized = (text or "").strip()

    if not normalized:
        return False

    incomplete_commands = ["/wiki", "/img", "/image", "/video", "/tiempo", "/weather"]
    return normalized not in incomplete_commands


def process(text, chat_id, placeholder_message_id=None):
    stop_typing = threading.Event()
    stop_placeholder = threading.Event()
    typing_thread = threading.Thread(
        target=_typing_indicator,
        args=(chat_id, stop_typing),
        daemon=True
    )
    placeholder_thread = None

    try:
        typing_thread.start()
        if placeholder_message_id:
            placeholder_thread = threading.Thread(
                target=_placeholder_indicator,
                args=(chat_id, placeholder_message_id, stop_placeholder),
                daemon=True
            )
            placeholder_thread.start()
        logger.info(f"📩 INPUT: {text}")

        result = None
        sources = []
        text = (text or "").strip()
        pending_intent = None

        if text.startswith("/"):
            clear_pending_followup(chat_id)
        else:
            pending_intent = pop_pending_followup(chat_id)

        if pending_intent:
            logger.info(f"↪️ USING PENDING INTENT: {pending_intent}")
            result, sources = run_direct_intent(pending_intent, text)

        # -----------------------
        # 🎯 COMANDOS DIRECTOS (SIN IA)
        # -----------------------
        elif text.startswith("/video"):
            query = text.replace("/video", "").strip()

            if not query:
                set_pending_followup(chat_id, "movies")
                _finalize_text_response(
                    chat_id,
                    "¿Qué película quieres ver?",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            result, sources = run_direct_intent("movies", query)

        elif text.startswith("/img") or text.startswith("/image"):
            query = text.replace("/img", "").replace("/image", "").strip()

            if not query:
                set_pending_followup(chat_id, "images")
                _finalize_text_response(
                    chat_id,
                    "¿Qué imagen quieres buscar?",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            result, sources = run_direct_intent("images", query)

        elif text.startswith("/wiki"):
            query = text.replace("/wiki", "").strip()

            if not query:
                set_pending_followup(chat_id, "wiki")
                _finalize_text_response(
                    chat_id,
                    "¿Qué quieres buscar en la wiki?",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            result, sources = run_direct_intent("wiki", query)

        elif text.startswith("/tiempo") or text.startswith("/weather"):
            command = "/tiempo" if text.startswith("/tiempo") else "/weather"
            query = text.replace(command, "", 1).strip()

            if not query:
                set_pending_followup(chat_id, "weather")
                _finalize_text_response(
                    chat_id,
                    "¿De qué ciudad quieres saber el tiempo?",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            result, sources = run_direct_intent("weather", query)

        # -----------------------
        # 🤖 MODO IA
        # -----------------------
        else:
            result, sources = agent(text)
            logger.info(f"🔗 SOURCES: {sources}")

        logger.info(f"🧠 RESULT: {result}")

        # -----------------------
        # ERROR MODE
        # -----------------------
        if isinstance(result, dict) and result.get("error"):
            _finalize_text_response(
                chat_id,
                result["error"],
                placeholder_message_id,
                stop_placeholder
            )
            return

        # -----------------------
        # IMAGE MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "images":
            images = result.get("images", [])

            if not images:
                _finalize_text_response(
                    chat_id,
                    "No encontré imágenes.",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            send_images(chat_id, images[:3])

            return

        # -----------------------
        # MENU MODE (LIBRARY / BUTTONS)
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "menu":
            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            send_message_with_buttons(
                chat_id,
                result.get("text", "Menú"),
                result.get("buttons", [])
            )
            return

        # -----------------------
        # VIDEO MODE (JELLYFIN)
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "video":

            title = result.get("title", "")
            image = result.get("image")
            item_id = result.get("item_id")
            audio_tracks = result.get("audio_tracks", [])

            fallback_url = jellyfin.get_stream_url(item_id, 0)

            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)

            # Carátula
            if image:
                send_photo(chat_id, image)

            # Título
            send_message(chat_id, f"🎬 {title}")

            # -----------------------
            # FORMATO IDIOMAS
            # -----------------------
            def format_lang(lang):
                if not lang:
                    return "Desconocido"

                lang = lang.lower()

                if lang.startswith("spa"):
                    return "🇪🇸 Español"
                elif lang.startswith("eng"):
                    return "🇬🇧 Inglés"
                elif lang.startswith("ger"):
                    return "🇩🇪 Alemán"
                elif lang.startswith("rus"):
                    return "🇷🇺 Ruso"
                else:
                    return f"🎧 {lang.upper()}"

            # -----------------------
            # BOTONES AUDIO
            # -----------------------
            buttons = []
            used_langs = set()

            for track in audio_tracks:
                lang = track.get("language")

                if not lang or lang in used_langs:
                    continue

                used_langs.add(lang)

                index = jellyfin.get_audio_stream_by_language(item_id, lang)

                if index is None:
                    continue

                url = jellyfin.get_stream_url(item_id, index)

                buttons.append([
                    {
                        "text": format_lang(lang),
                        "url": url
                    }
                ])

            # fallback
            if not buttons:
                buttons = [[
                    {
                        "text": "▶ Reproducir",
                        "url": fallback_url
                    }
                ]]

            send_message_with_buttons(
                chat_id,
                "Elige idioma:",
                buttons
            )

            return

        # -----------------------
        # TEXT MODE
        # -----------------------
        _finalize_text_response(chat_id, result, placeholder_message_id, stop_placeholder)

    except Exception:
        logger.error("❌ ERROR EN PROCESS:\n" + traceback.format_exc())
        _finalize_text_response(
            chat_id,
            "Ocurrió un error al procesar tu solicitud.",
            placeholder_message_id,
            stop_placeholder
        )
    finally:
        stop_typing.set()
        stop_placeholder.set()


# =======================
# WEBHOOK
# =======================
@router.post("/webhook")
async def webhook(req: Request):
    data = await req.json()

    logger.info(f"📩 RAW UPDATE: {data}")

    text = None
    chat_id = None

    # -----------------------
    # MESSAGE
    # -----------------------
    if "message" in data:
        text = data["message"].get("text")
        chat_id = data["message"]["chat"]["id"]


    # -----------------------
    # CALLBACK QUERY (NETFLIX UI)
    # -----------------------
    elif "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        callback_message_id = callback["message"]["message_id"]
        
        # 1. Responder al callback para quitar el relojito
        answer_callback_query(callback["id"])

        result = handle_callback(callback)

        if not result:
            return {"ok": True}

        # --- LÓGICA DE VIDEO (CON BOTONES DE AUDIO) ---
        if result.get("type") == "video":
            title = result.get("title", "")
            image = result.get("image")
            item_id = result.get("item_id")
            audio_tracks = result.get("audio_tracks", [])

            # 1. Enviar Carátula y Título
            if image:
                send_photo(chat_id, image)
            send_message(chat_id, f"🎬 {title}")

            # 2. Formateador de idiomas (puedes mover esto a una función externa para no repetir código)
            def format_lang(lang):
                if not lang: return "Desconocido"
                lang = lang.lower()
                if lang.startswith("spa"): return "🇪🇸 Español"
                elif lang.startswith("eng"): return "🇬🇧 Inglés"
                elif lang.startswith("ger"): return "🇩🇪 Alemán"
                elif lang.startswith("rus"): return "🇷🇺 Ruso"
                else: return f"🎧 {lang.upper()}"

            # 3. Generar botones de audio
            buttons = []
            used_langs = set()

            for track in audio_tracks:
                lang = track.get("language")
                if not lang or lang in used_langs: continue
                
                used_langs.add(lang)
                index = jellyfin.get_audio_stream_by_language(item_id, lang)
                
                if index is not None:
                    url = jellyfin.get_stream_url(item_id, index)
                    buttons.append([{"text": format_lang(lang), "url": url}])

            # Fallback si no hay tracks detectados
            if not buttons:
                fallback_url = jellyfin.get_stream_url(item_id, 0)
                buttons = [[{"text": "▶ Reproducir", "url": fallback_url}]]

            # 4. Enviar los botones
            send_message_with_buttons(chat_id, "Elige idioma:", buttons)
            return {"ok": True}

        # --- LÓGICA DE TEXTO (ERRORES / MENSAJES) ---
        if result.get("type") == "text":
            edit_message(
                chat_id,
                callback_message_id,
                result.get("text", "")
            )
            return {"ok": True}

        # --- LÓGICA DE MENÚ ---
        if result.get("type") == "menu":
            edit_message_with_buttons(
                chat_id,
                callback_message_id,
                result.get("text", "Menú"),
                result.get("buttons", [])
            )
            return {"ok": True}

    # -----------------------
    # EDITED MESSAGE
    # -----------------------
    elif "edited_message" in data:
        text = data["edited_message"].get("text")
        chat_id = data["edited_message"]["chat"]["id"]

    else:
        logger.warning("⚠️ Update ignorado")
        return {"ok": True}

    if not text or not chat_id:
        return {"ok": True}

    placeholder_message_id = None
    if _needs_placeholder(text):
        placeholder_message_id = send_temp_message(chat_id, "Buscando...")
        send_chat_action(chat_id, "typing")

    threading.Thread(
        target=process,
        args=(text, chat_id, placeholder_message_id)
    ).start()

    return {"ok": True}
