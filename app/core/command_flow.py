from app.core.chat_state import (
    clear_base_chat_state,
    clear_wallapop_result_session,
    set_pending_followup,
    set_translate_result,
    set_translate_session,
    set_wallapop_session,
)
from app.core.direct_intents import run_direct_intent
from app.core.playlist_flow import handle_playlist_command
from app.utils.bot_ui import helper_message, start_message
from app.utils.wallapop_ui import (
    wallapop_condition_buttons,
    wallapop_radius_buttons,
    wallapop_order_buttons,
)


def handle_slash_command(text: str, chat_id):
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

    if text.startswith("/"):
        return True, "Ese comando no existe. Usa /helper para ver los comandos disponibles.", []

    return False, None, []
