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
    send_message_with_reply_keyboard,
    remove_reply_keyboard,
    send_local_audio,
    send_local_document,
    send_photo,
    send_photo_bytes_with_buttons,
    send_photo_with_buttons,
    send_images,
    send_chat_action,
    send_local_video,
    send_local_photo_with_buttons,
    send_temp_message,
    edit_message,
    edit_message_with_buttons,
    delete_message,
    send_message_with_buttons,
    edit_photo_with_buttons,
    answer_callback_query,
    pop_recent_bot_messages,
)
from app.config import YOUTUBE_SEND_AS_DOCUMENT
from app.tools.jellyfin import jellyfin
from app.core.callback_handler import handle_callback
from app.core.command_flow import handle_slash_command
from app.core.direct_intents import run_direct_intent
from app.core.translate_flow import handle_translate_voice_input
from app.core.access_control import (
    approve_user,
    block_user,
    get_user_details,
    is_admin,
    is_approved,
    is_blocked,
    list_users,
    list_admins,
    record_user_activity,
    register_access_request,
)
from app.core.chat_state import (
    clear_all_chat_state,
    clear_base_chat_state,
    clear_jellyfin_item_message,
    clear_pending_followup,
    clear_prediction_session,
    clear_playlist_session,
    clear_recipe_session,
    clear_translate_result,
    clear_translate_session,
    clear_wallapop_alert_session,
    clear_wallapop_item_message,
    clear_wallapop_result_session,
    clear_wallapop_session,
    get_jellyfin_item_message,
    get_pending_followup,
    get_playlist_session,
    get_translate_session,
    get_translate_result,
    get_wallapop_session,
    get_wallapop_alert_session,
    get_wallapop_item_message,
    get_wallapop_result_session,
    pop_pending_followup,
    set_pending_followup,
    set_playlist_session,
    set_jellyfin_item_message,
    set_translate_result,
    set_translate_session,
    set_wallapop_alert_session,
    set_wallapop_item_message,
    set_wallapop_result_session,
    set_wallapop_session,
    get_prediction_session,
    get_recipe_session,
    set_recipe_session,
)
from app.tools.wallapop_alerts import create_or_replace_alert, delete_alert, get_alert_for_chat
from app.core.wallapop_alert_worker import run_wallapop_alert_test
from app.utils.playlist_ui import (
    coerce_playlist_feedback,
    playlist_manage_menu,
    playlist_remove_menu,
)
from app.utils.access_ui import (
    build_control_menu,
    build_user_actions_menu,
    build_user_details_menu,
)
from app.utils.wallapop_ui import (
    WALLAPOP_UI_PAGE_SIZE,
    wallapop_alert_reuse_buttons,
    wallapop_alerts_menu,
    wallapop_apply_order,
    wallapop_build_result_session,
    wallapop_condition_buttons,
    wallapop_item_caption,
    wallapop_location_skip_buttons,
    wallapop_order_buttons,
    wallapop_price_skip_buttons,
    wallapop_radius_buttons,
    wallapop_results_menu,
    wallapop_total_loaded_pages,
)
from app.utils.jellyfin_ui import build_jellyfin_audio_buttons
from app.utils.prediction_ui import prediction_result_menu, team_suggestion_menu
from app.utils.response_flow import (
    clear_placeholder,
    finalize_text_response,
    placeholder_indicator,
    typing_indicator,
)

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


def _access_request_buttons(user_id):
    return [[
        {"text": "✅ Aprobar", "callback_data": f"access_approve:{user_id}"},
        {"text": "❌ Bloquear", "callback_data": f"access_block:{user_id}"},
    ]]


def _clear_chat_context(chat_id, remove_keyboard=False, source_message_id=None):
    recent_message_ids = list(reversed(pop_recent_bot_messages(chat_id)))
    seen_message_ids = set()
    for message_id in recent_message_ids:
        if not message_id or message_id in seen_message_ids:
            continue
        seen_message_ids.add(message_id)
        delete_message(chat_id, message_id)

    existing_jellyfin_item_message = get_jellyfin_item_message(chat_id)
    if existing_jellyfin_item_message and existing_jellyfin_item_message.get("message_id"):
        delete_message(chat_id, existing_jellyfin_item_message["message_id"])

    existing_wallapop_item_message = get_wallapop_item_message(chat_id)
    if existing_wallapop_item_message and existing_wallapop_item_message.get("message_id"):
        delete_message(chat_id, existing_wallapop_item_message["message_id"])

    clear_all_chat_state(chat_id)

    if remove_keyboard:
        remove_reply_keyboard(chat_id)

    if source_message_id:
        delete_message(chat_id, source_message_id)


