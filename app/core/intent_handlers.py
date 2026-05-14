"""Handlers for specific intents using the strategy pattern."""

from typing import Any, List, Tuple


class StartIntentHandler:
    """Handler para el intent 'start'."""

    def get_intent_name(self) -> str:
        return "start"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import clear_base_chat_state, clear_wallapop_result_session
        
        clear_base_chat_state(chat_id)
        clear_wallapop_result_session(chat_id)
        return True, "Bienvenido", []


class HelperIntentHandler:
    """Handler para el intent 'helper'."""

    def get_intent_name(self) -> str:
        return "helper"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import clear_base_chat_state
        
        clear_base_chat_state(chat_id)
        return True, "Helper", []


class MoviesIntentHandler:
    """Handler para el intent 'movies'."""

    def get_intent_name(self) -> str:
        return "movies"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_movies_intent
        
        if not query.strip():
            set_pending_followup(chat_id, "movies")
            return True, "¿Qué película quieres ver?", []
        
        return run_movies_intent(query, chat_id)


class ImagesIntentHandler:
    """Handler para el intent 'images'."""

    def get_intent_name(self) -> str:
        return "images"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_images_intent
        
        if not query.strip():
            set_pending_followup(chat_id, "images")
            return True, "¿Qué imagen quieres buscar?", []
        
        return run_images_intent(query, chat_id)


class WikiIntentHandler:
    """Handler para el intent 'wiki'."""

    def get_intent_name(self) -> str:
        return "wiki"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_wiki_intent
        
        if not query.strip():
            set_pending_followup(chat_id, "wiki")
            return True, "¿Qué quieres buscar en la wiki?", []
        
        return run_wiki_intent(query, chat_id)


class WeatherIntentHandler:
    """Handler para el intent 'weather'."""

    def get_intent_name(self) -> str:
        return "weather"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_weather_intent
        
        if not query.strip():
            set_pending_followup(chat_id, "weather")
            return True, "¿De qué ciudad quieres saber el tiempo?", []
        
        return run_weather_intent(query, chat_id)


class YoutubeIntentHandler:
    """Handler para el intent 'youtube'."""

    def get_intent_name(self) -> str:
        return "youtube"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_youtube_intent
        
        if not query.strip():
            set_pending_followup(chat_id, "youtube")
            return True, "¿Qué vídeo quieres buscar en YouTube?", []
        
        return run_youtube_intent(query, chat_id)


class MusicIntentHandler:
    """Handler para el intent 'music'."""

    def get_intent_name(self) -> str:
        return "music"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_music_intent
        
        if not query.strip():
            set_pending_followup(chat_id, "music")
            return True, "¿Qué canción quieres buscar?", []
        
        return run_music_intent(query, chat_id)


class LibraryIntentHandler:
    """Handler para el intent 'library'."""

    def get_intent_name(self) -> str:
        return "library"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.direct_intents import run_library_intent
        
        # El query puede ser vacío o contener la categoría (movies/series)
        return run_library_intent(query, chat_id)


class TranslateIntentHandler:
    """Handler para el intent 'translate'."""

    def get_intent_name(self) -> str:
        return "translate"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.tools.translate import build_translate_result_menu, translate_language_buttons, translate_payload
        from app.core.chat_state import set_translate_session, set_translate_result
        
        if not query.strip():
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


class PlaylistIntentHandler:
    """Handler para el intent 'playlist'."""

    def get_intent_name(self) -> str:
        return "playlist"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.playlist_flow import handle_playlist_command
        
        command = query.strip()
        result, sources = handle_playlist_command(command, chat_id, None)
        return True, *result, sources


class PredictionIntentHandler:
    """Handler para el intent 'prediction'."""

    def get_intent_name(self) -> str:
        return "prediction"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import clear_prediction_session, clear_recipe_session
        
        clear_prediction_session(chat_id)
        clear_recipe_session(chat_id)

        if not query.strip():
            return True, {"type": "menu", "text": "Prediction menu"}, ["sports_prediction_tool"]

        # Llamada real al tool de predicciones
        from app.tools.sports_prediction import predict_match
        
        result = predict_match(query, chat_id=chat_id)
        
        if result.get("error"):
            return True, {"type": "text", "text": f"❌ {result['error']}"}, ["sports_prediction_tool"]
        
        from app.utils.prediction_ui import prediction_result_menu
        return prediction_result_menu(result, chat_id), ["sports_prediction_tool"]


