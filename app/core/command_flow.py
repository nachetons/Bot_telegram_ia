"""Command flow with registry pattern."""

from typing import Tuple, List, Any
from app.core.chat_state import (
    clear_base_chat_state,
    clear_pending_followup,
    clear_prediction_session,
    clear_recipe_session,
    clear_wallapop_result_session,
    set_prediction_session,
    set_pending_followup,
    set_translate_result,
    set_translate_session,
    set_wallapop_session,
    set_recipe_session,
)
from app.core.access_control import is_admin, list_users
from app.core.direct_intents import run_direct_intent
from app.core.playlist_flow import handle_playlist_command
from app.tools.wallapop_alerts import get_alert_for_chat
from app.utils.bot_ui import helper_message, start_message
from app.utils.access_ui import build_control_menu
from app.utils.wallapop_ui import (
    wallapop_alerts_menu,
    wallapop_condition_buttons,
    wallapop_radius_buttons,
    wallapop_order_buttons,
)
from app.utils.prediction_ui import (
    prediction_menu,
    history_menu,
    match_prediction_menu,
    top_scorer_menu,
    rival_analysis_menu
)
from app.utils.recipe_ui import recipe_menu, recipe_history_menu
from app.tools.manga import manga_menu, manga_search, manga_read, manga_auto_search, manga_get_history, manga_get_favorites, manga_download
from app.core.command_registry import command_registry


