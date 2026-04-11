from fastapi import APIRouter, Request
import threading
import logging
import traceback
from queue import Queue

from app.services.agent import agent
from app.services.telegram_client import (
    send_message,
    send_local_audio,
    send_photo,
    send_photo_with_buttons,
    send_images,
    send_chat_action,
    send_local_video,
    send_temp_message,
    edit_message,
    edit_message_with_buttons,
    delete_message,
    send_message_with_buttons,
    answer_callback_query,
    download_telegram_file,
)
from app.tools.jellyfin import jellyfin
from app.core.callback_handler import handle_callback

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

pending_followups = {}
pending_followups_lock = threading.Lock()
playlist_sessions = {}
playlist_sessions_lock = threading.Lock()
translate_sessions = {}
translate_sessions_lock = threading.Lock()
translate_results = {}
translate_results_lock = threading.Lock()
chat_queues = {}
chat_workers = {}
chat_queue_guard = threading.Lock()


def set_pending_followup(chat_id, intent):
    with pending_followups_lock:
        pending_followups[chat_id] = intent


def pop_pending_followup(chat_id):
    with pending_followups_lock:
        return pending_followups.pop(chat_id, None)


def clear_pending_followup(chat_id):
    with pending_followups_lock:
        pending_followups.pop(chat_id, None)


def set_playlist_session(chat_id, action, playlist_name):
    with playlist_sessions_lock:
        playlist_sessions[chat_id] = {
            "action": action,
            "playlist": playlist_name,
        }


def get_playlist_session(chat_id):
    with playlist_sessions_lock:
        return playlist_sessions.get(chat_id)


def clear_playlist_session(chat_id):
    with playlist_sessions_lock:
        playlist_sessions.pop(chat_id, None)


def set_translate_session(chat_id, step, text_value=None):
    with translate_sessions_lock:
        translate_sessions[chat_id] = {
            "step": step,
            "text": text_value or "",
        }


def get_translate_session(chat_id):
    with translate_sessions_lock:
        return translate_sessions.get(chat_id)


def clear_translate_session(chat_id):
    with translate_sessions_lock:
        translate_sessions.pop(chat_id, None)


def set_translate_result(chat_id, payload):
    with translate_results_lock:
        translate_results[chat_id] = payload


def get_translate_result(chat_id):
    with translate_results_lock:
        return translate_results.get(chat_id)


def _get_chat_queue(chat_id):
    with chat_queue_guard:
        queue = chat_queues.get(chat_id)
        if queue is None:
            queue = Queue()
            chat_queues[chat_id] = queue
        return queue


def _ensure_chat_worker(chat_id):
    with chat_queue_guard:
        worker = chat_workers.get(chat_id)
        if worker and worker.is_alive():
            return

        worker = threading.Thread(
            target=_chat_worker_loop,
            args=(chat_id,),
            daemon=True
        )
        chat_workers[chat_id] = worker
        worker.start()


def _enqueue_chat_message(chat_id, text, placeholder_message_id=None):
    queue = _get_chat_queue(chat_id)
    queue.put((text, placeholder_message_id))
    _ensure_chat_worker(chat_id)


def _chat_worker_loop(chat_id):
    queue = _get_chat_queue(chat_id)

    while True:
        text, placeholder_message_id = queue.get()
        try:
            _process_locked(text, chat_id, placeholder_message_id)
        finally:
            queue.task_done()


def _playlist_manage_buttons(playlist_name):
    return [
        [
            {"text": "➕ Añadir", "callback_data": f"playlist_action:add:{playlist_name}"},
            {"text": "🗑 Quitar canción", "callback_data": f"playlist_action:remove:{playlist_name}"},
        ],
        [
            {"text": "📄 Ver", "callback_data": f"playlist_action:view:{playlist_name}"},
            {"text": "▶ Reproducir", "callback_data": f"playlist_action:play:{playlist_name}"},
        ],
        [
            {"text": "❌ Borrar playlist", "callback_data": f"playlist_action:delete:{playlist_name}"},
        ],
    ]