class RecipeIntentHandler:
    """Handler para el intent 'recipe'."""

    def get_intent_name(self) -> str:
        return "recipe"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.tools.recipe import search_recipes
        from app.utils.recipe_ui import recipe_list_menu, recipe_menu
        from app.core.chat_state import clear_recipe_session
        
        if not query.strip():
            return True, recipe_menu(), ["recipe_tool"]

        results = search_recipes(query)
        menu = recipe_list_menu(query, results.get("recipes", []))
        clear_recipe_session(chat_id)

        return True, *menu, ["recipe_tool"]


class WallapopIntentHandler:
    """Handler para el intent 'wallapop'."""

    def get_intent_name(self) -> str:
        return "wallapop"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import clear_wallapop_result_session, set_wallapop_session
        
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

        if query.strip():
            session["query"] = query.strip()
            session["step"] = "await_condition"
            set_wallapop_session(chat_id, session)
            return True, {
                "type": "menu",
                "text": f"Producto: {query}\n\n¿Qué estado quieres filtrar?",
                "buttons": [],
            }, ["wallapop_tool"]

        set_wallapop_session(chat_id, session)
        return True, "¿Qué producto quieres buscar en Wallapop?", ["wallapop_tool"]


class MisAlertasIntentHandler:
    """Handler para el intent 'mis_alertas'."""

    def get_intent_name(self) -> str:
        return "mis_alertas"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.tools.wallapop_alerts import get_alert_for_chat
        from app.utils.wallapop_ui import wallapop_alerts_menu
        
        return True, wallapop_alerts_menu(get_alert_for_chat(chat_id)), ["wallapop_tool"]


class ControlIntentHandler:
    """Handler para el intent 'control'."""

    def get_intent_name(self) -> str:
        return "control"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.access_control import is_admin, list_users
        from app.utils.access_ui import build_control_menu
        
        if not is_admin(chat_id):
            return True, "⛔ Este panel es solo para administradores.", []
        
        users = list_users("all")
        return True, build_control_menu(users, current_filter="all", page=0), ["access_control"]


class ClearIntentHandler:
    """Handler para el intent 'clear'."""

    def get_intent_name(self) -> str:
        return "clear"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import clear_recipe_session
        
        clear_recipe_session(chat_id)
        return True, "🧹 He limpiado el contexto de este chat. Puedes empezar de nuevo cuando quieras.", []


class MisRecetasIntentHandler:
    """Handler para el intent 'mis_recetas'."""

    def get_intent_name(self) -> str:
        return "mis_recetas"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.direct_intents import run_direct_intent
        
        result = run_direct_intent("recipe", "history", chat_id)
        return True, *result


class ClearRecipesIntentHandler:
    """Handler para el intent 'clear_recipes'."""

    def get_intent_name(self) -> str:
        return "clear_recipes"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.direct_intents import run_direct_intent
        
        result = run_direct_intent("recipe", "clear", chat_id)
        return True, *result


class MangaIntentHandler:
    """Handler para el intent 'manga'."""

    def get_intent_name(self) -> str:
        return "manga"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.config import TELEGRAM_CHAT_ID
        
        if chat_id != TELEGRAM_CHAT_ID:
            return True, "⛔ Funcionalidad manga restringida por ahora.", []
        
        from app.core.chat_state import set_pending_followup
        from app.core.direct_intents import run_manga_intent
        from app.tools.manga import manga_menu
        
        if not query.strip():
            result = manga_menu(chat_id)
            result["_edit"] = True
            return True, result, ["manga_tool"]
        
        return run_manga_intent(query, chat_id)


class MangaManhwaIntentHandler:
    """Handler para el intent 'manga_manhwa' (búsqueda específica en Manhwaweb)."""

    def get_intent_name(self) -> str:
        return "manga_manhwa"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.config import TELEGRAM_CHAT_ID
        
        if chat_id != TELEGRAM_CHAT_ID:
            return True, "⛔ Funcionalidad manga restringida por ahora.", []
        
        from app.core.chat_state import set_pending_followup
        from app.tools.manga import manga_search, manga_manhwaweb_menu
        
        if not query.strip():
            result = manga_manhwaweb_menu()
            result["_edit"] = True
            return True, result, ["manga_tool"]
        
        # Buscar específicamente como manhwa
        result = manga_search(query, "manhwa")
        return True, result, ["manga_tool"]


