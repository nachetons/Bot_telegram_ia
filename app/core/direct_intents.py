"""Intent runner using the dispatcher pattern."""

from typing import Any, Dict, List, Tuple

# Import para inicializar handlers
from app.core import intent_handlers


def run_direct_intent(intent: str, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
    """Ejecuta un intent usando el dispatcher centralizado."""
    from app.core.intent_dispatcher import intent_dispatcher
    
    handler = intent_dispatcher.get_handler(intent)
    if not handler:
        return False, {"type": "text", "text": f"Intent '{intent}' no encontrado"}, []
    
    handled, result, sources = handler.handle(query, chat_id)
    return handled, result, sources


# Funciones de compatibilidad para command_flow.py
def run_movies_intent(query: str, chat_id: int):
    """Ejecuta el intent movies con la lógica real."""
    from app.tools.jellyfin import jellyfin
    
    if not query.strip():
        return True, {"type": "text", "text": "¿Qué película quieres ver?"}, ["jellyfin_tool"]
    
    result = jellyfin.search_movie(query)
    result_type = result.get("type")

    if result_type == "uncertain":
        return True, {"type": "text", "text": result.get("message", "No se encontraron películas")}, ["jellyfin_tool"]

    if result_type == "suggestion":
        movie = result.get("result") or {}
        item_id = movie.get("Id")
        if item_id:
            return True, {
                "type": "menu",
                "text": result.get("message", "¿Te refieres a esta película?"),
                "buttons": [
                    [{"text": "✅ Sí", "callback_data": f"movie_suggest_yes:{item_id}"}, {"text": "❌ No", "callback_data": "movie_suggest_no"}],
                ],
            }, ["jellyfin_tool"]

        return True, {"type": "text", "text": result.get("message", "No estoy seguro de la película")}, ["jellyfin_tool"]

    if result_type == "match":
        movie = result.get("result")
        if not movie:
            return True, {"type": "text", "text": "No se encontraron películas"}, ["jellyfin_tool"]

        item_id = movie["Id"]
        return True, {
            "type": "video",
            "title": movie.get("Name"),
            "image": jellyfin.get_image_url(movie),
            "item_id": item_id,
            "audio_tracks": jellyfin.get_audio_tracks(item_id),
            "score": result.get("score"),
        }, ["jellyfin_tool"]

    return True, {"type": "text", "text": "No se encontraron películas"}, ["jellyfin_tool"]


def run_library_intent(query: str, chat_id: int):
    """Ejecuta el intent library con la lógica real."""
    from app.tools.jellyfin import jellyfin
    
    # Si query es vacío, mostrar menú principal
    if not query.strip():
        return True, {
            "type": "menu",
            "text": "🎥 Biblioteca Jellyfin\n¿Qué quieres ver?",
            "buttons": [
                [{"text": "🎬 Películas", "callback_data": "open_library:movies"}],
                [{"text": "📺 Series", "callback_data": "open_library:series"}],
            ]
        }, ["jellyfin_library"]
    
    # Si query es "movies" o "series", cargar esa categoría
    if query.lower() in ["movies", "películas"]:
        movies = jellyfin.get_all_movies()
        
        buttons = []
        for movie in movies[:20]:
            item_id = movie.get("Id")
            title = movie.get("Name", "Sin título")[:40]
            buttons.append([{"text": f"🎬 {title}", "callback_data": f"play_movie:{item_id}"}])

        return True, {"type": "menu", "text": "🎬 Películas (1-20)", "buttons": buttons}, ["jellyfin_library"]
    
    if query.lower() in ["series", "series de tv"]:
        series = jellyfin.get_all_series()
        
        buttons = []
        for series_item in series[:20]:
            item_id = series_item.get("Id")
            title = series_item.get("Name", "Sin título")[:40]
            buttons.append([{"text": f"📺 {title}", "callback_data": f"play_series:{item_id}"}])

        return True, {"type": "menu", "text": "📺 Series (1-20)", "buttons": buttons}, ["jellyfin_library"]
    
    # Fallback: mostrar menú principal
    return run_library_intent("", chat_id)


def run_wiki_intent(query: str, chat_id: int):
    """Ejecuta el intent wiki con la lógica real."""
    from app.tools.wiki import wikipedia
    
    result, sources = wikipedia(query)
    # Asegurar que devuelve exactamente 3 valores
    return True, result, sources


def run_weather_intent(query: str, chat_id: int):
    """Ejecuta el intent weather con la lógica real."""
    from app.tools.weather import get_weather
    
    result, sources = get_weather(query)
    # Asegurar que devuelve exactamente 3 valores
    return True, result, sources


def run_images_intent(query: str, chat_id: int):
    """Ejecuta el intent images con la lógica real."""
    from app.tools.images import get_images
    
    images = get_images(query)
    return True, {"type": "images", "images": images}, ["images_tool"]


def run_youtube_intent(query: str, chat_id: int):
    """Ejecuta el intent youtube con la lógica real."""
    from app.tools.youtube import download_youtube_video
    
    result = download_youtube_video(query)
    # Asegurar que devuelve exactamente 3 valores
    return True, result, ["youtube_tool"]


def run_music_intent(query: str, chat_id: int):
    """Ejecuta el intent music con la lógica real."""
    from app.tools.music_local import music_run
    
    result = music_run(query, chat_id)
    # Asegurar que devuelve exactamente 3 valores
    return True, result, ["music_tool"]
