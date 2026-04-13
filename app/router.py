from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
import threading
import logging
import traceback
from datetime import datetime
import re
import unicodedata
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
    download_telegram_file,
)
from app.config import YOUTUBE_SEND_AS_DOCUMENT
from app.tools.jellyfin import jellyfin
from app.core.callback_handler import handle_callback

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

pending_followups = {}
pending_followups_lock = threading.Lock()
playlist_sessions = {}
playlist_sessions_lock = threading.Lock()
translate_sessions = {}
translate_sessions_lock = threading.Lock()
translate_results = {}
translate_results_lock = threading.Lock()
wallapop_sessions = {}
wallapop_sessions_lock = threading.Lock()
wallapop_result_sessions = {}
wallapop_result_sessions_lock = threading.Lock()
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


def set_wallapop_session(chat_id, payload):
    with wallapop_sessions_lock:
        wallapop_sessions[chat_id] = payload


def get_wallapop_session(chat_id):
    with wallapop_sessions_lock:
        return wallapop_sessions.get(chat_id)


def clear_wallapop_session(chat_id):
    with wallapop_sessions_lock:
        wallapop_sessions.pop(chat_id, None)


def set_wallapop_result_session(chat_id, payload):
    with wallapop_result_sessions_lock:
        wallapop_result_sessions[chat_id] = payload


def get_wallapop_result_session(chat_id):
    with wallapop_result_sessions_lock:
        return wallapop_result_sessions.get(chat_id)


def clear_wallapop_result_session(chat_id):
    with wallapop_result_sessions_lock:
        wallapop_result_sessions.pop(chat_id, None)


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


def _wallapop_condition_buttons():
    return [
        [
            {"text": "🆕 Nuevo", "callback_data": "wallapop_condition:new"},
            {"text": "✨ Como nuevo", "callback_data": "wallapop_condition:as_good_as_new"},
        ],
        [
            {"text": "📦 En su caja", "callback_data": "wallapop_condition:in_box"},
            {"text": "♻️ Buen estado", "callback_data": "wallapop_condition:good"},
        ],
        [
            {"text": "⏭ Sin filtrar", "callback_data": "wallapop_condition:any"},
        ],
    ]


def _wallapop_radius_buttons():
    return [
        [
            {"text": "5 km", "callback_data": "wallapop_radius:5"},
            {"text": "10 km", "callback_data": "wallapop_radius:10"},
            {"text": "25 km", "callback_data": "wallapop_radius:25"},
        ],
        [
            {"text": "50 km", "callback_data": "wallapop_radius:50"},
            {"text": "100 km", "callback_data": "wallapop_radius:100"},
        ],
        [
            {"text": "⏭ Sin radio", "callback_data": "wallapop_radius:skip"},
        ],
    ]


def _wallapop_order_buttons():
    return [
        [
            {"text": "⭐ Relevancia", "callback_data": "wallapop_order:most_relevance"},
            {"text": "🕒 Recientes", "callback_data": "wallapop_order:newest"},
        ],
        [
            {"text": "💸 Precio asc", "callback_data": "wallapop_order:price_low_to_high"},
            {"text": "💰 Precio desc", "callback_data": "wallapop_order:price_high_to_low"},
        ],
        [
            {"text": "📍 Cercanos", "callback_data": "wallapop_order:closest"},
            {"text": "🔥 Gangas", "callback_data": "wallapop_order:deal_score"},
        ],
    ]


WALLAPOP_UI_PAGE_SIZE = 8


def _wallapop_total_loaded_pages(result_session):
    loaded_items = len(result_session.get("loaded_items", []))
    if loaded_items <= 0:
        return 1
    return (loaded_items + WALLAPOP_UI_PAGE_SIZE - 1) // WALLAPOP_UI_PAGE_SIZE