def _playlist_picker_menu(chat_id):
    from app.tools.music_local import playlist_names

    names = playlist_names(chat_id)
    if not names:
        return (
            "No tienes playlists creadas todavía.\n"
            "Crea una con /playlist crear <nombre>"
        )

    buttons = [
        [{"text": name, "callback_data": f"playlist_manage:{name}"}]
        for name in names[:30]
    ]
    return {
        "type": "menu",
        "text": "¿Qué playlist quieres utilizar?",
        "buttons": buttons,
    }


def _playlist_remove_menu(chat_id, playlist_name):
    from app.tools.music_local import playlist_tracks

    tracks = playlist_tracks(chat_id, playlist_name)
    if tracks is None:
        return {"type": "text", "text": f"No existe la playlist '{playlist_name}'."}
    if not tracks:
        return {"type": "text", "text": f"La playlist '{playlist_name}' está vacía."}

    buttons = []
    for index, track in enumerate(tracks[:20], start=1):
        title = track.get("title", "Sin título")[:40]
        buttons.append([
            {
                "text": f"🗑 {index}. {title}",
                "callback_data": f"playlist_remove_item:{playlist_name}:{index}",
            }
        ])

    return {
        "type": "menu",
        "text": f"¿Qué canción quieres quitar de '{playlist_name}'?",
        "buttons": buttons,
    }


def _playlist_manage_menu(playlist_name, extra_text=None):
    text = f"Playlist seleccionada: {playlist_name}\n¿Qué quieres hacer?"
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    return {
        "type": "menu",
        "text": text,
        "buttons": _playlist_manage_buttons(playlist_name),
    }


def _coerce_playlist_feedback(value):
    if value is None:
        return "No pude completar la operación sobre la playlist."

    if isinstance(value, dict):
        if value.get("error"):
            return str(value.get("error"))
        if value.get("type") == "text":
            return str(value.get("text", "No pude completar la operación sobre la playlist."))
        if value.get("type") == "youtube":
            return "Encontré resultados de YouTube, pero no pude guardar la canción en la playlist."
        if value.get("type") == "menu":
            return "La operación devolvió un menú inesperado y no se guardó la canción."
        return "Recibí una respuesta inesperada al guardar la canción."

    return str(value)


def _start_message():
    return (
        "Bienvenido. Cada chat mantiene su propio contexto, playlists y seguimiento temporal.\n\n"
        "Comandos principales:\n"
        "/video <pelicula> - buscar una pelicula en Jellyfin\n"
        "/wiki <tema> - buscar en Wikipedia\n"
        "/img <tema> - buscar imagenes\n"
        "/weather <ciudad> - consultar el tiempo\n"
        "/youtube <busqueda> - buscar y enviar un video\n"
        "/music <cancion> - buscar y enviar audio\n"
        "/translate <destino> | <texto> - traducir texto\n"
        "/playlist - gestionar tus playlists\n\n"
        "Ejemplos:\n"
        "/music Danza Kuduro\n"
        "/translate en | hola mundo\n"
        "/youtube hall of fame\n"
        "/playlist crear motivacion"
    )


def _helper_message():
    return (
        "Guía rápida del bot:\n\n"
        "/start - bienvenida y uso básico\n"
        "/helper - ver todos los comandos\n"
        "/video <pelicula> - buscar y reproducir una película de Jellyfin\n"
        "/wiki <tema> - buscar en Wikipedia\n"
        "/img <tema> - buscar imágenes\n"
        "/weather <ciudad> - consultar el tiempo\n"
        "/youtube <búsqueda> - buscar y enviar un vídeo\n"
        "/music <canción> - buscar y enviar audio\n"
        "/translate <destino> | <texto> - traducir texto\n"
        "/translate <origen> | <destino> | <texto> - traducir indicando idioma origen\n"
        "/playlist - abrir el gestor interactivo de playlists\n"
        "/playlist crear <nombre> - crear playlist\n"
        "/playlist add <nombre> | <canción> - añadir canción\n"
        "/playlist ver <nombre> - ver canciones\n"
        "/playlist play <nombre> - reproducir la primera canción\n"
        "/playlist remove <nombre> | <posición> - quitar una canción\n"
        "/playlist borrar <nombre> - borrar playlist"
    )