def _notify_admins_about_access(request_payload):
    user_id = request_payload.get("user_id")
    first_name = request_payload.get("first_name") or "Sin nombre"
    username = request_payload.get("username") or ""
    username_line = f"@{username}" if username else "sin username"
    text = (
        "🔐 Nueva solicitud de acceso al bot\n\n"
        f"Nombre: {first_name}\n"
        f"Usuario: {username_line}\n"
        f"user_id: {user_id}\n"
        f"chat_id: {request_payload.get('chat_id')}\n"
        f"Solicitado: {request_payload.get('requested_at')}"
    )
    buttons = _access_request_buttons(user_id)
    for admin_chat_id in list_admins():
        send_message_with_buttons(admin_chat_id, text, buttons)


def _handle_access_gate(user_id, chat_id, first_name="", username="", callback_id=None):
    if user_id is None:
        return True

    if is_admin(user_id) or is_approved(user_id):
        return True

    if is_blocked(user_id):
        if callback_id:
            answer_callback_query(callback_id, "No tienes acceso a este bot.")
        send_message(chat_id, "⛔ No tienes acceso a este bot.")
        return False

    registration = register_access_request(
        user_id,
        chat_id=chat_id,
        username=username,
        first_name=first_name,
    )
    if registration.get("created") and registration.get("request"):
        _notify_admins_about_access(registration["request"])

    if callback_id:
        answer_callback_query(callback_id, "Acceso pendiente de aprobación.")
    send_message(
        chat_id,
        "🔒 Este bot es privado.\nTu acceso ha quedado pendiente de aprobación por el administrador.",
    )
    return False


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


def _enqueue_chat_message(chat_id, text, placeholder_message_id=None, source_message_id=None):
    queue = _get_chat_queue(chat_id)
    queue.put((text, placeholder_message_id, source_message_id))
    _ensure_chat_worker(chat_id)


def _chat_worker_loop(chat_id):
    queue = _get_chat_queue(chat_id)

    while True:
        text, placeholder_message_id, source_message_id = queue.get()
        try:
            logger.info(f"🔧 Worker processing for chat_id={chat_id}, text={text}")
            result = _process_locked(text, chat_id, placeholder_message_id, source_message_id)
            logger.info(f"✅ Worker completed for chat_id={chat_id}: {result}")

            # 🔥 AÑADE ESTO
            if result:
                success, payload, sources = result

                if payload:
                    if payload["type"] == "menu":
                        send_message_with_buttons(
                            chat_id,
                            payload["text"],
                            payload["buttons"]
                        )
                    elif payload["type"] == "text":
                        send_message(chat_id, payload["text"])

        finally:
            queue.task_done()


def _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks, media_source_id=None, anchor_message_id=None):
    buttons = build_jellyfin_audio_buttons(item_id, audio_tracks, media_source_id=media_source_id)
    caption = f"🎬 {title}\n\nElige idioma:"
    existing_item_message = get_jellyfin_item_message(chat_id)

    if existing_item_message and existing_item_message.get("message_id"):
        existing_message_id = existing_item_message["message_id"]
        # Si la ficha anterior quedó por encima del menú actual, o simplemente queremos
        # mantener una sola ficha viva, la borramos antes de crear la nueva.
        if anchor_message_id is None or existing_message_id != anchor_message_id:
            delete_message(chat_id, existing_message_id)
            clear_jellyfin_item_message(chat_id)

    sent_message_id = None
    image_bytes, _ = jellyfin.get_image_binary(item_id)
    if image_bytes:
        sent_message_id = send_photo_bytes_with_buttons(
            chat_id,
            image_bytes,
            f"{item_id}.jpg",
            caption,
            buttons,
        )
        if sent_message_id:
            set_jellyfin_item_message(chat_id, {"message_id": sent_message_id, "has_image": True})
            return

    if image:
        sent_message_id = send_photo_with_buttons(chat_id, image, caption, buttons)
        if sent_message_id:
            set_jellyfin_item_message(chat_id, {"message_id": sent_message_id, "has_image": True})
            return

    sent_message_id = send_message_with_buttons(chat_id, caption, buttons)
    if sent_message_id:
        set_jellyfin_item_message(chat_id, {"message_id": sent_message_id, "has_image": False})


def _send_wallapop_location_prompt(chat_id, placeholder_message_id=None, stop_placeholder=None):
    prompt = (
        "Indica una localidad para buscar cerca,\n"
        "o usa el teclado para compartir tu ubicación o hacer skip."
    )
    clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
    send_message_with_reply_keyboard(
        chat_id,
        prompt,
        [
            [{"text": "📍 Usar mi ubicación", "request_location": True}],
            [{"text": "⏭ Skip"}],
        ],
    )


def _callback_message_has_media(callback_message):
    return bool(callback_message.get("photo") or callback_message.get("caption"))