def _wallapop_results_slice(result_session):
    page_index = result_session.get("current_page", 0)
    loaded_items = result_session.get("loaded_items", [])
    start = page_index * WALLAPOP_UI_PAGE_SIZE
    end = start + WALLAPOP_UI_PAGE_SIZE
    return start, end, loaded_items[start:end]


def _wallapop_format_price(item):
    price = item.get("price")
    currency = (item.get("currency") or "EUR").upper()
    if price is None:
        return "Precio no disponible"
    symbol = "€" if currency == "EUR" else currency
    return f"{price:.0f}{symbol}"


def _wallapop_normalize_text(value):
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _wallapop_tokenize(value):
    normalized = _wallapop_normalize_text(value)
    return normalized.split() if normalized else []


def _wallapop_price_insight(item, result_session):
    price = item.get("price")
    if price is None:
        return None

    loaded_items = result_session.get("loaded_items", [])
    query_tokens = _wallapop_tokenize(result_session.get("filters", {}).get("query", ""))
    item_tokens = set(_wallapop_tokenize(item.get("title", "")))
    numeric_query_tokens = [token for token in query_tokens if any(ch.isdigit() for ch in token)]

    comparable_prices = []
    for candidate in loaded_items:
        candidate_price = candidate.get("price")
        if candidate_price is None:
            continue
        if candidate.get("id") == item.get("id"):
            continue
        if candidate.get("similarity_score", 0) < 0.72:
            continue

        candidate_tokens = set(_wallapop_tokenize(candidate.get("title", "")))
        if numeric_query_tokens and not all(token in candidate_tokens for token in numeric_query_tokens):
            continue
        if numeric_query_tokens and not all(token in item_tokens for token in numeric_query_tokens):
            continue

        comparable_prices.append(float(candidate_price))

    if len(comparable_prices) < 2:
        return None

    comparable_prices.sort()
    middle = len(comparable_prices) // 2
    if len(comparable_prices) % 2 == 0:
        median_price = (comparable_prices[middle - 1] + comparable_prices[middle]) / 2
    else:
        median_price = comparable_prices[middle]

    if median_price <= 0:
        return None

    ratio = float(price) / median_price
    if ratio <= 0.88:
        label = "🟢 Ganga"
    elif ratio >= 1.12:
        label = "🔴 Caro"
    else:
        label = "🟡 Precio razonable"

    return {
        "label": label,
        "median_price": round(median_price, 2),
        "comparable_count": len(comparable_prices),
        "ratio": round(ratio, 3),
    }


def _wallapop_deal_sort_key(item, result_session):
    insight = _wallapop_price_insight(item, result_session)
    if not insight:
        return (3, 1.0, -(item.get("similarity_score") or 0), item.get("price") or 0)

    ratio = insight.get("ratio", 1.0)
    if ratio <= 0.88:
        bucket = 0
    elif ratio <= 1.12:
        bucket = 1
    else:
        bucket = 2

    return (
        bucket,
        ratio,
        -(item.get("similarity_score") or 0),
        item.get("price") or 0,
    )


def _wallapop_apply_order(result_session):
    order = result_session.get("filters", {}).get("order")
    if order != "deal_score":
        return

    items = list(result_session.get("loaded_items", []))
    if not items:
        return

    items.sort(key=lambda item: _wallapop_deal_sort_key(item, result_session))
    result_session["loaded_items"] = items


def _wallapop_format_datetime(label):
    if not label:
        return ""
    return label