def run_direct_intent(intent, query, chat_id=None):
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

    if intent == "youtube":
        from app.tools.youtube import download_best_youtube_video

        result = download_best_youtube_video(query)
        return result, ["youtube_tool"]

    if intent == "music":
        from app.tools.music_local import music_run

        result = music_run(query, chat_id)
        return result, ["music_tool"]

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

    incomplete_commands = ["/start", "/helper", "/wiki", "/img", "/image", "/video", "/tiempo", "/weather", "/youtube", "/music", "/playlist", "/translate"]
    return normalized not in incomplete_commands


def _handle_translate_voice_input(chat_id, file_id, file_unique_id=None):
    from app.tools.translate import translate_language_buttons
    from app.tools.transcription import temp_voice_path, transcribe_audio_file

    local_path = download_telegram_file(file_id, str(temp_voice_path(chat_id, file_unique_id)))
    if not local_path:
        return "No pude descargar la nota de voz."

    transcript = transcribe_audio_file(local_path)
    if transcript.get("error"):
        return transcript["error"]

    detected_text = transcript.get("text", "").strip()
    if not detected_text:
        return "No pude entender la nota de voz."

    set_translate_session(chat_id, "await_language", detected_text)
    return {
        "type": "menu",
        "text": (
            f"Texto detectado:\n{detected_text}\n\n"
            "¿A qué idioma quieres traducirlo?"
        ),
        "buttons": translate_language_buttons(),
    }


