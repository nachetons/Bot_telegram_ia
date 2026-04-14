from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
import threading
import logging
import traceback
from queue import Queue
from urllib.parse import urljoin, urlparse

import requests

from app.services.agent import agent
from app.services.telegram_client import (
    send_message,
    send_local_audio,
    send_local_document,
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
)
from app.config import YOUTUBE_SEND_AS_DOCUMENT
from app.tools.jellyfin import jellyfin
from app.core.callback_handler import handle_callback
from app.core.command_flow import handle_slash_command
from app.core.direct_intents import run_direct_intent
from app.core.translate_flow import handle_translate_voice_input
from app.core.chat_state import (
    clear_base_chat_state,
    clear_pending_followup,
    clear_playlist_session,
    clear_translate_session,
    clear_translate_result,
    clear_wallapop_result_session,
    clear_wallapop_session,
    get_playlist_session,
    get_translate_result,
    get_translate_session,
    get_wallapop_result_session,
    get_wallapop_session,
    pop_pending_followup,
    set_pending_followup,
    set_playlist_session,
    set_translate_result,
    set_translate_session,
    set_wallapop_result_session,
    set_wallapop_session,
)
from app.utils.playlist_ui import (
    coerce_playlist_feedback,
    playlist_manage_menu,
    playlist_remove_menu,
)
from app.utils.wallapop_ui import (
    WALLAPOP_UI_PAGE_SIZE,
    wallapop_apply_order,
    wallapop_build_result_session,
    wallapop_condition_buttons,
    wallapop_item_caption,
    wallapop_order_buttons,
    wallapop_radius_buttons,
    wallapop_results_menu,
    wallapop_total_loaded_pages,
)
from app.utils.jellyfin_ui import build_jellyfin_audio_buttons
from app.utils.response_flow import (
    clear_placeholder,
    finalize_text_response,
    placeholder_indicator,
    typing_indicator,
)

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


def _rewrite_jellyfin_playlist(content: str, current_target: str):
    current_full_url = urljoin(f"{jellyfin.base_url}/", current_target.lstrip("/"))
    rewritten_lines = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            rewritten_lines.append(raw_line)
            continue

        resolved = urljoin(current_full_url, line)
        parsed = urlparse(resolved)
        relative_target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        rewritten_lines.append(jellyfin.build_proxy_url(relative_target, expires_in=3600))

    return "\n".join(rewritten_lines)


def _stream_remote_response(remote_response):
    try:
        for chunk in remote_response.iter_content(chunk_size=8192):
            if chunk:
                yield chunk
    finally:
        remote_response.close()


@router.get("/proxy/jellyfin/raw/{encoded_target}")
async def proxy_jellyfin_raw(encoded_target: str, exp: int, sig: str):
    if not jellyfin.verify_proxy_request(encoded_target, exp, sig):
        return Response("Forbidden", status_code=403)

    try:
        relative_target = jellyfin.decode_proxy_target(encoded_target)
    except Exception:
        return Response("Invalid target", status_code=400)

    try:
        remote_response = requests.get(
            f"{jellyfin.base_url}{relative_target}",
            headers=jellyfin._headers(),
            stream=True,
            timeout=30,
        )
        remote_response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Jellyfin proxy error: %s", exc)
        return Response("Upstream error", status_code=502)

    content_type = remote_response.headers.get("Content-Type", "application/octet-stream")
    if ".m3u8" in relative_target or "mpegurl" in content_type.lower():
        playlist_text = remote_response.text
        remote_response.close()
        rewritten = _rewrite_jellyfin_playlist(playlist_text, relative_target)
        return Response(rewritten, media_type=content_type)

    passthrough_headers = {}
    if remote_response.headers.get("Content-Length"):
        passthrough_headers["Content-Length"] = remote_response.headers["Content-Length"]
    if remote_response.headers.get("Accept-Ranges"):
        passthrough_headers["Accept-Ranges"] = remote_response.headers["Accept-Ranges"]

    return StreamingResponse(
        _stream_remote_response(remote_response),
        media_type=content_type,
        headers=passthrough_headers,
    )