def _needs_placeholder(text):
    normalized = (text or "").strip()

    if not normalized:
        return False

    incomplete_commands = ["/start", "/helper", "/library", "/menu", "/catalog", "/wiki", "/img", "/image", "/video", "/tiempo", "/weather", "/youtube", "/music", "/playlist", "/translate", "/wallapop", "/mis_alertas", "/prediccion", "/prediction", "/mis_predicciones"]
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


def process(text, chat_id, placeholder_message_id=None, source_message_id=None):
    _enqueue_chat_message(chat_id, text, placeholder_message_id, source_message_id)


def _process_locked(text, chat_id, placeholder_message_id=None, source_message_id=None):
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
        wallapop_alert_session = None

        if text.startswith("/"):
            if text.startswith("/clear"):
                _clear_chat_context(chat_id, remove_keyboard=True, source_message_id=source_message_id)
            elif not text.startswith("/wallapop") and not text.startswith("/mis_alertas"):
                clear_base_chat_state(chat_id)
                existing_jellyfin_item_message = get_jellyfin_item_message(chat_id)
                if existing_jellyfin_item_message and existing_jellyfin_item_message.get("message_id"):
                    delete_message(chat_id, existing_jellyfin_item_message["message_id"])
                clear_jellyfin_item_message(chat_id)
                clear_wallapop_alert_session(chat_id)
        else:
            pending_intent = pop_pending_followup(chat_id)
            playlist_session = get_playlist_session(chat_id)
            wallapop_alert_session = get_wallapop_alert_session(chat_id)

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

        elif get_recipe_session(chat_id) and not text.startswith("/"):

            from app.tools.recipe import search_recipes
            from app.utils.recipe_ui import recipe_list_menu
            
            session = get_recipe_session(chat_id)
            step = session.get("step")
            
            logger.info(f"DEBUG: Recipe session found, chat_id={chat_id}, step={step}, text={text}")

            # -------------------------
            # BUSQUEDA DE RECETA POR TEXTO
            # -------------------------
            if step == "await_query":
                logger.info(f"DEBUG: Entering await_query block")
                query = text.strip()
                
                results = search_recipes(query)
                recipes = results.get("recipes", [])
                logger.info(f"DEBUG: Found {len(recipes)} recipes")
                
                # Guardar resultados en la sesión antes de mostrar el menú
                callback_message_id = session.get("callback_message_id")
                set_recipe_session(chat_id, {
                    "step": "await_selection",
                    "query": query,
                    "results": recipes,
                    "callback_message_id": callback_message_id
                })
                
                # Guardar la receta en el historial
                from app.tools.recipe import _save_prediction, predict_recipe_success
                
                # Usar la primera URL de los resultados encontrados
                first_url = recipes[0].get("url") if recipes else ""
                
                prediction = predict_recipe_success(query)
                prediction["recipe_name"] = query
                prediction["probability"] = 75
                prediction["url"] = first_url
                
                _save_prediction(chat_id, query, first_url)
                
                menu = recipe_list_menu(query, recipes)
                
                return True, menu, ["recipe_tool"]

            # -------------------------
            # MOSTRAR RECETA SELECCIONADA (solo si hay callback previo)
            # -------------------------
            if step == "viewing_recipe":
                recipe = session.get("selected_recipe")
                from app.tools.recipe import get_recipe_details
                from app.utils.recipe_ui import recipe_detail_menu
                
                details = get_recipe_details(recipe["url"])
                
                return True, recipe_detail_menu(details), ["recipe_tool"]

            # Si hay resultados guardados pero no estamos viendo una receta
            if step == "await_selection":
                query = session.get("query", "")
                recipes = session.get("results", [])
                
                if recipes:
                    menu = recipe_list_menu(query, recipes)
                    return True, menu, ["recipe_tool"]

            # Si no hay step válido, simplemente mostrar el menú de nuevo
            menu = recipe_list_menu(
                session.get("query", ""),
                session.get("results", [])
            )
            return True, menu, ["recipe_tool"]

        elif get_prediction_session(chat_id) and not text.startswith("/"):
            from app.core.chat_state import set_prediction_session
            from app.tools.sports_prediction import find_next_match, predict_match, resolve_team_name
            
            session = get_prediction_session(chat_id)
            step = session.get("step")
            
            if step == "await_team_a":
                team_a = text.strip()
                
                if team_a:
                    resolved = resolve_team_name(team_a)
                    if resolved["status"] == "resolved":
                        team_a = resolved["resolved_name"]
                        session["team_a"] = team_a
                        session["step"] = "await_team_b"
                        session.pop("team_a_suggestions", None)
                        set_prediction_session(chat_id, session)

                        result = {
                            "type": "menu",
                            "text": f"⚽ Equipo 1: {team_a}\n\n¿Quién es el rival?",
                            "buttons": [
                                [{"text": "📅 Próximo Rival", "callback_data": "pred:rival_auto"}],
                                [{"text": "✏️ Escribir otro", "callback_data": "pred:rival_manual"}]
                            ]
                        }
                        sources = ["sports_prediction_tool"]
                    elif resolved["status"] == "suggest":
                        session["team_a_suggestions"] = resolved["suggestions"]
                        session["step"] = "await_team_a"
                        set_prediction_session(chat_id, session)
                        result = team_suggestion_menu(team_a, resolved["suggestions"], "team_a")
                        sources = ["sports_prediction_tool"]
                    else:
                        result = {"type": "text", "text": f"❌ No encontré ningún equipo parecido a '{team_a}'."}
                        sources = ["sports_prediction_tool"]

            elif step == "await_team_b":
                team_b = text.strip()
                resolved = resolve_team_name(team_b)
                if resolved["status"] == "resolved":
                    team_b = resolved["resolved_name"]
                    session["team_b"] = team_b
                    session["step"] = "analyzing"
                    session.pop("team_b_suggestions", None)
                    set_prediction_session(chat_id, session)

                    prediction = predict_match(session["team_a"], team_b, chat_id=chat_id)
                    result = prediction_result_menu(prediction, chat_id)
                    clear_prediction_session(chat_id)
                    sources = ["sports_prediction_tool"]
                elif resolved["status"] == "suggest":
                    session["team_b_suggestions"] = resolved["suggestions"]
                    session["step"] = "await_team_b"
                    set_prediction_session(chat_id, session)
                    result = team_suggestion_menu(team_b, resolved["suggestions"], "team_b")
                    sources = ["sports_prediction_tool"]
                else:
                    result = {"type": "text", "text": f"❌ No encontré ningún equipo parecido a '{team_b}'."}
                    sources = ["sports_prediction_tool"]

            elif step == "await_rival_auto":
                team_a = session.get("team_a")
                match = find_next_match(team_a)
                if match:
                    session["team_b"] = match["opponent"]
                    session["step"] = "analyzing"
                    set_prediction_session(chat_id, session)
                    
                    prediction = predict_match(session["team_a"], match["opponent"], chat_id=chat_id)
                    result = prediction_result_menu(prediction, chat_id)
                    clear_prediction_session(chat_id)
                    sources = ["sports_prediction_tool"]
                else:
                    result = {"type": "text", "text": "No se encontró próximo partido"}
                    sources = []

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
                _send_wallapop_location_prompt(chat_id, placeholder_message_id, stop_placeholder)
                return
            elif step == "await_location":
                lowered = text.strip().lower()
                normalized_skip = lowered.replace("⏭", "").strip()
                remove_reply_keyboard(chat_id)
                if normalized_skip in {"skip", "saltar", "omitir"}:
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

            elif step == "await_order":
                session["step"] = "searching"
                set_wallapop_session(chat_id, session)
                send_chat_action(chat_id, "typing")
                from app.tools.wallapop import search_wallapop
                result = search_wallapop(session)

                if isinstance(result, dict) and result.get("type") == "wallapop" and result.get("items"):
                    result_session = wallapop_build_result_session(session, result)
                    set_wallapop_result_session(chat_id, result_session)
                    menu = wallapop_results_menu(result_session)
                    edit_message_with_buttons(
                        chat_id,
                        placeholder_message_id or source_message_id,
                        menu["text"],
                        menu["buttons"],
                    )
                elif isinstance(result, dict) and result.get("type") == "wallapop":
                    if result.get("buttons"):
                        edit_message_with_buttons(
                            chat_id,
                            placeholder_message_id or source_message_id,
                            result.get("text", "No pude obtener resultados de Wallapop."),
                            result.get("buttons", []),
                        )
                    else:
                        edit_message(
                            chat_id,
                            placeholder_message_id or source_message_id,
                            result.get("text", "No pude obtener resultados de Wallapop."),
                        )
                else:
                    edit_message(
                        chat_id,
                        placeholder_message_id or source_message_id,
                        str(result.get("error") if isinstance(result, dict) else result),
                    )

        elif wallapop_alert_session and not text.startswith("/"):
            if wallapop_alert_session.get("step") == "await_max_price":
                try:
                    max_price = int(float(text.replace("€", "").strip()))
                except ValueError:
                    result = "No entendí el precio máximo de la alerta. Escribe un número como `50` o `1200`."
                    sources = ["wallapop_tool"]
                    logger.info(f"🧠 RESULT: {result}")
                    finalize_text_response(chat_id, result, placeholder_message_id, stop_placeholder)
                    return

                existing_alert = get_alert_for_chat(chat_id)
                if existing_alert:
                    clear_wallapop_alert_session(chat_id)
                    result = "Ya tienes una alerta activa. Usa /mis_alertas para borrarla antes de crear otra."
                    sources = ["wallapop_tool"]
                    logger.info(f"🧠 RESULT: {result}")
                    finalize_text_response(chat_id, result, placeholder_message_id, stop_placeholder)
                    return

                result_session = get_wallapop_result_session(chat_id) or {}
                alert = create_or_replace_alert(
                    chat_id,
                    wallapop_alert_session.get("filters", {}),
                    wallapop_alert_session.get("reuse_filters", True),
                    max_price,
                    seen_items=result_session.get("loaded_items", []),
                )
                clear_wallapop_alert_session(chat_id)

                source_message_id = wallapop_alert_session.get("source_message_id")
                if source_message_id and result_session:
                    menu = wallapop_results_menu(result_session)
                    edit_message_with_buttons(chat_id, source_message_id, menu["text"], menu["buttons"])

                if isinstance(alert, dict) and alert.get("error"):
                    result = alert["error"]
                else:
                    result = (
                        f"🔔 Alerta creada para '{alert.get('query', '')}' por un máximo de {int(alert.get('max_price', 0))}€.\n"
                        "Solo avisaré de anuncios nuevos a partir de ahora.\n"
                        "Puedes verla o borrarla con /mis_alertas."
                    )
                sources = ["wallapop_tool"]

        elif pending_intent:
            logger.info(f"↪️ USING PENDING INTENT: {pending_intent}")
            result, sources = run_direct_intent(pending_intent, text, chat_id)

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

        else:
            handled, result, sources = handle_slash_command(text, chat_id)
            if not handled:
                result, sources = agent(text)
                logger.info(f"🔗 SOURCES: {sources}")

        logger.info(f"🧠 RESULT: {result}")

        # Convertir tuple (True/False, result_dict/list, sources) a dict
        if isinstance(result, tuple) and len(result) >= 2:
            success = result[0]
            result_data = result[1]
            sources = result[2] if len(result) > 2 else []
            
            if isinstance(result_data, dict):
                result = result_data
            elif isinstance(result_data, str):
                result = {"type": "text", "text": result_data}

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
                result.get("text", ""),
                result.get("buttons", []),
            )
            
            return

        if isinstance(result, dict) and result.get("type") == "prediction_card":
            clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            send_local_photo_with_buttons(
                chat_id,
                result.get("image_path", ""),
                result.get("text", ""),
                result.get("buttons", []),
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
    sender_id = None
    sender_username = ""
    sender_first_name = ""

    # -----------------------
    # MESSAGE
    # -----------------------
    if "message" in data:
        message = data["message"]
        text = message.get("text")
        chat_id = message["chat"]["id"]
        sender = message.get("from") or {}
        sender_id = sender.get("id")
        sender_username = sender.get("username") or ""
        sender_first_name = sender.get("first_name") or ""
        voice = message.get("voice")
        location = message.get("location")

        record_user_activity(
            sender_id,
            chat_id=chat_id,
            username=sender_username,
            first_name=sender_first_name,
            text=text,
        )

        if not _handle_access_gate(sender_id, chat_id, sender_first_name, sender_username):
            return {"ok": True}

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

        if location and chat_id:
            wallapop_session = get_wallapop_session(chat_id)
            if wallapop_session and wallapop_session.get("step") == "await_location":
                remove_reply_keyboard(chat_id)
                wallapop_session["latitude"] = location.get("latitude")
                wallapop_session["longitude"] = location.get("longitude")
                wallapop_session["location_label"] = "Mi ubicación"
                wallapop_session["step"] = "await_radius"
                set_wallapop_session(chat_id, wallapop_session)
                send_message_with_buttons(
                    chat_id,
                    "Ubicación recibida.\n\n¿Qué radio quieres usar?",
                    wallapop_radius_buttons(),
                )
                return {"ok": True}


    # -----------------------
    # CALLBACK QUERY (NETFLIX UI)
    # -----------------------
    elif "callback_query" in data:
        callback = data["callback_query"]
        callback_message = callback["message"]
        chat_id = callback_message["chat"]["id"]
        callback_message_id = callback_message["message_id"]
        callback_data = callback.get("data", "")
        sender = callback.get("from") or {}
        sender_id = sender.get("id")
        sender_username = sender.get("username") or ""
        sender_first_name = sender.get("first_name") or ""

        record_user_activity(
            sender_id,
            chat_id=chat_id,
            username=sender_username,
            first_name=sender_first_name,
            text=f"[callback] {callback_data}",
        )

        if callback_data.startswith("access_approve:") or callback_data.startswith("access_block:"):
            if not is_admin(sender_id):
                answer_callback_query(callback["id"], "Solo un admin puede gestionar accesos.")
                return {"ok": True}

            target_user_id = callback_data.split(":", 1)[1]
            if not str(target_user_id).isdigit():
                answer_callback_query(callback["id"], "Usuario no válido.")
                return {"ok": True}

            if callback_data.startswith("access_approve:"):
                approved_request = approve_user(int(target_user_id))
                answer_callback_query(callback["id"], "Usuario aprobado.")
                edit_message(
                    chat_id,
                    callback_message_id,
                    f"✅ Acceso aprobado para {approved_request.get('first_name') or approved_request.get('username') or target_user_id} ({target_user_id})." if approved_request else f"✅ Acceso aprobado para {target_user_id}.",
                )
                target_chat_id = (approved_request or {}).get("chat_id") or int(target_user_id)
                send_message(
                    target_chat_id,
                    "✅ Tu acceso al bot ha sido aprobado.\nYa puedes usarlo con normalidad.",
                )
                return {"ok": True}

            blocked_request = block_user(int(target_user_id))
            answer_callback_query(callback["id"], "Usuario bloqueado.")
            edit_message(
                chat_id,
                callback_message_id,
                f"❌ Acceso bloqueado para {blocked_request.get('first_name') or blocked_request.get('username') or target_user_id} ({target_user_id})." if blocked_request else f"❌ Acceso bloqueado para {target_user_id}.",
            )
            target_chat_id = (blocked_request or {}).get("chat_id") or int(target_user_id)
            send_message(
                target_chat_id,
                "⛔ Tu acceso al bot ha sido rechazado.",
            )
            return {"ok": True}

        if callback_data.startswith("control_approve:") or callback_data.startswith("control_block:"):
            if not is_admin(sender_id):
                answer_callback_query(callback["id"], "Solo un admin puede gestionar accesos.")
                return {"ok": True}

            _, target_user_id, status_filter, page_value = callback_data.split(":", 3)
            if not str(target_user_id).isdigit():
                answer_callback_query(callback["id"], "Usuario no válido.")
                return {"ok": True}

            try:
                page = max(0, int(page_value))
            except ValueError:
                page = 0

            if callback_data.startswith("control_approve:"):
                approved_request = approve_user(int(target_user_id))
                answer_callback_query(callback["id"], "Usuario aprobado.")
                target_chat_id = (approved_request or {}).get("chat_id") or int(target_user_id)
                send_message(
                    target_chat_id,
                    "✅ Tu acceso al bot ha sido aprobado.\nYa puedes usarlo con normalidad.",
                )
            else:
                blocked_request = block_user(int(target_user_id))
                answer_callback_query(callback["id"], "Usuario bloqueado.")
                target_chat_id = (blocked_request or {}).get("chat_id") or int(target_user_id)
                send_message(
                    target_chat_id,
                    "⛔ Tu acceso al bot ha sido rechazado.",
                )

            all_users = list_users("all")
            users = all_users if status_filter == "all" else list_users(status_filter)
            menu = build_control_menu(users, current_filter=status_filter, page=page, all_users=all_users)
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data.startswith("control_list:"):
            if not is_admin(sender_id):
                answer_callback_query(callback["id"], "Solo un admin puede usar este panel.")
                return {"ok": True}

            _, status_filter, page_value = callback_data.split(":", 2)
            try:
                page = max(0, int(page_value))
            except ValueError:
                page = 0

            all_users = list_users("all")
            users = all_users if status_filter == "all" else list_users(status_filter)
            menu = build_control_menu(users, current_filter=status_filter, page=page, all_users=all_users)
            answer_callback_query(callback["id"])
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data.startswith("control_user:"):
            if not is_admin(sender_id):
                answer_callback_query(callback["id"], "Solo un admin puede usar este panel.")
                return {"ok": True}

            _, user_id_value, status_filter, page_value = callback_data.split(":", 3)
            if not str(user_id_value).isdigit():
                answer_callback_query(callback["id"], "Usuario no válido.")
                return {"ok": True}

            user = get_user_details(int(user_id_value))
            if not user:
                answer_callback_query(callback["id"], "No encontré ese usuario.")
                return {"ok": True}

            try:
                page = max(0, int(page_value))
            except ValueError:
                page = 0

            menu = build_user_actions_menu(user, current_filter=status_filter, page=page)
            answer_callback_query(callback["id"])
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if callback_data.startswith("control_detail:"):
            if not is_admin(sender_id):
                answer_callback_query(callback["id"], "Solo un admin puede usar este panel.")
                return {"ok": True}

            _, user_id_value, status_filter, page_value = callback_data.split(":", 3)
            if not str(user_id_value).isdigit():
                answer_callback_query(callback["id"], "Usuario no válido.")
                return {"ok": True}

            user = get_user_details(int(user_id_value))
            if not user:
                answer_callback_query(callback["id"], "No encontré ese usuario.")
                return {"ok": True}

            try:
                page = max(0, int(page_value))
            except ValueError:
                page = 0

            menu = build_user_details_menu(user, current_filter=status_filter, page=page)
            answer_callback_query(callback["id"])
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
            return {"ok": True}

        if not _handle_access_gate(
            sender_id,
            chat_id,
            sender_first_name,
            sender_username,
            callback_id=callback["id"],
        ):
            return {"ok": True}

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
                    result.get("media_source_id"),
                    callback_message_id,
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
            edit_message_with_buttons(
                chat_id,
                callback_message_id,
                (
                    "Indica un rango de precio como `50-200`, o un máximo como `300`.\n"
                    "Si no quieres filtro de precio, escribe `skip` o pulsa el botón."
                ),
                wallapop_price_skip_buttons(),
            )
            return {"ok": True}

        if callback_data.startswith("wallapop_price:"):
            answer_callback_query(callback["id"])
            session = get_wallapop_session(chat_id) or {}
            session["min_price"] = None
            session["max_price"] = None
            session["step"] = "await_location"
            set_wallapop_session(chat_id, session)
            edit_message(
                chat_id,
                callback_message_id,
                "Indica una localidad para buscar cerca.",
            )
            _send_wallapop_location_prompt(chat_id)
            return {"ok": True}

        if callback_data.startswith("wallapop_location:"):
            answer_callback_query(callback["id"])
            session = get_wallapop_session(chat_id) or {}
            session["location_label"] = ""
            session["distance_km"] = None
            session["step"] = "await_order"
            set_wallapop_session(chat_id, session)
            edit_message_with_buttons(
                chat_id,
                callback_message_id,
                "¿Cómo quieres ordenar los resultados?",
                wallapop_order_buttons(),
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
            elif isinstance(result, dict) and result.get("type") == "wallapop":
                if result.get("buttons"):
                    edit_message_with_buttons(
                        chat_id,
                        callback_message_id,
                        result.get("text", "No pude obtener resultados de Wallapop."),
                        result.get("buttons", []),
                    )
                else:
                    edit_message(
                        chat_id,
                        callback_message_id,
                        result.get("text", "No pude obtener resultados de Wallapop."),
                    )
            else:
                edit_message(
                    chat_id,
                    callback_message_id,
                    str(result.get("error") if isinstance(result, dict) else result),
                )
            return {"ok": True}

        if callback_data == "wallapop_alert_create":
            answer_callback_query(callback["id"])
            existing_alert = get_alert_for_chat(chat_id)
            if existing_alert:
                edit_message(
                    chat_id,
                    callback_message_id,
                    "Ya tienes una alerta activa. Usa /mis_alertas para borrarla antes de crear otra.",
                )
                return {"ok": True}

            result_session = get_wallapop_result_session(chat_id)
            if not result_session:
                edit_message(chat_id, callback_message_id, "No tengo una búsqueda reciente de Wallapop.")
                return {"ok": True}

            edit_message_with_buttons(
                chat_id,
                callback_message_id,
                "¿Quieres reutilizar los filtros de esta búsqueda para la alerta?",
                wallapop_alert_reuse_buttons(),
            )
            return {"ok": True}

        if callback_data.startswith("wallapop_alert_reuse:"):
            answer_callback_query(callback["id"])
            result_session = get_wallapop_result_session(chat_id)
            if not result_session:
                edit_message(chat_id, callback_message_id, "No tengo una búsqueda reciente de Wallapop.")
                return {"ok": True}

            reuse_filters = callback_data.split(":", 1)[1] == "yes"
            base_filters = dict(result_session.get("filters", {}))
            if not reuse_filters:
                base_filters = {
                    "query": base_filters.get("query", ""),
                    "condition": "any",
                    "min_price": None,
                    "max_price": None,
                    "location_label": "",
                    "distance_km": None,
                    "latitude": None,
                    "longitude": None,
                    "category_id": base_filters.get("category_id"),
                    "order": "newest",
                }

            set_wallapop_alert_session(
                chat_id,
                {
                    "step": "await_max_price",
                    "reuse_filters": reuse_filters,
                    "filters": base_filters,
                    "source_message_id": callback_message_id,
                },
            )
            edit_message(
                chat_id,
                callback_message_id,
                "¿Qué precio máximo quieres para esta alerta? Escribe solo el número, por ejemplo `120` o `850`.",
            )
            return {"ok": True}

        if callback_data == "wallapop_alert_delete":
            answer_callback_query(callback["id"])
            deleted = delete_alert(chat_id)
            clear_wallapop_alert_session(chat_id)
            if deleted:
                edit_message(chat_id, callback_message_id, "La alerta de Wallapop se ha borrado.")
            else:
                edit_message(chat_id, callback_message_id, "No encontré ninguna alerta activa para borrar.")
            return {"ok": True}

        if callback_data == "wallapop_alert_test":
            answer_callback_query(callback["id"], "Probando alerta...")
            test_result = run_wallapop_alert_test(chat_id)
            updated_alert = get_alert_for_chat(chat_id)

            if not updated_alert:
                edit_message(chat_id, callback_message_id, "No encontré ninguna alerta activa.")
                return {"ok": True}

            if not test_result.get("ok"):
                if test_result.get("error") == "invalid_result":
                    status_message = "Última prueba: no pude obtener resultados válidos ahora mismo."
                else:
                    status_message = "Última prueba: no se pudo completar."
            else:
                new_count = test_result.get("new_count", 0)
                current_count = test_result.get("current_count", 0)
                if new_count > 0:
                    suffix = "se envió aviso" if new_count == 1 else "se enviaron avisos"
                    status_message = f"Última prueba: encontré {new_count} artículo(s) nuevo(s) y {suffix}."
                elif current_count > 0:
                    status_message = f"Última prueba: no hay artículos nuevos ahora mismo. La búsqueda actual devolvió {current_count} resultado(s)."
                else:
                    status_message = "Última prueba: no encontré resultados ahora mismo."

            menu = wallapop_alerts_menu(updated_alert, status_message=status_message)
            edit_message_with_buttons(chat_id, callback_message_id, menu["text"], menu["buttons"])
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
            existing_item_message = get_wallapop_item_message(chat_id)
            if existing_item_message and existing_item_message.get("message_id"):
                delete_message(chat_id, existing_item_message["message_id"])
            clear_wallapop_item_message(chat_id)
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
            existing_item_message = get_wallapop_item_message(chat_id)
            sent_message_id = None

            if existing_item_message:
                existing_message_id = existing_item_message.get("message_id")
                existing_has_image = existing_item_message.get("has_image", False)

                if existing_message_id:
                    if existing_message_id < callback_message_id:
                        delete_message(chat_id, existing_message_id)
                        clear_wallapop_item_message(chat_id)
                    elif image and existing_has_image:
                        edited = edit_photo_with_buttons(
                            chat_id,
                            existing_message_id,
                            image,
                            caption,
                            buttons,
                        )
                        if edited:
                            sent_message_id = existing_message_id
                    elif not image and not existing_has_image:
                        edit_message_with_buttons(chat_id, existing_message_id, caption, buttons)
                        sent_message_id = existing_message_id
                    else:
                        delete_message(chat_id, existing_message_id)
                        clear_wallapop_item_message(chat_id)

            if sent_message_id is None:
                if image:
                    sent_message_id = send_photo_with_buttons(chat_id, image, caption, buttons)
                else:
                    sent_message_id = send_message_with_buttons(chat_id, caption, buttons)

            if sent_message_id:
                set_wallapop_item_message(
                    chat_id,
                    {
                        "message_id": sent_message_id,
                        "has_image": bool(image),
                    },
                )
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
            media_source_id = result.get("media_source_id")
            _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks, media_source_id, callback_message_id)
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
            if _callback_message_has_media(callback_message):
                delete_message(chat_id, callback_message_id)
                send_message(chat_id, result.get("text", ""))
            else:
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
            if _callback_message_has_media(callback_message):
                delete_message(chat_id, callback_message_id)
                send_message_with_buttons(
                    chat_id,
                    result.get("text", "Menú"),
                    result.get("buttons", [])
                )
            else:
                edit_message_with_buttons(
                    chat_id,
                    callback_message_id,
                    result.get("text", "Menú"),
                    result.get("buttons", [])
                )
            if should_answer_callback_at_end:
                answer_callback_query(callback["id"])
            return {"ok": True}

        if result.get("type") == "prediction_card":
            delete_message(chat_id, callback_message_id)
            send_local_photo_with_buttons(
                chat_id,
                result.get("image_path", ""),
                result.get("text", ""),
                result.get("buttons", []),
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
        sender = data["edited_message"].get("from") or {}
        sender_id = sender.get("id")
        sender_username = sender.get("username") or ""
        sender_first_name = sender.get("first_name") or ""

        record_user_activity(
            sender_id,
            chat_id=chat_id,
            username=sender_username,
            first_name=sender_first_name,
            text=text,
        )

        if not _handle_access_gate(sender_id, chat_id, sender_first_name, sender_username):
            return {"ok": True}

    else:
        logger.warning("⚠️ Update ignorado")
        return {"ok": True}

    if not text or not chat_id:
        return {"ok": True}

    placeholder_message_id = None
    if _needs_placeholder(text) and not _should_skip_placeholder(chat_id, text):
        placeholder_message_id = send_temp_message(chat_id, "Buscando...")
        send_chat_action(chat_id, "typing")

    logger.info(f"🔄 Calling process for chat_id={chat_id}, text={text}")
    result = process(text, chat_id, placeholder_message_id, message.get("message_id"))
    logger.info(f"✅ Process completed: {result}")

    return {"ok": True}
