from app.tools.jellyfin import jellyfin
from app.tools.youtube import download_youtube_audio, download_youtube_video
import logging
from app.core.chat_state import (
    clear_prediction_session,
    get_prediction_session,
    set_prediction_session,
    get_recipe_session
)
from app.tools.sports_prediction import delete_prediction, find_next_match, get_user_predictions, predict_match
from app.utils.prediction_ui import history_menu, prediction_menu, prediction_result_menu

logger = logging.getLogger("bot")
EPISODES_PER_PAGE = 20
SEASONS_PER_PAGE = 20


def _season_label(season):
    name = season.get("Name") or "Temporada"
    index = season.get("IndexNumber")
    if index is None:
        return name
    return f"Temporada {index}"


def _episode_label(episode):
    season_number = episode.get("ParentIndexNumber")
    episode_number = episode.get("IndexNumber")
    name = episode.get("Name", "Episodio")

    prefix_parts = []
    if season_number is not None:
        prefix_parts.append(f"T{int(season_number):02d}")
    if episode_number is not None:
        prefix_parts.append(f"E{int(episode_number):02d}")

    prefix = "".join(prefix_parts)
    if prefix:
        return f"▶️ {prefix} - {name}"
    return f"▶️ {name}"

def handle_callback(callback):
    data = callback["data"]
    chat_id = callback["message"]["chat"]["id"]
    
    logger.info(f"🔄 Procesando callback data: {data}")

    # ---------------------------------------------------------
    # 1. ENTRADA A LA BIBLIOTECA CON PAGINACIÓN
    # Formato esperado: "open_library:movies:0" (categoría:offset)
    # ---------------------------------------------------------
    if data.startswith("open_library:"):
        parts = data.split(":")
        category = parts[1]
        # Si no viene offset, empezamos en 0
        offset = int(parts[2]) if len(parts) > 2 else 0
        limit = 20  # Cantidad de películas por página

        if category == "movies":
            all_items = jellyfin.get_all_movies()
            title = "🎬 **Películas Disponibles**"
            prefix = "play_movie"
        else:
            all_items = jellyfin.get_all_series()
            title = "📺 **Series Disponibles**"
            prefix = "open_series"

        if not all_items:
            return {"type": "text", "text": "No se encontraron elementos."}

        # Seleccionamos solo el trozo de la lista que toca mostrar
        items_to_show = all_items[offset : offset + limit]
        
        buttons = []
        for item in items_to_show:
            buttons.append([
                {
                    "text": item.get("Name", "Sin título"),
                    "callback_data": f"{prefix}:{item['Id']}"
                }
            ])

        # --- FILA DE NAVEGACIÓN ---
        nav_buttons = []
        # Botón Anterior
        if offset > 0:
            prev_offset = max(0, offset - limit)
            nav_buttons.append({"text": "⬅️ Anterior", "callback_data": f"open_library:{category}:{prev_offset}"})
        
        # Botón Siguiente
        if offset + limit < len(all_items):
            next_offset = offset + limit
            nav_buttons.append({"text": "Siguiente ➡️", "callback_data": f"open_library:{category}:{next_offset}"})

        if nav_buttons:
            buttons.append(nav_buttons)

        total = len(all_items)
        page_info = f"\n\nPágina { (offset // limit) + 1 } de { (total // limit) + 1 }"
        
        return {
            "type": "menu",
            "text": f"{title}{page_info}",
            "buttons": buttons
        }

    # ---------------------------------------------------------
    # 2. SELECCIÓN DE SERIE -> MOSTRAR TEMPORADAS / EPISODIOS
    # ---------------------------------------------------------
    if data.startswith("open_series:"):
        parts = data.split(":")
        series_id = parts[1]
        offset = int(parts[2]) if len(parts) > 2 else 0

        try:
            series_info = jellyfin.get_item_info(series_id)
            seasons = jellyfin.get_seasons(series_id)

            if seasons:
                seasons_to_show = seasons[offset : offset + SEASONS_PER_PAGE]
                buttons = []
                for season in seasons_to_show:
                    buttons.append([
                        {
                            "text": _season_label(season),
                            "callback_data": f"open_season:{season['Id']}"
                        }
                    ])

                nav_buttons = []
                if offset > 0:
                    prev_offset = max(0, offset - SEASONS_PER_PAGE)
                    nav_buttons.append({
                        "text": "⬅️ Anterior",
                        "callback_data": f"open_series:{series_id}:{prev_offset}"
                    })
                if offset + SEASONS_PER_PAGE < len(seasons):
                    next_offset = offset + SEASONS_PER_PAGE
                    nav_buttons.append({
                        "text": "Siguiente ➡️",
                        "callback_data": f"open_series:{series_id}:{next_offset}"
                    })
                if nav_buttons:
                    buttons.append(nav_buttons)

                return {
                    "type": "menu",
                    "text": (
                        f"📺 **{series_info.get('Name', 'Serie')}**\n\n"
                        f"Selecciona una temporada:\n\n"
                        f"Página {(offset // SEASONS_PER_PAGE) + 1} de {max(1, (len(seasons) + SEASONS_PER_PAGE - 1) // SEASONS_PER_PAGE)}"
                    ),
                    "buttons": buttons
                }

            episodes = jellyfin.get_series_episodes(series_id)
            if not episodes:
                return {"type": "text", "text": "No se encontraron episodios para esta serie."}
        except Exception as e:
            logger.error(f"Error filtrando episodios: {e}")
            return {"type": "text", "text": "Error al cargar episodios."}

        buttons = []
        episodes_to_show = episodes[offset : offset + EPISODES_PER_PAGE]
        for e in episodes_to_show:
            buttons.append([
                {
                    "text": _episode_label(e),
                    "callback_data": f"play_episode:{e['Id']}"
                }
            ])

        nav_buttons = []
        if offset > 0:
            prev_offset = max(0, offset - EPISODES_PER_PAGE)
            nav_buttons.append({
                "text": "⬅️ Anterior",
                "callback_data": f"open_series:{series_id}:{prev_offset}"
            })
        if offset + EPISODES_PER_PAGE < len(episodes):
            next_offset = offset + EPISODES_PER_PAGE
            nav_buttons.append({
                "text": "Siguiente ➡️",
                "callback_data": f"open_series:{series_id}:{next_offset}"
            })
        if nav_buttons:
            buttons.append(nav_buttons)

        return {
            "type": "menu",
            "text": (
                f"📺 **{series_info.get('Name', 'Serie')}**\n\n"
                f"Selecciona un episodio:\n\n"
                f"Página {(offset // EPISODES_PER_PAGE) + 1} de {max(1, (len(episodes) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)}"
            ),
            "buttons": buttons
        }

    if data.startswith("open_season:"):
        parts = data.split(":")
        season_id = parts[1]
        offset = int(parts[2]) if len(parts) > 2 else 0

        try:
            season_info = jellyfin.get_item_info(season_id)
            series_id = season_info.get("SeriesId") or season_info.get("ParentId")
            series_name = season_info.get("SeriesName") or "Serie"
            episodes = jellyfin.get_episodes_by_season(season_id)
            if not episodes:
                return {"type": "text", "text": "No se encontraron episodios para esa temporada."}
        except Exception as e:
            logger.error(f"Error cargando temporada: {e}")
            return {"type": "text", "text": "Error al cargar la temporada."}

        buttons = []
        episodes_to_show = episodes[offset : offset + EPISODES_PER_PAGE]
        for episode in episodes_to_show:
            buttons.append([
                {
                    "text": _episode_label(episode),
                    "callback_data": f"play_episode:{episode['Id']}"
                }
            ])

        nav_buttons = []
        if offset > 0:
            prev_offset = max(0, offset - EPISODES_PER_PAGE)
            nav_buttons.append({
                "text": "⬅️ Anterior",
                "callback_data": f"open_season:{season_id}:{prev_offset}"
            })
        if offset + EPISODES_PER_PAGE < len(episodes):
            next_offset = offset + EPISODES_PER_PAGE
            nav_buttons.append({
                "text": "Siguiente ➡️",
                "callback_data": f"open_season:{season_id}:{next_offset}"
            })
        if nav_buttons:
            buttons.append(nav_buttons)

        if series_id:
            buttons.append([
                {
                    "text": "⬅️ Volver a temporadas",
                    "callback_data": f"open_series:{series_id}"
                }
            ])

        return {
            "type": "menu",
            "text": (
                f"📺 **{series_name}**\n"
                f"🎞 {_season_label(season_info)}\n\n"
                f"Selecciona un episodio:\n\n"
                f"Página {(offset // EPISODES_PER_PAGE) + 1} de {max(1, (len(episodes) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)}"
            ),
            "buttons": buttons
        }

    # ---------------------------------------------------------
    # 3. REPRODUCIR (Película o Episodio)
    # ---------------------------------------------------------
    if data.startswith("play_movie:") or data.startswith("play_episode:"):
        item_id = data.split(":")[1]
        return jellyfin.run_by_id(item_id)

    # ---------------------------------------------------------
    # 4. YOUTUBE -> DESCARGAR Y ENVIAR A TELEGRAM