def _extract_playlist_batch_queries(playlist_name: str, raw_query_block: str):
    queries = []
    normalized_playlist = (playlist_name or "").strip().lower()

    for raw_line in (raw_query_block or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lowered = line.lower()
        prefix = f"/playlist add {normalized_playlist} |"
        if lowered.startswith(prefix):
            line = line[len(prefix):].strip()
        elif lowered.startswith("/playlist add ") and "|" in line:
            _, line = line.split("|", 1)
            line = line.strip()

        if line:
            queries.append(line)

    return queries


def process(text, chat_id, placeholder_message_id=None):
    _enqueue_chat_message(chat_id, text, placeholder_message_id)


def _process_locked(text, chat_id, placeholder_message_id=None):
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
        playlist_session = None

        if text.startswith("/"):
            clear_pending_followup(chat_id)
            clear_playlist_session(chat_id)
            clear_translate_session(chat_id)
        else:
            pending_intent = pop_pending_followup(chat_id)
            playlist_session = get_playlist_session(chat_id)

        if playlist_session and not text.startswith("/"):
            from app.tools.music_local import playlist_add

            if playlist_session.get("action") == "add":
                playlist_name = playlist_session.get("playlist")
                raw_add_result = playlist_add(chat_id, playlist_name, text)
                logger.info(
                    "🎵 PLAYLIST ADD RESULT TYPE: %s | VALUE PREVIEW: %s",
                    type(raw_add_result).__name__,
                    str(raw_add_result)[:300]
                )
                add_result = _coerce_playlist_feedback(raw_add_result)
                result = _playlist_manage_menu(
                    playlist_name,
                    add_result + "\nPuedes seguir añadiendo canciones o elegir otra acción."
                )
                sources = ["music_tool"]

        elif get_translate_session(chat_id) and not text.startswith("/"):
            from app.tools.translate import translate_language_buttons

            session = get_translate_session(chat_id)
            if session.get("step") == "await_text":
                set_translate_session(chat_id, "await_language", text)
                result = {
                    "type": "menu",
                    "text": "¿A qué idioma quieres traducirlo?",
                    "buttons": translate_language_buttons(),
                }
                sources = ["translate_tool"]

        elif pending_intent:
            logger.info(f"↪️ USING PENDING INTENT: {pending_intent}")
            result, sources = run_direct_intent(pending_intent, text, chat_id)

        # -----------------------
        # 🎯 COMANDOS DIRECTOS (SIN IA)
        # -----------------------
        elif text.startswith("/start"):
            clear_pending_followup(chat_id)
            clear_playlist_session(chat_id)
            clear_translate_session(chat_id)
            result = _start_message()
            sources = []

        elif text.startswith("/helper") or text.startswith("/help"):
            clear_pending_followup(chat_id)
            clear_playlist_session(chat_id)
            clear_translate_session(chat_id)
            result = _helper_message()
            sources = []

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

            result, sources = run_direct_intent("movies", query, chat_id)

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

            result, sources = run_direct_intent("images", query, chat_id)

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

            result, sources = run_direct_intent("wiki", query, chat_id)

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

            result, sources = run_direct_intent("weather", query, chat_id)

        elif text.startswith("/youtube"):
            query = text.replace("/youtube", "", 1).strip()

            if not query:
                set_pending_followup(chat_id, "youtube")
                _finalize_text_response(
                    chat_id,
                    "¿Qué vídeo quieres buscar en YouTube?",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            result, sources = run_direct_intent("youtube", query, chat_id)

        elif text.startswith("/music"):
            query = text.replace("/music", "", 1).strip()
            result, sources = run_direct_intent("music", query, chat_id)

        elif text.startswith("/translate"):
            from app.tools.translate import build_translate_result_menu, translate_language_buttons, translate_payload

            query = text.replace("/translate", "", 1).strip()
            if not query:
                set_translate_session(chat_id, "await_text")
                result = "¿Qué texto quieres traducir?"
            elif "|" not in query:
                set_translate_session(chat_id, "await_language", query)
                result = {
                    "type": "menu",
                    "text": "¿A qué idioma quieres traducirlo?",
                    "buttons": translate_language_buttons(),
                }
            else:
                payload = translate_payload(query)
                if payload.get("error"):
                    result = payload["error"]
                else:
                    set_translate_result(chat_id, payload)
                    result = build_translate_result_menu(payload)
            sources = ["translate_tool"]

        elif text.startswith("/playlist"):
            from app.tools.music_local import (
                playlist_add,
                playlist_add_many,
                playlist_create,
                playlist_delete,
                playlist_list,
                playlist_play,
                playlist_remove,
                playlist_view,
            )

            command = text.replace("/playlist", "", 1).strip()

            if not command:
                result = _playlist_picker_menu(chat_id)
                sources = ["music_tool"]
            elif command.startswith("crear "):
                result = playlist_create(chat_id, command[6:].strip())
                sources = ["music_tool"]
            elif command.startswith("add "):
                payload = command[4:].strip()
                if "|" not in payload:
                    result = "Usa este formato: /playlist add nombre | canción"
                else:
                    playlist_name, track_query = [part.strip() for part in payload.split("|", 1)]
                    batch_queries = _extract_playlist_batch_queries(playlist_name, track_query)
                    if len(batch_queries) > 1:
                        result = playlist_add_many(chat_id, playlist_name, batch_queries)
                    else:
                        single_query = batch_queries[0] if batch_queries else track_query
                        raw_result = playlist_add(chat_id, playlist_name, single_query)
                        logger.info(
                            "🎵 PLAYLIST DIRECT ADD RESULT TYPE: %s | VALUE PREVIEW: %s",
                            type(raw_result).__name__,
                            str(raw_result)[:300]
                        )
                        result = _coerce_playlist_feedback(raw_result)
                sources = ["music_tool"]
            elif command.startswith("ver "):
                result = playlist_view(chat_id, command[4:].strip())
                sources = ["music_tool"]
            elif command.startswith("play "):
                result = playlist_play(chat_id, command[5:].strip())
                sources = ["music_tool"]
            elif command == "listas":
                result = playlist_list(chat_id)
                sources = ["music_tool"]
            elif command.startswith("remove "):
                payload = command[7:].strip()
                if "|" not in payload:
                    result = "Usa este formato: /playlist remove nombre | posicion"
                else:
                    playlist_name, index_value = [part.strip() for part in payload.split("|", 1)]
                    result = playlist_remove(chat_id, playlist_name, index_value)
                sources = ["music_tool"]
            elif command.startswith("borrar "):
                result = playlist_delete(chat_id, command[7:].strip())
                sources = ["music_tool"]
            else:
                result = (
                    "Comandos de playlist:\n"
                    "- /playlist listas\n"
                    "- /playlist crear <nombre>\n"
                    "- /playlist add <nombre> | <canción>\n"
                    "- /playlist remove <nombre> | <posición>\n"
                    "- /playlist borrar <nombre>\n"
                    "- /playlist ver <nombre>\n"
                    "- /playlist play <nombre>"
                )
                sources = ["music_tool"]

        elif text.startswith("/"):
            result = "Ese comando no existe. Usa /helper para ver los comandos disponibles."
            sources = []

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
        # YOUTUBE MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "youtube":
            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)

            thumbnail = result.get("thumbnail")
            caption = result.get("caption") or "Resultado de YouTube"
            buttons = result.get("buttons", [])
            text_summary = result.get("text", "")

            if thumbnail and buttons:
                send_photo_with_buttons(chat_id, thumbnail, caption, buttons)
                if text_summary:
                    send_message(chat_id, text_summary)
            elif thumbnail:
                send_photo(chat_id, thumbnail, caption)
                if text_summary:
                    send_message(chat_id, text_summary)
            else:
                send_message_with_buttons(chat_id, text_summary or "Resultados de YouTube", buttons)

            return

        # -----------------------
        # LOCAL VIDEO MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "local_video":
            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            send_local_video(
                chat_id,
                result.get("path", ""),
                result.get("caption", "")
            )
            return

        if isinstance(result, dict) and result.get("type") == "text":
            _finalize_text_response(
                chat_id,
                result.get("text", ""),
                placeholder_message_id,
                stop_placeholder
            )
            return

        # -----------------------
        # LOCAL AUDIO MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "local_audio":
            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            send_local_audio(
                chat_id,
                result.get("path", ""),
                result.get("title", ""),
                result.get("performer", "")
            )
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
        voice = data["message"].get("voice")

        if voice and chat_id:
            translate_session = get_translate_session(chat_id)
            if translate_session and translate_session.get("step") == "await_text":
                result = _handle_translate_voice_input(
                    chat_id,
                    voice.get("file_id"),
                    voice.get("file_unique_id")
                )

                if isinstance(result, dict) and result.get("type") == "menu":
                    send_message_with_buttons(
                        chat_id,
                        result.get("text", ""),
                        result.get("buttons", []),
                    )
                else:
                    send_message(chat_id, str(result))
                return {"ok": True}

            send_message(chat_id, "Si quieres traducir una nota de voz, usa primero /translate y luego envíamela.")
            return {"ok": True}


    # -----------------------
    # CALLBACK QUERY (NETFLIX UI)
    # -----------------------
    elif "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        callback_message_id = callback["message"]["message_id"]
        callback_data = callback.get("data", "")

        if callback_data.startswith("playlist_manage:"):
            playlist_name = callback_data.split(":", 1)[1]
            answer_callback_query(callback["id"])
            menu = _playlist_manage_menu(playlist_name)
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data.startswith("playlist_action:"):
            _, action, playlist_name = callback_data.split(":", 2)
            answer_callback_query(callback["id"])

            if action == "add":
                set_playlist_session(chat_id, "add", playlist_name)
                edit_message(
                    chat_id,
                    callback_message_id,
                    (
                        f"Escribe la canción que quieres añadir a '{playlist_name}'.\n"
                        "Después puedes seguir enviando más canciones y las iré añadiendo."
                    ),
                )
                return {"ok": True}

            if action == "remove":
                menu = _playlist_remove_menu(chat_id, playlist_name)
                if menu.get("type") == "menu":
                    edit_message_with_buttons(
                        chat_id,
                        callback_message_id,
                        menu.get("text", ""),
                        menu.get("buttons", []),
                    )
                else:
                    edit_message(chat_id, callback_message_id, menu.get("text", ""))
                return {"ok": True}

            if action == "view":
                from app.tools.music_local import playlist_view

                result = playlist_view(chat_id, playlist_name)
                if isinstance(result, dict) and result.get("type") == "menu":
                    edit_message_with_buttons(
                        chat_id,
                        callback_message_id,
                        result.get("text", ""),
                        result.get("buttons", []),
                    )
                else:
                    edit_message(chat_id, callback_message_id, str(result))
                return {"ok": True}

            if action == "play":
                from app.tools.music_local import playlist_play

                send_chat_action(chat_id, "upload_audio")
                result = playlist_play(chat_id, playlist_name)
                if isinstance(result, dict) and result.get("type") == "local_audio":
                    send_local_audio(
                        chat_id,
                        result.get("path", ""),
                        result.get("title", ""),
                        result.get("performer", ""),
                    )
                else:
                    edit_message(chat_id, callback_message_id, str(result))
                return {"ok": True}

            if action == "delete":
                from app.tools.music_local import playlist_delete

                clear_playlist_session(chat_id)
                result = playlist_delete(chat_id, playlist_name)
                edit_message(chat_id, callback_message_id, str(result))
                return {"ok": True}

        if callback_data.startswith("playlist_remove_item:"):
            _, playlist_name, index_value = callback_data.split(":", 2)
            from app.tools.music_local import playlist_remove

            answer_callback_query(callback["id"])
            result = playlist_remove(chat_id, playlist_name, index_value)
            menu = _playlist_manage_menu(playlist_name, str(result))
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data.startswith("translate_lang:"):
            from app.tools.translate import build_translate_result_menu, generate_translate_audio, translate_payload

            target_lang = callback_data.split(":", 1)[1]
            session = get_translate_session(chat_id)
            answer_callback_query(callback["id"])

            if not session or session.get("step") != "await_language" or not session.get("text"):
                edit_message(chat_id, callback_message_id, "No tengo ningún texto pendiente para traducir. Usa /translate.")
                return {"ok": True}

            payload = translate_payload(f"auto | {target_lang} | {session.get('text')}")
            clear_translate_session(chat_id)
            if payload.get("error"):
                edit_message(chat_id, callback_message_id, payload["error"])
                return {"ok": True}

            set_translate_result(chat_id, payload)
            menu = build_translate_result_menu(payload)
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data.startswith("translate_voice:"):
            from app.tools.translate import generate_translate_audio

            answer_callback_query(callback["id"], "Generando audio...")
            payload = get_translate_result(chat_id)
            if not payload or not payload.get("translated_text"):
                edit_message(chat_id, callback_message_id, "No tengo una traducción reciente para pronunciar. Usa /translate.")
                return {"ok": True}

            audio_result = generate_translate_audio(payload.get("translated_text"), payload.get("target"))
            if audio_result.get("error"):
                edit_message(chat_id, callback_message_id, audio_result["error"])
                return {"ok": True}

            send_chat_action(chat_id, "upload_audio")
            send_local_audio(
                chat_id,
                audio_result.get("path", ""),
                audio_result.get("title", ""),
                audio_result.get("performer", ""),
            )
            return {"ok": True}
        
        # 1. Responder al callback para quitar el relojito
        if callback_data.startswith("youtube_play:") or callback_data.startswith("music_play:"):
            if callback_data.startswith("music_play:"):
                answer_callback_query(callback["id"], "Preparando audio para Telegram...")
                send_chat_action(chat_id, "upload_audio")
            else:
                answer_callback_query(callback["id"], "Preparando vídeo para Telegram...")
                send_chat_action(chat_id, "upload_video")
        else:
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

        if result.get("type") == "local_video":
            send_local_video(
                chat_id,
                result.get("path", ""),
                result.get("caption", "")
            )
            return {"ok": True}

        if result.get("type") == "local_audio":
            send_local_audio(
                chat_id,
                result.get("path", ""),
                result.get("title", ""),
                result.get("performer", "")
            )
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

    process(text, chat_id, placeholder_message_id)

    return {"ok": True}
