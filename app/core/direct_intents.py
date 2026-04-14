from app.services.agent import agent
from app.tools.jellyfin import jellyfin


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