def _wallapop_format_age(timestamp_ms):
    try:
        published_at = datetime.fromtimestamp(float(timestamp_ms) / 1000)
    except (TypeError, ValueError, OSError):
        return ""

    delta = datetime.now() - published_at
    if delta.days > 0:
        return f"hace {delta.days} día{'s' if delta.days != 1 else ''}"

    hours = delta.seconds // 3600
    if hours > 0:
        return f"hace {hours} hora{'s' if hours != 1 else ''}"

    minutes = max(1, delta.seconds // 60)
    return f"hace {minutes} min"


def _wallapop_trim_button(text, limit=52):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _wallapop_results_menu(result_session):
    filters = result_session.get("filters", {})
    search_url = result_session.get("search_url")
    current_page = result_session.get("current_page", 0)
    loaded_pages = _wallapop_total_loaded_pages(result_session)
    start, _, items = _wallapop_results_slice(result_session)

    text_lines = [f"🛒 Wallapop: {filters.get('query', '')}"]
    if result_session.get("summary"):
        text_lines.append(f"Filtros: {result_session['summary']}")
    text_lines.append("")
    text_lines.append("Selecciona un artículo para ver la ficha completa.")
    text_lines.append("")
    total_label = f"{loaded_pages}+" if result_session.get("next_page_token") else str(loaded_pages)
    text_lines.append(f"Página {current_page + 1} de {total_label}")

    buttons = []
    for index, item in enumerate(items, start=start + 1):
        location = item.get("location") or "Sin ubicación"
        buttons.append([
            {
                "text": _wallapop_trim_button(
                    f"{index}. {_wallapop_format_price(item)} | {item.get('title', '')} | {location}"
                ),
                "callback_data": f"wallapop_item:{index - 1}",
            }
        ])

    nav_buttons = []
    if current_page > 0:
        nav_buttons.append({"text": "⬅️ Anterior", "callback_data": "wallapop_page:prev"})

    loaded_items = result_session.get("loaded_items", [])
    if (current_page + 1) * WALLAPOP_UI_PAGE_SIZE < len(loaded_items) or result_session.get("next_page_token"):
        nav_buttons.append({"text": "Siguiente ➡️", "callback_data": "wallapop_page:next"})

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([{"text": "🔎 Buscar otro producto", "callback_data": "wallapop_new_search"}])

    if search_url:
        buttons.append([{"text": "🔗 Abrir búsqueda en Wallapop", "url": search_url}])

    return {
        "type": "menu",
        "text": "\n".join(text_lines),
        "buttons": buttons,
    }


def _wallapop_item_caption(item, result_session=None):
    lines = [
        f"🛒 {item.get('title', 'Artículo')}",
        f"💸 {_wallapop_format_price(item)}",
    ]

    location_parts = [part for part in [item.get("location"), item.get("region")] if part]
    if location_parts:
        lines.append(f"📍 {', '.join(location_parts)}")

    if item.get("condition"):
        condition_labels = {
            "new": "Nuevo",
            "as_good_as_new": "Como nuevo",
            "in_box": "En su caja",
            "good": "Buen estado",
            "used": "Usado",
        }
        lines.append(f"📦 {condition_labels.get(item['condition'], item['condition'])}")

    created_label = _wallapop_format_datetime(item.get("created_label"))
    age_label = _wallapop_format_age(item.get("created_at"))
    if created_label:
        suffix = f" ({age_label})" if age_label else ""
        lines.append(f"🕒 Publicado: {created_label}{suffix}")

    modified_label = _wallapop_format_datetime(item.get("modified_label"))
    if modified_label:
        lines.append(f"✏️ Última edición: {modified_label}")

    if result_session:
        price_insight = _wallapop_price_insight(item, result_session)
        if price_insight:
            lines.append(
                f"📊 {price_insight['label']} frente a {price_insight['comparable_count']} comparables"
            )
            lines.append(f"Referencia media: {price_insight['median_price']:.0f}€")

    extra_flags = []
    if item.get("shipping"):
        extra_flags.append("Envío")
    if item.get("reserved"):
        extra_flags.append("Reservado")
    if item.get("has_warranty"):
        extra_flags.append("Garantía")
    if item.get("is_refurbished"):
        extra_flags.append("Reacondicionado")
    if item.get("is_top_profile"):
        extra_flags.append("Top profile")
    if item.get("views") is not None:
        extra_flags.append(f"{item['views']} visualizaciones")

    if extra_flags:
        lines.append("• " + " | ".join(extra_flags))

    description = (item.get("description") or "").strip()
    if description:
        shortened = description[:500].rstrip()
        if len(description) > 500:
            shortened += "…"
        lines.append("")
        lines.append(shortened)

    return "\n".join(lines)[:1024]


def _wallapop_build_result_session(filters, search_result):
    result_session = {
        "filters": dict(filters),
        "loaded_items": list(search_result.get("items", [])),
        "next_page_token": search_result.get("next_page"),
        "current_page": 0,
        "summary": search_result.get("summary", ""),
        "search_url": search_result.get("search_url"),
    }
    _wallapop_apply_order(result_session)
    return result_session


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
        "Bienvenido. Cada chat mantiene su propio contexto, playlists y modos guiados.\n\n"
        "Puedes usar el bot de dos formas:\n"
        "1. Comando completo: /music Danza Kuduro\n"
        "2. Comando vacío en modo guiado: /translate, /wiki, /youtube, /music, /playlist, /wallapop\n\n"
        "Comandos principales:\n"
        "/library - abrir la biblioteca de Jellyfin\n"
        "/video <pelicula> - buscar una película\n"
        "/wiki <tema> - buscar en Wikipedia\n"
        "/img <tema> - buscar imágenes\n"
        "/weather <ciudad> - consultar el tiempo\n"
        "/youtube <busqueda> - buscar y enviar un vídeo\n"
        "/music <cancion> - buscar y enviar audio\n"
        "/wallapop - buscar productos con filtros guiados\n"
        "/translate <destino> | <texto> - traducir texto\n"
        "/playlist - gestionar playlists\n"
        "/helper - ver la guía completa\n\n"
        "Ejemplos:\n"
        "/youtube hall of fame\n"
        "/music Danza Kuduro\n"
        "/wallapop iphone 15\n"
        "/translate en | hola mundo"
    )