chat_queues = {}
chat_workers = {}
chat_queue_guard = threading.Lock()


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


def _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks):
    buttons = build_jellyfin_audio_buttons(item_id, audio_tracks)
    caption = f"🎬 {title}\n\nElige idioma:"

    if image:
        send_photo_with_buttons(chat_id, image, caption, buttons)
    else:
        send_message_with_buttons(chat_id, caption, buttons)


def _needs_placeholder(text):
    normalized = (text or "").strip()

    if not normalized:
        return False

    incomplete_commands = ["/start", "/helper", "/library", "/menu", "/catalog", "/wiki", "/img", "/image", "/video", "/tiempo", "/weather", "/youtube", "/music", "/playlist", "/translate", "/wallapop"]
    return normalized not in incomplete_commands


def _should_skip_placeholder(chat_id, text):
    normalized = (text or "").strip()
    if not normalized or normalized.startswith("/"):
        return False

    wallapop_session = get_wallapop_session(chat_id)
    if wallapop_session and wallapop_session.get("step") in {"await_query", "await_price", "await_location"}:
        return True

    translate_session = get_translate_session(chat_id)
    if translate_session and translate_session.get("step") == "await_text":
        return True

    return False


def process(text, chat_id, placeholder_message_id=None):
    _enqueue_chat_message(chat_id, text, placeholder_message_id)


