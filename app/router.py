from fastapi import APIRouter, Request
import threading
import logging
import traceback

from app.services.agent import agent
from app.services.telegram_client import (
    send_message,
    send_photo,
    send_message_with_buttons,
    answer_callback_query
)
from app.tools.jellyfin import jellyfin
from app.core.callback_handler import handle_callback

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


# =======================
# PROCESS MAIN MESSAGE
# =======================
def process(text, chat_id):
    try:
        logger.info(f"📩 INPUT: {text}")

        result = None
        sources = []

        # -----------------------
        # 🎯 COMANDOS DIRECTOS (SIN IA)
        # -----------------------
        if text.startswith("/video"):
            query = text.replace("/video", "").strip()
            result = jellyfin.run(query)

        elif text.startswith("/img") or text.startswith("/image"):
            from app.tools.images import get_images
            query = text.replace("/img", "").replace("/image", "").strip()
            images = get_images(query)
            result = {"type": "images", "images": images}

        elif text.startswith("/wiki"):
            from app.tools.wiki import wikipedia
            query = text.replace("/wiki", "").strip()
            result, _ = wikipedia(query)

        elif text.startswith("/tiempo") or text.startswith("/weather"):
            from app.tools.weather import get_weather
            result, _ = get_weather(text)

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
            send_message(chat_id, result["error"])
            return

        # -----------------------
        # IMAGE MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "images":
            images = result.get("images", [])

            if not images:
                send_message(chat_id, "No encontré imágenes.")
                return

            for img in images[:3]:
                send_photo(chat_id, img)

            return

        # -----------------------
        # MENU MODE (LIBRARY / BUTTONS)
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "menu":
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
        send_message(chat_id, str(result))

    except Exception:
        logger.error("❌ ERROR EN PROCESS:\n" + traceback.format_exc())
        send_message(chat_id, "Ocurrió un error al procesar tu solicitud.")


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
            send_message(chat_id, result.get("text", ""))
            return {"ok": True}

        # --- LÓGICA DE MENÚ ---
        if result.get("type") == "menu":
            send_message_with_buttons(
                chat_id,
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

    threading.Thread(target=process, args=(text, chat_id)).start()

    return {"ok": True}
