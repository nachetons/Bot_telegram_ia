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

    if intent == "prediction":
        from app.tools.sports_prediction import predict_match, get_user_predictions
        
        # Si query es vacío o solo espacios, devolver menú principal
        if not query or not query.strip():
            from app.utils.prediction_ui import prediction_menu
            return prediction_menu(), ["sports_prediction_tool"]
        
        # Si es "history" o similar, mostrar historial
        if query.lower() in ["historial", "mis predicciones", "history"]:
            predictions = get_user_predictions(chat_id)
            from app.utils.prediction_ui import history_menu
            return history_menu(predictions), ["sports_prediction_tool"]
        
        # Caso principal: predecir partido
        result = predict_match(query, chat_id=chat_id)
        
        if result.get("error"):
            if result.get("suggestions"):
                from app.core.chat_state import set_prediction_session
                from app.utils.prediction_ui import team_suggestion_menu

                field = result.get("field", "team_a")
                payload = {
                    "step": "await_team_a" if field == "team_a" else "await_team_b",
                    f"{field}_suggestions": result.get("suggestions", []),
                }
                if result.get("team_a"):
                    payload["team_a"] = result["team_a"]
                set_prediction_session(chat_id, payload)
                return team_suggestion_menu(result.get("original_query", query), result.get("suggestions", []), field), ["sports_prediction_tool"]
            return {"type": "text", "text": f"❌ {result['error']}"}, ["sports_prediction_tool"]
        
        from app.utils.prediction_ui import prediction_result_menu
        return prediction_result_menu(result, chat_id), ["sports_prediction_tool"]

    if intent == "recipe":
        from app.tools.recipe import search_recipes, get_user_recipes, clear_user_recipes
        from app.utils.recipe_ui import recipe_history_menu, recipe_list_menu

        # ---------------- HISTORIAL ----------------
        if query.lower() in ["historial", "mis recetas", "history"]:
            recipes = get_user_recipes(chat_id)
            return recipe_history_menu(recipes), ["recipe_tool"]

        # ---------------- CLEAR ----------------
        if query.lower() in ["limpiar", "clear", "borrar"]:
            clear_user_recipes(chat_id)
            return {"type": "text", "text": "✅ Historial de recetas limpiado."}, ["recipe_tool"]

        # ---------------- BUSCAR RECETAS ----------------
        results = search_recipes(query)

        # ⚠️ IMPORTANTE: guardar en sesión
        from app.core.chat_state import set_recipe_session
        set_recipe_session(chat_id, {
            "step": "select_recipe",
            "query": query,
            "results": results["recipes"]
        })

        return recipe_list_menu(query, results["recipes"]), ["recipe_tool"]

    return agent(query)