def _handle_clear(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /clear."""
    clear_recipe_session(chat_id)
    return True, "📹 He limpiado el contexto de este chat. Puedes empezar de nuevo cuando quieras.", []


def _handle_start(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /start."""
    clear_base_chat_state(chat_id)
    clear_wallapop_result_session(chat_id)
    return True, start_message(), []


def _handle_helper(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /helper o /help."""
    clear_base_chat_state(chat_id)
    return True, helper_message(), []


def _handle_video(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /video."""
    query = text.replace("/video", "").strip()
    if not query:
        set_pending_followup(chat_id, "movies")
        return True, "¿Qué película quieres ver?", []

    handled, result, sources = run_direct_intent("movies", query, chat_id)
    return handled, result, sources


def _handle_image(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /img o /image."""
    query = text.replace("/img", "").replace("/image", "").strip()
    if not query:
        set_pending_followup(chat_id, "images")
        return True, "¿Qué imagen quieres buscar?", []

    handled, result, sources = run_direct_intent("images", query, chat_id)
    return handled, result, sources


def _handle_wiki(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /wiki."""
    query = text.replace("/wiki", "").strip()
    if not query:
        set_pending_followup(chat_id, "wiki")
        return True, "¿Qué quieres buscar en la wiki?", []

    handled, result, sources = run_direct_intent("wiki", query, chat_id)
    return handled, result, sources


def _handle_weather(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /tiempo o /weather."""
    command = "/tiempo" if text.startswith("/tiempo") else "/weather"
    query = text.replace(command, "", 1).strip()
    if not query:
        set_pending_followup(chat_id, "weather")
        return True, "¿De qué ciudad quieres saber el tiempo?", []

    handled, result, sources = run_direct_intent("weather", query, chat_id)
    return handled, result, sources


def _handle_youtube(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /youtube."""
    query = text.replace("/youtube", "", 1).strip()
    if not query:
        set_pending_followup(chat_id, "youtube")
        return True, "¿Qué vídeo quieres buscar en YouTube?", []

    handled, result, sources = run_direct_intent("youtube", query, chat_id)
    return handled, result, sources


def _handle_music(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /music."""
    query = text.replace("/music", "", 1).strip()
    if not query:
        set_pending_followup(chat_id, "music")
        return True, "¿Qué canción quieres buscar?", []

    handled, result, sources = run_direct_intent("music", query, chat_id)
    return handled, result, sources


def _handle_wallapop(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /wallapop."""
    from app.tools.wallapop_alerts import get_alert_for_chat

    query = text.replace("/wallapop", "", 1).strip()
    clear_pending_followup(chat_id)
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
        return True, {
            "type": "menu",
            "text": f"Producto: {query}\n\n¿Qué estado quieres filtrar?",
            "buttons": wallapop_condition_buttons(),
        }, ["wallapop_tool"]

    set_wallapop_session(chat_id, session)
    return True, "¿Qué producto quieres buscar en Wallapop?", ["wallapop_tool"]


def _handle_mis_alertas(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /mis_alertas."""
    return True, wallapop_alerts_menu(get_alert_for_chat(chat_id)), ["wallapop_tool"]


def _handle_control(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /control."""
    if not is_admin(chat_id):
        return True, "❌ Este panel es solo para administradores.", []
    users = list_users("all")
    return True, build_control_menu(users, current_filter="all", page=0), ["access_control"]


def _handle_library(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /library, /menu o /catalog."""
    from app.core.chat_state import clear_all_chat_state

    # Limpiar estado anterior antes de mostrar nuevo menú
    clear_all_chat_state(chat_id)

    handled, result, sources = run_direct_intent("library", "", chat_id)

    # Marcar para editar en lugar de enviar nuevo mensaje
    if isinstance(result, dict) and result.get("type") == "menu":
        result["_edit"] = True  # Bandera para editar el último mensaje

    return handled, result, sources


def _handle_translate(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /translate."""
    from app.tools.translate import build_translate_result_menu, translate_language_buttons, translate_payload

    query = text.replace("/translate", "", 1).strip()
    clear_pending_followup(chat_id)
    if not query:
        set_translate_session(chat_id, "await_text")
        return True, "¿Qué texto quieres traducir?", ["translate_tool"]
    if "|" not in query:
        set_translate_session(chat_id, "await_language", query)
        return True, {
            "type": "menu",
            "text": "¿A qué idioma quieres traducirlo?",
            "buttons": translate_language_buttons(),
        }, ["translate_tool"]

    payload = translate_payload(query)
    if payload.get("error"):
        return True, payload["error"], ["translate_tool"]

    set_translate_result(chat_id, payload)
    return True, build_translate_result_menu(payload), ["translate_tool"]


def _handle_playlist(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /playlist."""
    command = text.replace("/playlist", "", 1).strip()
    result, sources = handle_playlist_command(command, chat_id, None)
    return True, result, sources


def _handle_prediction(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /prediccion o /prediction."""
    from app.core.direct_intents import run_direct_intent

    query = text.replace("/prediccion", "", 1).replace("/prediction", "", 1).strip()
    clear_pending_followup(chat_id)
    clear_prediction_session(chat_id)
    clear_recipe_session(chat_id)

    if not query:
        return True, prediction_menu(), ["sports_prediction_tool"]

    if query.lower() in ["historial", "mis predicciones", "history"]:
        handled, result, sources = run_direct_intent("prediction", "history", chat_id)
        return handled, result, sources

    # Caso principal: predecir partido con equipo
    handled, result, sources = run_direct_intent("prediction", query, chat_id)
    return handled, result, sources



def _handle_recipe(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /receta o /recipe."""
    from app.tools.recipe import search_recipes
    from app.utils.recipe_ui import recipe_list_menu

    query = text.replace("/receta", "", 1).replace("/recipe", "", 1).strip()
    clear_pending_followup(chat_id)

    if not query:
        from app.utils.recipe_ui import recipe_menu
        return True, recipe_menu(), ["recipe_tool"]

    results = search_recipes(query)
    menu = recipe_list_menu(query, results.get("recipes", []))
    clear_recipe_session(chat_id)

    return True, menu, ["recipe_tool"]


def _handle_mis_recetas(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /mis_recetas."""
    handled, result, sources = run_direct_intent("recipe", "history", chat_id)
    return handled, result, sources


def _handle_clear_recipes(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /clear_recipes."""
    handled, result, sources = run_direct_intent("recipe", "clear", chat_id)
    return handled, result, sources


def _handle_manga(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Handler para /manga."""
    query = text.replace("/manga", "", 1).strip()

    if not query:
        return True, manga_menu(chat_id), ["manga_tool"]

    # Detectar si es comando especial o búsqueda
    if query.lower().startswith("ver "):
        search_query = query[4:].strip()
        return True, manga_auto_search(chat_id, search_query), ["manga_tool"]

    if query.lower().startswith("historial"):
        return True, manga_get_history(chat_id), ["manga_tool"]

    if query.lower().startswith("favoritos") or query.lower().startswith("fav "):
        fav_query = query[4:].strip() if query.lower().startswith("fav ") else ""
        if not fav_query:
            return True, manga_get_favorites(chat_id), ["manga_tool"]
        # Buscar y añadir a favoritos
        search_result = manga_search(fav_query)
        if "results" in search_result and search_result["results"]:
            first_manga = search_result["results"][0]
            title = first_manga.get("title", "Sin título")
            url = first_manga.get("url", "")
            from app.tools.manga import manga_add_favorite
            return True, manga_add_favorite(chat_id, title, url), ["manga_tool"]
        return True, search_result, ["manga_tool"]

    if query.lower().startswith("descargar ") or query.lower().startswith("dl "):
        dl_query = query[10:].strip() if query.lower().startswith("descargar ") else query[3:]
        return True, manga_download(chat_id, dl_query), ["manga_tool"]

    # Búsqueda automática en todos los tipos
    return True, manga_auto_search(chat_id, query), ["manga_tool"]


# Registrar comandos
def _initialize_commands():
    """Inicializa el registro de comandos."""
    command_registry.register("/clear", _handle_clear)
    command_registry.register("/start", _handle_start)
    command_registry.register("/helper", _handle_helper)
    command_registry.register("/help", _handle_helper)
    command_registry.register("/video", _handle_video)
    command_registry.register("/img", _handle_image)
    command_registry.register("/image", _handle_image)
    command_registry.register("/wiki", _handle_wiki)
    command_registry.register("/tiempo", _handle_weather)
    command_registry.register("/weather", _handle_weather)
    command_registry.register("/youtube", _handle_youtube)
    command_registry.register("/music", _handle_music)
    command_registry.register("/wallapop", _handle_wallapop)
    command_registry.register("/mis_alertas", _handle_mis_alertas)
    command_registry.register("/control", _handle_control)
    command_registry.register("/library", _handle_library)
    command_registry.register("/menu", _handle_library)
    command_registry.register("/catalog", _handle_library)
    command_registry.register("/translate", _handle_translate)
    command_registry.register("/playlist", _handle_playlist)
    command_registry.register("/prediccion", _handle_prediction)
    command_registry.register("/prediction", _handle_prediction)
    command_registry.register("/receta", _handle_recipe)
    command_registry.register("/recipe", _handle_recipe)
    command_registry.register("/mis_recetas", _handle_mis_recetas)
    command_registry.register("/clear_recipes", _handle_clear_recipes)
    command_registry.register("/manga", _handle_manga)


_initialize_commands()


def handle_slash_command(text: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Maneja comandos slash usando el registry."""
    # Extraer nombre del comando
    parts = text.split()
    if not parts or not parts[0].startswith("/"):
        return False, None, []

    command_name = parts[0]

    # Buscar handler en el registry
    handler = command_registry.get_handler(command_name)
    if handler:
        result_tuple = handler.handler(text, chat_id)
        # Asegurar que siempre devuelve exactamente 3 valores
        if isinstance(result_tuple, tuple) and len(result_tuple) == 3:
            return result_tuple[0], result_tuple[1], result_tuple[2]
        elif isinstance(result_tuple, tuple):
            # Si tiene más de 3 valores, tomar solo los primeros 3
            return result_tuple[0], result_tuple[1], list(result_tuple[2]) if len(result_tuple) > 2 else []
        else:
            return True, result_tuple, []

    # Fallback para comandos desconocidos
    if text.startswith("/"):
        return True, "Ese comando no existe. Usa /helper para ver los comandos disponibles.", []

    return False, None, []