# ---------------------------------------------------------
    if data.startswith("youtube_play:"):
        video_id = data.split(":", 1)[1]
        return download_youtube_video(video_id)

    if data.startswith("music_play:"):
        video_id = data.split(":", 1)[1]
        return download_youtube_audio(video_id)

# Predicciones deportivas
    if data == "pred:match":
        session = get_prediction_session(chat_id) or {}
        session["step"] = "await_team_a"
        set_prediction_session(chat_id, session)
        
        return {
            "type": "text",
            "text": "📝 Escribe el nombre del equipo principal:"
        }

    if data == "pred:rival_auto":
        session = get_prediction_session(chat_id) or {}
        team_a = session.get("team_a", "Real Madrid")

        match = find_next_match(team_a)
        if match:
            team_b = match["opponent"]
            result = predict_match(team_a, team_b, chat_id=chat_id)
            clear_prediction_session(chat_id)
            return prediction_result_menu(result, chat_id)
        else:
            return {"type": "text", "text": "No se encontró próximo partido"}

    if data == "pred:rival_manual":
        session = get_prediction_session(chat_id) or {}
        session["step"] = "await_team_b"
        set_prediction_session(chat_id, session)
        
        return {
            "type": "text",
            "text": "✏️ Escribe el nombre del rival:"
        }

    if data.startswith("pred:suggest:"):
        parts = data.split(":")
        field = parts[2] if len(parts) > 2 else ""
        try:
            index = int(parts[3])
        except (IndexError, ValueError):
            index = -1

        session = get_prediction_session(chat_id) or {}
        suggestions = session.get(f"{field}_suggestions") or []
        if index < 0 or index >= len(suggestions):
            return {"type": "text", "text": "No pude recuperar esa sugerencia. Escríbelo de nuevo."}

        selected_team = suggestions[index]
        if field == "team_a":
            session["team_a"] = selected_team
            session["step"] = "await_team_b"
            session.pop("team_a_suggestions", None)
            set_prediction_session(chat_id, session)
            return {
                "type": "menu",
                "text": f"⚽ Equipo 1: {selected_team}\n\n¿Quién es el rival?",
                "buttons": [
                    [{"text": "📅 Próximo Rival", "callback_data": "pred:rival_auto"}],
                    [{"text": "✏️ Escribir otro", "callback_data": "pred:rival_manual"}],
                ],
            }

        if field == "team_b":
            team_a = session.get("team_a")
            if not team_a:
                return {"type": "text", "text": "No encontré el equipo principal. Empezamos de nuevo con /prediccion."}
            session["team_b"] = selected_team
            session.pop("team_b_suggestions", None)
            set_prediction_session(chat_id, session)
            result = predict_match(team_a, selected_team, chat_id=chat_id)
            clear_prediction_session(chat_id)
            return prediction_result_menu(result, chat_id)

    if data.startswith("pred:retry:"):
        field = data.split(":")[2] if len(data.split(":")) > 2 else ""
        session = get_prediction_session(chat_id) or {}
        if field == "team_a":
            session["step"] = "await_team_a"
            session.pop("team_a_suggestions", None)
            set_prediction_session(chat_id, session)
            return {"type": "text", "text": "📝 Escribe el nombre del equipo principal:"}
        if field == "team_b":
            session["step"] = "await_team_b"
            session.pop("team_b_suggestions", None)
            set_prediction_session(chat_id, session)
            return {"type": "text", "text": "✏️ Escribe el nombre del rival:"}

    if data == "pred:history" or data.startswith("pred:history:"):
        page = 0
        if data.startswith("pred:history:"):
            try:
                page = int(data.split(":")[2])
            except (IndexError, ValueError):
                page = 0
        predictions = get_user_predictions(chat_id)
        return history_menu(predictions, page=page)

    if data.startswith("pred:delete:"):
        parts = data.split(":")
        prediction_id = parts[2] if len(parts) > 2 else ""
        page = 0
        if len(parts) > 3:
            try:
                page = int(parts[3])
            except ValueError:
                page = 0
        delete_prediction(chat_id, prediction_id)
        predictions = get_user_predictions(chat_id)
        max_page = max(0, (len(predictions) - 1) // 5) if predictions else 0
        return history_menu(predictions, page=min(page, max_page))

    if data == "pred:new":
        clear_prediction_session(chat_id)
        return prediction_menu()
    
    if data == "recipe:search":
        from app.core.chat_state import set_recipe_session, clear_recipe_session
        
        clear_recipe_session(chat_id)
        
        callback_message_id = callback["message"]["message_id"]
        
        set_recipe_session(chat_id, {
            "step": "await_query",
            "callback_message_id": callback_message_id
        })
        
        logger.info(f"DEBUG CALLBACK: recipe:search for chat_id={chat_id}, step=await_query")
        
        return {
            "type": "menu",
            "text": "🔍 ¿Qué receta quieres buscar?",
            "buttons": []
        }

    if data.startswith("recipe:select:"):
        index = int(data.split(":")[2])

        from app.core.chat_state import get_recipe_session, set_recipe_session
        from app.tools.recipe import get_recipe_details
        from app.utils.recipe_ui import recipe_detail_menu

        session = get_recipe_session(chat_id)
        recipes = session.get("results", [])

        if not recipes or index >= len(recipes):
            return {"type": "text", "text": "❌ Receta no válida"}

        recipe = recipes[index]

        details = get_recipe_details(recipe["url"])

        # 🔥 CLAVE: guardar estado de receta seleccionada y mostrar inmediatamente
        set_recipe_session(chat_id, {
            **session,
            "step": "viewing_recipe",
            "selected_recipe": recipe
        })

        return recipe_detail_menu(details)

    if data == "recipe:history":
        from app.tools.recipe import get_user_recipes, get_recipe_details
        from app.utils.recipe_ui import recipe_detail_menu
        
        recipes = get_user_recipes(chat_id)
        
        if not recipes:
            return {"type": "text", "text": "📭 No tienes recetas guardadas aún."}
        
        buttons = []
        for r in reversed(recipes):
            recipe_name = r.get('recipe_name', 'Receta')
            created_at = r.get('created_at', '')[:10] if r.get('created_at') else ''
            
            buttons.append([
                {
                    "text": f"🍽️ {recipe_name}",
                    "callback_data": f"recipe:history_select:{r['id']}"
                }
            ])
        
        buttons.append([{"text": "↩️ Volver", "callback_data": "recipe:back"}])
        
        return {
            "type": "menu",
            "text": "📚 HISTORIAL DE RECETAS\nSelecciona una receta para ver detalles:",
            "buttons": buttons
        }

    if data.startswith("recipe:history_select:"):
        from app.tools.recipe import get_user_recipes, get_recipe_details
        from app.utils.recipe_ui import recipe_detail_menu
        
        recipe_id = data.split(":")[2]
        
        recipes = get_user_recipes(chat_id)
        recipe_data = next((r for r in recipes if r.get('id') == recipe_id), None)
        
        logger.info(f"DEBUG: Selecting recipe {recipe_id}, data={recipe_data}")
        
        if not recipe_data:
            return {"type": "text", "text": "❌ Receta no encontrada en el historial"}
        
        url = recipe_data.get("url")
        if not url:
            return {"type": "text", "text": "❌ URL de receta perdida. Busca la receta de nuevo."}
        
        logger.info(f"DEBUG: Fetching details for URL: {url}")
        details = get_recipe_details(url)
        logger.info(f"DEBUG: Details fetched - Title: {details.get('title')}, Ingredients count: {len(details.get('ingredients', []))}, Instructions count: {len(details.get('instructions', []))}")

        return recipe_detail_menu(details)

    if data == "recipe:back":
        from app.core.chat_state import clear_recipe_session
        from app.utils.recipe_ui import recipe_menu
        
        clear_recipe_session(chat_id)
        return recipe_menu()

    if data == "recipe:clear":
        from app.tools.recipe import clear_user_recipes
        
        clear_user_recipes(chat_id)
        return {"type": "text", "text": "✅ Historial de recetas limpiado."}

    return None