def _helper_message():
    return (
        "Guía completa del bot:\n\n"
        "Información general:\n"
        "- Cada usuario tiene su propio contexto, playlists y sesiones guiadas.\n"
        "- Muchos comandos se pueden usar vacíos y el bot te irá pidiendo lo necesario.\n"
        "- Si escribes un comando que no existe, el bot te avisará.\n\n"
        "Comandos generales:\n"
        "/start - bienvenida y resumen rápido.\n"
        "/helper - guía completa de comandos y modos de uso.\n\n"
        "Biblioteca Jellyfin:\n"
        "/library - abre la biblioteca.\n"
        "/menu - alias de /library.\n"
        "/catalog - alias de /library.\n"
        "/video <pelicula> - busca y reproduce una película.\n"
        "/video - modo guiado: te pregunta qué película quieres ver.\n\n"
        "Wikipedia y búsqueda informativa:\n"
        "/wiki <tema> - busca en Wikipedia.\n"
        "/wiki - modo guiado: te pregunta qué quieres buscar.\n\n"
        "Imágenes:\n"
        "/img <tema> - busca imágenes.\n"
        "/image <tema> - alias de /img.\n"
        "/img - modo guiado: te pregunta qué imagen quieres buscar.\n\n"
        "Tiempo:\n"
        "/weather <ciudad> - consulta el tiempo.\n"
        "/tiempo <ciudad> - alias de /weather.\n"
        "/weather - modo guiado: te pregunta la ciudad.\n\n"
        "YouTube:\n"
        "/youtube <busqueda> - busca y envía automáticamente el mejor vídeo.\n"
        "/youtube - modo guiado: te pregunta qué vídeo quieres buscar.\n\n"
        "Música:\n"
        "/music <cancion> - busca y envía audio.\n"
        "/music - modo guiado: te pregunta qué canción quieres buscar.\n"
        "/music buscar <consulta> - muestra resultados musicales con botones.\n"
        "/music fav <consulta> - guarda una canción en favoritos.\n"
        "/music favs - muestra tus favoritos.\n"
        "/music recomendar - recomienda música según historial y favoritos.\n"
        "/music - también puede usarse vacío para iniciar la búsqueda guiada.\n\n"
        "Wallapop:\n"
        "/wallapop - inicia una búsqueda guiada.\n"
        "/wallapop <producto> - precarga el producto y luego te pide filtros.\n"
        "- Puedes filtrar por estado, rango de precio, ubicación, radio y orden.\n\n"
        "Traducción:\n"
        "/translate <destino> | <texto> - traduce desde idioma automático.\n"
        "/translate <origen> | <destino> | <texto> - traduce indicando idioma origen.\n"
        "/translate - modo guiado: te pide el texto y luego te deja elegir idioma.\n"
        "- Dentro de /translate también puedes enviar una nota de voz en vez de texto.\n"
        "- Tras traducir, puedes usar el botón de pronunciación para escuchar el resultado.\n\n"
        "Playlists:\n"
        "/playlist - abre el gestor interactivo de playlists.\n"
        "/playlist crear <nombre> - crea una playlist.\n"
        "/playlist listas - lista tus playlists.\n"
        "/playlist add <nombre> | <canción> - añade una canción.\n"
        "/playlist ver <nombre> - muestra la playlist.\n"
        "/playlist play <nombre> - reproduce la primera canción.\n"
        "/playlist remove <nombre> | <posición> - quita una canción.\n"
        "/playlist borrar <nombre> - elimina la playlist.\n"
        "- En modo guiado de /playlist puedes elegir la playlist, añadir, quitar, ver, reproducir o borrar con botones.\n\n"
        "Ejemplos rápidos:\n"
        "/library\n"
        "/video interestellar\n"
        "/wiki chuck norris\n"
        "/img cascadas\n"
        "/weather madrid\n"
        "/youtube waka waka shakira\n"
        "/music Danza Kuduro\n"
        "/wallapop steam deck\n"
        "/translate en | hola mundo\n"
        "/playlist crear motivacion\n"
        "/playlist add motivacion | believer imagine dragons"
    )


