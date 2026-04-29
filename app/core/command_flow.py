from app.core.chat_state import (
    clear_base_chat_state,
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

def handle_slash_command(text: str, chat_id):
    if text.startswith("/clear"):
        clear_recipe_session(chat_id)
        return True, "🧹 He limpiado el contexto de este chat. Puedes empezar de nuevo cuando quieras.", []

    if text.startswith("/start"):
        clear_base_chat_state(chat_id)
        clear_wallapop_result_session(chat_id)
        return True, start_message(), []

    if text.startswith("/helper") or text.startswith("/help"):
        clear_base_chat_state(chat_id)
        return True, helper_message(), []

    if text.startswith("/video"):
        query = text.replace("/video", "").strip()
        if not query:
            set_pending_followup(chat_id, "movies")
            return True, "¿Qué película quieres ver?", []
        return True, *run_direct_intent("movies", query, chat_id)

    if text.startswith("/img") or text.startswith("/image"):
        query = text.replace("/img", "").replace("/image", "").strip()
        if not query:
            set_pending_followup(chat_id, "images")
            return True, "¿Qué imagen quieres buscar?", []
        return True, *run_direct_intent("images", query, chat_id)

    if text.startswith("/wiki"):
        query = text.replace("/wiki", "").strip()
        if not query:
            set_pending_followup(chat_id, "wiki")
            return True, "¿Qué quieres buscar en la wiki?", []
        return True, *run_direct_intent("wiki", query, chat_id)

    if text.startswith("/tiempo") or text.startswith("/weather"):
        command = "/tiempo" if text.startswith("/tiempo") else "/weather"
        query = text.replace(command, "", 1).strip()
        if not query:
            set_pending_followup(chat_id, "weather")
            return True, "¿De qué ciudad quieres saber el tiempo?", []
        return True, *run_direct_intent("weather", query, chat_id)

    if text.startswith("/youtube"):
        query = text.replace("/youtube", "", 1).strip()
        if not query:
            set_pending_followup(chat_id, "youtube")
            return True, "¿Qué vídeo quieres buscar en YouTube?", []
        return True, *run_direct_intent("youtube", query, chat_id)

    if text.startswith("/music"):
        query = text.replace("/music", "", 1).strip()
        if not query:
            set_pending_followup(chat_id, "music")
            return True, "¿Qué canción quieres buscar?", []
        return True, *run_direct_intent("music", query, chat_id)

    if text.startswith("/wallapop"):
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
            return True, {
                "type": "menu",
                "text": (
                    f"Producto: {query}\n\n"
                    "¿Qué estado quieres filtrar?"
                ),
                "buttons": wallapop_condition_buttons(),
            }, ["wallapop_tool"]

        set_wallapop_session(chat_id, session)
        return True, "¿Qué producto quieres buscar en Wallapop?", ["wallapop_tool"]

    if text.startswith("/mis_alertas"):
        return True, wallapop_alerts_menu(get_alert_for_chat(chat_id)), ["wallapop_tool"]

    if text.startswith("/control"):
        if not is_admin(chat_id):
            return True, "⛔ Este panel es solo para administradores.", []
        users = list_users("all")
        return True, build_control_menu(users, current_filter="all", page=0), ["access_control"]

    if text.startswith("/library") or text.startswith("/menu") or text.startswith("/catalog"):
        return True, *run_direct_intent("library", "", chat_id)

    if text.startswith("/translate"):
        from app.tools.translate import build_translate_result_menu, translate_language_buttons, translate_payload

        query = text.replace("/translate", "", 1).strip()
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

    if text.startswith("/playlist"):
        command = text.replace("/playlist", "", 1).strip()
        result, sources = handle_playlist_command(command, chat_id, None)
        return True, result, sources

    if text.startswith("/prediccion") or text.startswith("/prediction"):
        query = text.replace("/prediccion", "", 1).replace("/prediction", "", 1).strip()
        clear_prediction_session(chat_id)
        clear_recipe_session(chat_id)

        if not query:
            return True, prediction_menu(), ["sports_prediction_tool"]

        if query.lower() in ["historial", "mis predicciones", "history"]:
            result, sources = run_direct_intent("prediction", "history", chat_id)
            return True, result, sources


    if text.startswith("/receta") or text.startswith("/recipe"):
        from app.tools.recipe import search_recipes
        from app.utils.recipe_ui import recipe_list_menu
        
        query = text.replace("/receta", "", 1).replace("/recipe", "", 1).strip()

        if not query:
            # Solo mostrar menú principal, sin guardar sesión
            from app.utils.recipe_ui import recipe_menu
            return True, recipe_menu(), ["recipe_tool"]

        results = search_recipes(query)
        
        # Mostrar resultados inmediatamente y limpiar sesión
        menu = recipe_list_menu(query, results.get("recipes", []))
        clear_recipe_session(chat_id)

        return True, menu, ["recipe_tool"]

    if text.startswith("/mis_recetas"):
        result, sources = run_direct_intent("recipe", "history", chat_id)
        return True, result, sources

    if text.startswith("/clear_recipes"):
        result, sources = run_direct_intent("recipe", "clear", chat_id)
        return True, result, sources

    if text.startswith("/"):
        return True, "Ese comando no existe. Usa /helper para ver los comandos disponibles.", []

    return False, None, []