def _process_locked(text, chat_id, placeholder_message_id=None):
    stop_typing = threading.Event()
    stop_placeholder = threading.Event()
    typing_thread = threading.Thread(
        target=typing_indicator,
        args=(chat_id, stop_typing),
        daemon=True
    )
    placeholder_thread = None

    try:
        typing_thread.start()
        if placeholder_message_id:
            placeholder_thread = threading.Thread(
                target=placeholder_indicator,
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
            clear_base_chat_state(chat_id)
            clear_wallapop_session(chat_id)
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
                add_result = coerce_playlist_feedback(raw_add_result)
                result = playlist_manage_menu(
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

        elif get_wallapop_session(chat_id) and not text.startswith("/"):
            session = get_wallapop_session(chat_id)
            step = session.get("step")

            if step == "await_query":
                session["query"] = text.strip()
                session["step"] = "await_condition"
                set_wallapop_session(chat_id, session)
                result = {
                    "type": "menu",
                    "text": (
                        f"Producto: {session['query']}\n\n"
                        "¿Qué estado quieres filtrar?"
                    ),
                    "buttons": wallapop_condition_buttons(),
                }
                sources = ["wallapop_tool"]
            elif step == "await_price":
                lowered = text.strip().lower()
                if lowered not in {"skip", "saltar", "omitir"}:
                    try:
                        price_text = text.replace("€", "").strip()
                        if "-" in price_text:
                            min_raw, max_raw = [part.strip() for part in price_text.split("-", 1)]
                            session["min_price"] = int(float(min_raw)) if min_raw else None
                            session["max_price"] = int(float(max_raw)) if max_raw else None
                        else:
                            session["max_price"] = int(float(price_text))
                    except ValueError:
                        result = "No entendí el precio. Usa un formato como `50-200`, `300` o escribe `skip`."
                        sources = ["wallapop_tool"]
                        logger.info(f"🧠 RESULT: {result}")
                        finalize_text_response(chat_id, result, placeholder_message_id, stop_placeholder)
                        return
                session["step"] = "await_location"
                set_wallapop_session(chat_id, session)
                result = (
                    "Indica una localidad para buscar cerca, o escribe `skip` si no quieres filtrar por ubicación."
                )
                sources = ["wallapop_tool"]
            elif step == "await_location":
                lowered = text.strip().lower()
                if lowered in {"skip", "saltar", "omitir"}:
                    session["location_label"] = ""
                    session["distance_km"] = None
                    session["step"] = "await_order"
                    set_wallapop_session(chat_id, session)
                    result = {
                        "type": "menu",
                        "text": "¿Cómo quieres ordenar los resultados?",
                        "buttons": wallapop_order_buttons(),
                    }
                else:
                    session["location_label"] = text.strip()
                    session["step"] = "await_radius"
                    set_wallapop_session(chat_id, session)
                    result = {
                        "type": "menu",
                        "text": f"Ubicación: {session['location_label']}\n\n¿Qué radio quieres usar?",
                        "buttons": wallapop_radius_buttons(),
                    }
                sources = ["wallapop_tool"]

        elif pending_intent:
            logger.info(f"↪️ USING PENDING INTENT: {pending_intent}")
            result, sources = run_direct_intent(pending_intent, text, chat_id)

        else:
            handled, result, sources = handle_slash_command(text, chat_id)
            if not handled:
                result, sources = agent(text)
                logger.info(f"🔗 SOURCES: {sources}")

        logger.info(f"🧠 RESULT: {result}")

        # -----------------------
        # ERROR MODE
        # -----------------------
        if isinstance(result, dict) and result.get("error"):
            finalize_text_response(
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
                finalize_text_response(
                    chat_id,
                    "No encontré imágenes.",
                    placeholder_message_id,
                    stop_placeholder
                )
                return

            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            send_images(chat_id, images[:6])

            return

        # -----------------------
        # YOUTUBE MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "youtube":
            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)

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

        if isinstance(result, dict) and result.get("type") == "wallapop":
            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            image = result.get("image")
            if image:
                send_photo_with_buttons(
                    chat_id,
                    image,
                    result.get("text", "")[:1024],
                    result.get("buttons", []),
                )
            else:
                send_message_with_buttons(
                    chat_id,
                    result.get("text", ""),
                    result.get("buttons", []),
                )
            return

        # -----------------------
        # LOCAL VIDEO MODE
        # -----------------------
        if isinstance(result, dict) and result.get("type") == "local_video":
            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            if YOUTUBE_SEND_AS_DOCUMENT:
                send_local_document(
                    chat_id,
                    result.get("path", ""),
                    result.get("caption", "")
                )
            else:
                send_local_video(
                    chat_id,
                    result.get("path", ""),
                    result.get("caption", "")
                )
            return

        if isinstance(result, dict) and result.get("type") == "text":
            finalize_text_response(
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
            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
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
            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
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

            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks)
            return

        # -----------------------
        # TEXT MODE
        # -----------------------
        finalize_text_response(chat_id, result, placeholder_message_id, stop_placeholder)

    except Exception:
        logger.error("❌ ERROR EN PROCESS:\n" + traceback.format_exc())
        finalize_text_response(
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
                result = handle_translate_voice_input(
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

        if callback_data.startswith("movie_suggest_yes:"):
            item_id = callback_data.split(":", 1)[1]
            answer_callback_query(callback["id"], "Abriendo película...")
            send_chat_action(chat_id, "typing")
            result = jellyfin.run_by_id(item_id)

            if isinstance(result, dict) and result.get("type") == "video":
                _send_jellyfin_video_response(
                    chat_id,
                    result.get("title", ""),
                    result.get("image"),
                    result.get("item_id"),
                    result.get("audio_tracks", []),
                )
                delete_message(chat_id, callback_message_id)
            else:
                edit_message(chat_id, callback_message_id, str(result.get("error", "No pude cargar esa película.")))
            return {"ok": True}

        if callback_data == "movie_suggest_no":
            answer_callback_query(callback["id"])
            set_pending_followup(chat_id, "movies")
            edit_message(chat_id, callback_message_id, "Vale, dime otra película.")
            return {"ok": True}

        if callback_data.startswith("playlist_manage:"):
            playlist_name = callback_data.split(":", 1)[1]
            answer_callback_query(callback["id"])
            menu = playlist_manage_menu(playlist_name)
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
                menu = playlist_remove_menu(chat_id, playlist_name)
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
            menu = playlist_manage_menu(playlist_name, str(result))
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

        if callback_data.startswith("wallapop_condition:"):
            answer_callback_query(callback["id"])
            session = get_wallapop_session(chat_id) or {}
            session["condition"] = callback_data.split(":", 1)[1]
            session["step"] = "await_price"
            set_wallapop_session(chat_id, session)
            edit_message(
                chat_id,
                callback_message_id,
                (
                    "Indica un rango de precio como `50-200`, o un máximo como `300`.\n"
                    "Si no quieres filtro de precio, escribe `skip`."
                ),
            )
            return {"ok": True}

        if callback_data.startswith("wallapop_radius:"):
            answer_callback_query(callback["id"])
            session = get_wallapop_session(chat_id) or {}
            radius_value = callback_data.split(":", 1)[1]
            session["distance_km"] = None if radius_value == "skip" else int(radius_value)
            session["step"] = "await_order"
            set_wallapop_session(chat_id, session)
            edit_message_with_buttons(
                chat_id,
                callback_message_id,
                "¿Cómo quieres ordenar los resultados?",
                wallapop_order_buttons(),
            )
            return {"ok": True}

        if callback_data.startswith("wallapop_order:"):
            from app.tools.wallapop import search_wallapop

            answer_callback_query(callback["id"], "Buscando en Wallapop...")
            session = get_wallapop_session(chat_id) or {}
            session["order"] = callback_data.split(":", 1)[1]
            clear_wallapop_session(chat_id)
            send_chat_action(chat_id, "typing")
            result = search_wallapop(session)

            if isinstance(result, dict) and result.get("type") == "wallapop" and result.get("items"):
                result_session = wallapop_build_result_session(session, result)
                set_wallapop_result_session(chat_id, result_session)
                menu = wallapop_results_menu(result_session)
                edit_message_with_buttons(
                    chat_id,
                    callback_message_id,
                    menu["text"],
                    menu["buttons"],
                )
            else:
                edit_message(
                    chat_id,
                    callback_message_id,
                    str(result.get("error") if isinstance(result, dict) else result),
                )
            return {"ok": True}

        if callback_data.startswith("wallapop_page:"):
            from app.tools.wallapop import search_wallapop

            answer_callback_query(callback["id"], "Cargando más resultados...")
            result_session = get_wallapop_result_session(chat_id)
            if not result_session:
                edit_message(chat_id, callback_message_id, "No tengo una búsqueda reciente de Wallapop. Usa /wallapop.")
                return {"ok": True}

            direction = callback_data.split(":", 1)[1]
            current_page = result_session.get("current_page", 0)
            target_page = current_page - 1 if direction == "prev" else current_page + 1
            if target_page < 0:
                target_page = 0

            required_items = (target_page + 1) * WALLAPOP_UI_PAGE_SIZE
            while required_items > len(result_session.get("loaded_items", [])) and result_session.get("next_page_token"):
                send_chat_action(chat_id, "typing")
                next_result = search_wallapop(
                    result_session.get("filters", {}),
                    next_page_token=result_session.get("next_page_token"),
                )
                if not isinstance(next_result, dict) or next_result.get("type") != "wallapop":
                    break

                existing_ids = {item.get("id") for item in result_session.get("loaded_items", [])}
                for item in next_result.get("items", []):
                    if item.get("id") not in existing_ids:
                        result_session.setdefault("loaded_items", []).append(item)
                        existing_ids.add(item.get("id"))
                result_session["next_page_token"] = next_result.get("next_page")
                wallapop_apply_order(result_session)

            max_page = max(0, wallapop_total_loaded_pages(result_session) - 1)
            result_session["current_page"] = min(target_page, max_page)
            set_wallapop_result_session(chat_id, result_session)
            menu = wallapop_results_menu(result_session)
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data == "wallapop_new_search":
            answer_callback_query(callback["id"])
            clear_wallapop_result_session(chat_id)
            set_wallapop_session(
                chat_id,
                {
                    "step": "await_query",
                    "query": "",
                    "condition": "any",
                    "min_price": None,
                    "max_price": None,
                    "location_label": "",
                    "distance_km": None,
                    "order": "newest",
                },
            )
            edit_message(
                chat_id,
                callback_message_id,
                "¿Qué producto quieres buscar en Wallapop?",
            )
            return {"ok": True}

        if callback_data.startswith("wallapop_item:"):
            answer_callback_query(callback["id"], "Abriendo anuncio...")
            result_session = get_wallapop_result_session(chat_id)
            if not result_session:
                send_message(chat_id, "No tengo una búsqueda reciente de Wallapop. Usa /wallapop.")
                return {"ok": True}

            try:
                item_index = int(callback_data.split(":", 1)[1])
            except ValueError:
                send_message(chat_id, "No pude abrir ese artículo.")
                return {"ok": True}

            items = result_session.get("loaded_items", [])
            if item_index < 0 or item_index >= len(items):
                send_message(chat_id, "Ese artículo ya no está disponible en la sesión actual.")
                return {"ok": True}

            item = items[item_index]
            buttons = [[{"text": "🔗 Abrir anuncio", "url": item.get("url")}]]
            image = item.get("image")
            caption = wallapop_item_caption(item, result_session)
            if image:
                send_photo_with_buttons(chat_id, image, caption, buttons)
            else:
                send_message_with_buttons(chat_id, caption, buttons)
            return {"ok": True}
        
        should_answer_callback_at_end = True

        # 1. Responder al callback para quitar el relojito
        if callback_data.startswith("youtube_play:") or callback_data.startswith("music_play:"):
            if callback_data.startswith("music_play:"):
                answer_callback_query(callback["id"], "Preparando audio para Telegram...")
                send_chat_action(chat_id, "upload_audio")
            else:
                answer_callback_query(callback["id"], "Preparando vídeo para Telegram...")
                send_chat_action(chat_id, "upload_video")
            should_answer_callback_at_end = False
        elif callback_data.startswith("open_library:") or callback_data.startswith("open_series:") or callback_data.startswith("open_season:") or callback_data.startswith("play_movie:") or callback_data.startswith("play_episode:"):
            send_chat_action(chat_id, "typing")

        result = handle_callback(callback)

        if not result:
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        # --- LÓGICA DE VIDEO (CON BOTONES DE AUDIO) ---
        if result.get("type") == "video":
            title = result.get("title", "")
            image = result.get("image")
            item_id = result.get("item_id")
            audio_tracks = result.get("audio_tracks", [])
            _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks)
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        if result.get("type") == "local_video":
            if YOUTUBE_SEND_AS_DOCUMENT:
                send_local_document(
                    chat_id,
                    result.get("path", ""),
                    result.get("caption", "")
                )
            else:
                send_local_video(
                    chat_id,
                    result.get("path", ""),
                    result.get("caption", "")
                )
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        if result.get("type") == "local_audio":
            send_local_audio(
                chat_id,
                result.get("path", ""),
                result.get("title", ""),
                result.get("performer", "")
            )
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        # --- LÓGICA DE TEXTO (ERRORES / MENSAJES) ---
        if result.get("type") == "text":
            edit_message(
                chat_id,
                callback_message_id,
                result.get("text", "")
            )
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        # --- LÓGICA DE MENÚ ---
        if result.get("type") == "menu":
            edit_message_with_buttons(
                chat_id,
                callback_message_id,
                result.get("text", "Menú"),
                result.get("buttons", [])
            )
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        if result.get("type") == "wallapop":
            image = result.get("image")
            if image:
                send_photo_with_buttons(
                    chat_id,
                    image,
                    result.get("text", "")[:1024],
                    result.get("buttons", []),
                )
            else:
                send_message_with_buttons(
                    chat_id,
                    result.get("text", ""),
                    result.get("buttons", []),
                )
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
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
    if _needs_placeholder(text) and not _should_skip_placeholder(chat_id, text):
        placeholder_message_id = send_temp_message(chat_id, "Buscando...")
        send_chat_action(chat_id, "typing")

    process(text, chat_id, placeholder_message_id)

    return {"ok": True}