def run_direct_intent(intent, query, chat_id=None):
    if intent == "movies":
        result = jellyfin.search_movie(query)
        result_type = result.get("type")

        if result_type == "uncertain":
            return {"type": "text", "text": result.get("message", "No se encontraron películas")}, ["jellyfin_tool"]

        if result_type == "suggestion":
            movie = result.get("result") or {}
            item_id = movie.get("Id")
            if item_id:
                return {
                    "type": "menu",
                    "text": result.get("message", "¿Te refieres a esta película?"),
                    "buttons": [
                        [
                            {"text": "✅ Sí", "callback_data": f"movie_suggest_yes:{item_id}"},
                            {"text": "❌ No", "callback_data": "movie_suggest_no"},
                        ]
                    ],
                }, ["jellyfin_tool"]

            return {"type": "text", "text": result.get("message", "No estoy seguro de la película")}, ["jellyfin_tool"]

        if result_type == "match":
            movie = result.get("result")
            if not movie:
                return {"type": "text", "text": "No se encontraron películas"}, ["jellyfin_tool"]

            item_id = movie["Id"]
            return {
                "type": "video",
                "title": movie.get("Name"),
                "image": jellyfin.get_image_url(movie),
                "item_id": item_id,
                "audio_tracks": jellyfin.get_audio_tracks(item_id),
                "score": result.get("score"),
            }, ["jellyfin_tool"]

        return {"type": "text", "text": "No se encontraron películas"}, ["jellyfin_tool"]

    if intent == "library":
        return {
            "type": "menu",
            "text": "🎥 Biblioteca",
            "buttons": [
                [{"text": "🎬 Películas", "callback_data": "open_library:movies"}],
                [{"text": "📺 Series", "callback_data": "open_library:series"}],
            ]
        }, ["jellyfin_library"]

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


