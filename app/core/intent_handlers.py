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


_initialize_handlers()