class MangaDexIntentHandler:
    """Handler para el intent 'mangadex' (búsqueda en MangaDex)."""

    def get_intent_name(self) -> str:
        return "mangadex"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.config import TELEGRAM_CHAT_ID
        
        if chat_id != TELEGRAM_CHAT_ID:
            return True, "⛔ Funcionalidad manga restringida por ahora.", []
        
        from app.core.chat_state import set_pending_followup
        from app.tools.manga import mangadex_search, mangadex_menu, _results_menu, _register_menu_callback
        
        if not query.strip():
            result = mangadex_menu()
            result["_edit"] = True
            return True, result, ["manga_tool"]
        
        search_result = mangadex_search(query)
        result = _results_menu(
            f"MANGADEX - Resultados para: {query}",
            search_result.get("results", []),
            f"No encontre mangas en MangaDex para '{query}'.",
            _register_menu_callback(mangadex_menu()),
        )
        return True, result, ["manga_tool"]


class MangaVerManhwaIntentHandler:
    """Handler para el intent 'manga_vermanhwa' (búsqueda en VerManhwa)."""

    def get_intent_name(self) -> str:
        return "manga_vermanhwa"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.config import TELEGRAM_CHAT_ID
        
        if chat_id != TELEGRAM_CHAT_ID:
            return True, "⛔ Funcionalidad manga restringida por ahora.", []
        
        from app.core.chat_state import set_pending_followup
        from app.tools.manga import vermanhwa_search, vermanhwa_menu
        
        if not query.strip():
            result = vermanhwa_menu()
            result["_edit"] = True
            return True, result, ["manga_tool"]
        
        result = vermanhwa_search(query)
        return True, result, ["manga_tool"]


class ReminderIntentHandler:
    """Handler para el intent 'reminder' (flujo guiado de recordatorios)."""

    def get_intent_name(self) -> str:
        return "reminder"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.core.chat_state import get_reminder_session, clear_pending_followup, clear_reminder_session, set_reminder_session
        from app.utils.reminder_ui import reminder_create_step2, reminder_main_menu, reminder_created_menu

        session = get_reminder_session(chat_id) or {}
        step = session.get("step", "")

        if not query.strip():
            return True, "Por favor escribe algo para continuar con el recordatorio.", []

        # Paso 1: Esperando descripción de la tarea
        if step == "await_task":
            task = query.strip()
            clear_pending_followup(chat_id)
            set_reminder_session(chat_id, {"step": "await_date", "task": task})
            return True, reminder_create_step2(task), ["reminder_tool"]

        # Paso 2: Esperando fecha manual (YYYY-MM-DD)
        if step == "await_date_manual":
            from app.tools.reminders import add_reminder

            date_str = query.strip()
            clear_pending_followup(chat_id)
            clear_reminder_session(chat_id)

            task = session.get("task", "")
            result = add_reminder(chat_id, task, date_str)

            if result["ok"]:
                return True, reminder_created_menu(result), ["reminder_tool"]
            else:
                return True, {"type": "text", "text": f"No pude crear el recordatorio: {result['message']}", "_edit": True}, []

        # Si no hay paso activo, mostrar menú principal
        clear_pending_followup(chat_id)
        clear_reminder_session(chat_id)
        return True, reminder_main_menu(), ["reminder_tool"]


# Registrar todos los handlers
def _initialize_handlers():
    """Inicializa el dispatcher con todos los handlers."""
    from app.core.intent_dispatcher import intent_dispatcher
    
    intent_dispatcher.register(StartIntentHandler())
    intent_dispatcher.register(HelperIntentHandler())
    intent_dispatcher.register(MoviesIntentHandler())
    intent_dispatcher.register(ImagesIntentHandler())
    intent_dispatcher.register(WikiIntentHandler())
    intent_dispatcher.register(WeatherIntentHandler())
    intent_dispatcher.register(YoutubeIntentHandler())
    intent_dispatcher.register(MusicIntentHandler())
    intent_dispatcher.register(LibraryIntentHandler())
    intent_dispatcher.register(TranslateIntentHandler())
    intent_dispatcher.register(PlaylistIntentHandler())
    intent_dispatcher.register(PredictionIntentHandler())
    intent_dispatcher.register(RecipeIntentHandler())
    intent_dispatcher.register(WallapopIntentHandler())
    intent_dispatcher.register(MisAlertasIntentHandler())
    intent_dispatcher.register(ControlIntentHandler())
    intent_dispatcher.register(ClearIntentHandler())
    intent_dispatcher.register(MisRecetasIntentHandler())
    intent_dispatcher.register(ClearRecipesIntentHandler())
    intent_dispatcher.register(MangaIntentHandler())
    intent_dispatcher.register(MangaManhwaIntentHandler())
    intent_dispatcher.register(MangaDexIntentHandler())
    intent_dispatcher.register(MangaVerManhwaIntentHandler())
    intent_dispatcher.register(ReminderIntentHandler())


_initialize_handlers()