def _format_jellyfin_lang(lang):
    if not lang:
        return "Desconocido"

    lang = lang.lower()

    if lang.startswith("spa"):
        return "🇪🇸 Español"
    if lang.startswith("eng"):
        return "🇬🇧 Inglés"
    if lang.startswith("ger"):
        return "🇩🇪 Alemán"
    if lang.startswith("rus"):
        return "🇷🇺 Ruso"
    return f"🎧 {lang.upper()}"


def _build_jellyfin_audio_buttons(item_id, audio_tracks):
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
                "text": _format_jellyfin_lang(lang),
                "url": url,
            }
        ])

    if not buttons:
        buttons = [[{"text": "▶ Reproducir", "url": jellyfin.get_stream_url(item_id, 0)}]]

    return buttons


def _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks):
    buttons = _build_jellyfin_audio_buttons(item_id, audio_tracks)
    caption = f"🎬 {title}\n\nElige idioma:"

    if image:
        send_photo_with_buttons(chat_id, image, caption, buttons)
    else:
        send_message_with_buttons(chat_id, caption, buttons)


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
                    "buttons": _wallapop_condition_buttons(),
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
                        _finalize_text_response(chat_id, result, placeholder_message_id, stop_placeholder)
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
                        "buttons": _wallapop_order_buttons(),
                    }
                else:
                    session["location_label"] = text.strip()
                    session["step"] = "await_radius"
                    set_wallapop_session(chat_id, session)
                    result = {
                        "type": "menu",
                        "text": f"Ubicación: {session['location_label']}\n\n¿Qué radio quieres usar?",
                        "buttons": _wallapop_radius_buttons(),
                    }
                sources = ["wallapop_tool"]

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
            clear_wallapop_result_session(chat_id)
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
            if not query:
                set_pending_followup(chat_id, "music")
                _finalize_text_response(
                    chat_id,
                    "¿Qué canción quieres buscar?",
                    placeholder_message_id,
                    stop_placeholder
                )
                return
            result, sources = run_direct_intent("music", query, chat_id)

        elif text.startswith("/wallapop"):
            query = text.replace("/wallapop", "", 1).strip()
            clear_wallapop_result_session(chat_id)
            session = {
                "step": "await_query",
                "query": "",
                "condition": "any",
                "min_price": None,
                "max_price": None,
                "location_label": "",
                "distance_km": None,
                "order": "newest",
            }

            if query:
                session["query"] = query
                session["step"] = "await_condition"
                set_wallapop_session(chat_id, session)
                result = {
                    "type": "menu",
                    "text": (
                        f"Producto: {query}\n\n"
                        "¿Qué estado quieres filtrar?"
                    ),
                    "buttons": _wallapop_condition_buttons(),
                }
            else:
                set_wallapop_session(chat_id, session)
                result = "¿Qué producto quieres buscar en Wallapop?"
            sources = ["wallapop_tool"]

        elif text.startswith("/library") or text.startswith("/menu") or text.startswith("/catalog"):
            result, sources = run_direct_intent("library", "", chat_id)

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
            send_images(chat_id, images[:6])

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

        if isinstance(result, dict) and result.get("type") == "wallapop":
            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
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
            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
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

            _clear_placeholder(chat_id, placeholder_message_id, stop_placeholder)
            _send_jellyfin_video_response(chat_id, title, image, item_id, audio_tracks)
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
                _wallapop_order_buttons(),
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
                result_session = _wallapop_build_result_session(session, result)
                set_wallapop_result_session(chat_id, result_session)
                menu = _wallapop_results_menu(result_session)
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
                _wallapop_apply_order(result_session)

            max_page = max(0, _wallapop_total_loaded_pages(result_session) - 1)
            result_session["current_page"] = min(target_page, max_page)
            set_wallapop_result_session(chat_id, result_session)
            menu = _wallapop_results_menu(result_session)
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
            caption = _wallapop_item_caption(item, result_session)
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
