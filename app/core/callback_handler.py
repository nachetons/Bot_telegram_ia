from app.tools.jellyfin import jellyfin
from app.tools.youtube import download_youtube_audio, download_youtube_video
from app.tools.manga import (
    manga_menu, manga_search_menu, manga_auto_search, manga_manhwaweb_menu, 
    manga_manhwaweb_catalog_menu, manga_manhwaweb_top10_menu, manga_manhwaweb_new_menu, 
    manga_manhwaweb_list, manga_handle_top10, manga_handle_new,
    mangadex_menu, mangadex_search_menu, mangadex_read_details, mangadex_view_chapter, mangadex_read_chapter, mangadex_top_menu,
    mangadex_auto_search, vermanhwa_menu, vermanhwa_search_menu, vermanhwa_read_details, vermanhwa_view_chapter, vermanhwa_read_chapter,
    _results_menu, _compact_results_menu, _resolve_callback, manga_add_favorite, _vermanhwa, _register_menu_callback,
)
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


def _is_manga_allowed(chat_id):
    """Verifica si el usuario tiene permiso para usar manga."""
    from app.config import TELEGRAM_CHAT_ID
    return chat_id == TELEGRAM_CHAT_ID


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
        return f"→ï⚕ {prefix} - {name}"
    return f"→ï⚕ {name}"

def handle_callback(callback):
    data = callback["data"]
    chat_id = callback["message"]["chat"]["id"]

    logger.info(f"📩 Procesando callback data: {data}")

    # ---------------------------------------------------------
    # 1. ENTRADA A LA BIBLIOTECA CON PAGINACIÃ“N
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
            title = "📚 **Películas Disponibles**"
            prefix = "play_movie"
        else:
            all_items = jellyfin.get_all_series()
            title = "ð⏭ **Series Disponibles**"
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

        # --- FILA DE NAVEGACIÃ“N ---
        nav_buttons = []
        # Botón Anterior
        if offset > 0:
            prev_offset = max(0, offset - limit)
            nav_buttons.append({"text": "⏰⚕ Anterior", "callback_data": f"open_library:{category}:{prev_offset}"})

        # Botón Siguiente
        if offset + limit < len(all_items):
            next_offset = offset + limit
            nav_buttons.append({"text": "Siguiente ⏭⚕", "callback_data": f"open_library:{category}:{next_offset}"})

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
    # 2. SELECCIÃ“N DE SERIE -> MOSTRAR TEMPORADAS / EPISODIOS
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
                        "text": "⏰⚕ Anterior",
                        "callback_data": f"open_series:{series_id}:{prev_offset}"
                    })
                if offset + SEASONS_PER_PAGE < len(seasons):
                    next_offset = offset + SEASONS_PER_PAGE
                    nav_buttons.append({
                        "text": "Siguiente ⏭⚕",
                        "callback_data": f"open_series:{series_id}:{next_offset}"
                    })
                if nav_buttons:
                    buttons.append(nav_buttons)

                return {
                    "type": "menu",
                    "text": (
                        f"ð⏭ **{series_info.get('Name', 'Serie')}**\n\n"
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
                "text": "⏰⚕ Anterior",
                "callback_data": f"open_series:{series_id}:{prev_offset}"
            })
        if offset + EPISODES_PER_PAGE < len(episodes):
            next_offset = offset + EPISODES_PER_PAGE
            nav_buttons.append({
                "text": "Siguiente ⏭⚕",
                "callback_data": f"open_series:{series_id}:{next_offset}"
            })
        if nav_buttons:
            buttons.append(nav_buttons)

        return {
            "type": "menu",
            "text": (
                f"ð⏭ **{series_info.get('Name', 'Serie')}**\n\n"
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
                "text": "⏰⚕ Anterior",
                "callback_data": f"open_season:{season_id}:{prev_offset}"
            })
        if offset + EPISODES_PER_PAGE < len(episodes):
            next_offset = offset + EPISODES_PER_PAGE
            nav_buttons.append({
                "text": "Siguiente ⏭⚕",
                "callback_data": f"open_season:{season_id}:{next_offset}"
            })
        if nav_buttons:
            buttons.append(nav_buttons)

        if series_id:
            buttons.append([
                {
                    "text": "⏰⚕ Volver a temporadas",
                    "callback_data": f"open_series:{series_id}"
                }
            ])

        return {
            "type": "menu",
            "text": (
                f"ð⏭ **{series_name}**\n"
                f"📺 {_season_label(season_info)}\n\n"
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
            "text": "📌 Escribe el nombre del equipo principal:"
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
            "text": "❌ï⚕ Escribe el nombre del rival:"
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
                    [{"text": "📌 Próximo Rival", "callback_data": "pred:rival_auto"}],
                    [{"text": "❌ï⚕ Escribir otro", "callback_data": "pred:rival_manual"}],
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
            return {"type": "text", "text": "📌 Escribe el nombre del equipo principal:"}
        if field == "team_b":
            session["step"] = "await_team_b"
            session.pop("team_b_suggestions", None)
            set_prediction_session(chat_id, session)
            return {"type": "text", "text": "❌ï⚕ Escribe el nombre del rival:"}

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
            "text": "ð🔍 ¿Qué receta quieres buscar?",
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

        # 🔑 CLAVE: guardar estado de receta seleccionada y mostrar inmediatamente
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
            return {"type": "text", "text": "📌 No tienes recetas guardadas aún."}

        buttons = []
        for r in reversed(recipes):
            recipe_name = r.get('recipe_name', 'Receta')
            created_at = r.get('created_at', '')[:10] if r.get('created_at') else ''

            buttons.append([
                {
                    "text": f"📍ï⚕ {recipe_name}",
                    "callback_data": f"recipe:history_select:{r['id']}"
                }
            ])

        buttons.append([{"text": "⏰ï⚕ Volver", "callback_data": "recipe:back"}])

        return {
            "type": "menu",
            "text": "📌 HISTORIAL DE RECETAS\nSelecciona una receta para ver detalles:",
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

    # ========== MANGA MESSAGE CLEANUP HELPER ==========
    def _delete_old_manga_menu(cid):
        """Elimina TODOS los mensajes anteriores de menu manga antes de mostrar uno nuevo."""
        from app.core.state_manager import state_manager
        
        # Eliminar todos los mensajes manga anteriores (no solo el ultimo)
        state_manager.delete_all_manga_menus(cid)

    # ========== MANGA MESSAGE TRACKING HELPER ==========
    def _track_manga_message(cid, msg_id):
        """Guarda el ID del nuevo mensaje de menu manga."""
        from app.core.state_manager import state_manager
        state_manager.set_manga_menu_message(cid, msg_id)

    # ========== MANGA HANDLERS ==========
    # Restricción: solo TELEGRAM_CHAT_ID puede usar manga
    if not _is_manga_allowed(chat_id):
        return None

    if data == "manga:search":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "manga")

        logger.info(f"DEBUG CALLBACK: manga:search for chat_id={chat_id}, step=await_query")

        return manga_search_menu()

    if data == "manga:auto":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "manga_auto")

        logger.info(f"DEBUG CALLBACK: manga:auto for chat_id={chat_id}, step=await_query")

        return {
            "type": "menu",
            "text": "🔍 BUSQUEDA GLOBAL\n\nEscribe el nombre del manga que buscas (se buscara en todos los servicios).",
            "buttons": [[{"text": "Cancelar", "callback_data": "manga:back"}]]
        }

    if data == "manga:manhwaweb":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "manga_manhwa")

        logger.info(f"DEBUG CALLBACK: manga:manhwa for chat_id={chat_id}, step=await_query")

        result = manga_manhwaweb_menu()
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    # MANGA - MANHWA WEB (nuevo con back_refs y filtros)
    
    if data == "manga:mw_catalog":
        from app.tools.manga import manga_manhwaweb_catalog_menu
        
        result = manga_manhwaweb_catalog_menu()
        result["_edit"] = True
        return result
    
    # Filtros del catalogo (tipo, estado, demografia, erotico, genero)
    if data.startswith("manga:mw_filter:"):
        # Formato: manga:mw_filter:{filter_type}:{filter_value}:{back_ref}
        parts = data.split(":")
        filter_key = parts[2] if len(parts) > 2 else ""
        filter_value = parts[3] if len(parts) > 3 else ""
        back_ref = parts[4] if len(parts) > 4 else ""
        
        from app.tools.manga import manga_manhwaweb_catalog_menu, manga_manhwaweb_list
        
        # Construir filtros segun el tipo seleccionado
        filters = {}
        if filter_key == "tipo":
            filters["tipo"] = filter_value
            result = manga_manhwaweb_list(filter_value, order_item="alfabetico", filters=filters)
        elif filter_key == "estado":
            # Para estado, necesitamos obtener el tipo actual desde el back_ref o usar manhwa por defecto
            # Por simplicidad, mostramos menu de tipos primero si no hay filtro de tipo
            result = manga_manhwaweb_list("manhwa", order_item="alfabetico", filters={"estado": filter_value})
        elif filter_key == "demografia":
            result = manga_manhwaweb_list("manhwa", order_item="alfabetico", filters={"demografia": filter_value})
        elif filter_key == "erotico":
            result = manga_manhwaweb_list("manhwa", order_item="alfabetico", filters={"erotico": filter_value})
        elif filter_key == "genero":
            # Genero es un ID numerico (2=Romance, 1=Drama, etc)
            try:
                genre_id = int(filter_value)
                result = manga_manhwaweb_list("manhwa", order_item="alfabetico", filters={"genero": genre_id})
            except ValueError:
                result = {"type": "text", "text": "Genero invalido."}
        else:
            result = manga_manhwaweb_catalog_menu()
        
        if isinstance(result, dict):
            result["_edit"] = True
        return result
    
    # Submenus de filtros adicionales (estado, demografia, erotico, generos)
    if data == "manga:mw_states":
        from app.tools.manga import manga_manhwaweb_state_menu
        
        result = manga_manhwaweb_state_menu()
        result["_edit"] = True
        return result
    
    if data == "manga:mw_demo":
        from app.tools.manga import manga_manhwaweb_demo_menu
        
        result = manga_manhwaweb_demo_menu()
        result["_edit"] = True
        return result
    
    if data == "manga:mw_erotic":
        from app.tools.manga import manga_manhwaweb_erotic_menu
        
        result = manga_manhwaweb_erotic_menu()
        result["_edit"] = True
        return result
    
    if data == "manga:mw_genres":
        from app.tools.manga import manga_manhwaweb_genre_menu
        
        result = manga_manhwaweb_genre_menu()
        result["_edit"] = True
        return result
    
    # Top 10 y Novedades
    if data == "manga:mw_top10":
        from app.tools.manga import manga_manhwaweb_top10_menu
        
        result = manga_manhwaweb_top10_menu()
        result["_edit"] = True
        return result
    
    if data.startswith("manga:mw_top:"):
        # Formato: manga:mw_top:{sort_type}:{back_ref}
        parts = data.split(":")
        sort_type = parts[2] if len(parts) > 2 else "popular"
        
        from app.tools.manga import manga_handle_top10
        
        result = manga_handle_top10(sort_type)
        result["_edit"] = True
        return result
    
    if data == "manga:mw_new":
        from app.tools.manga import manga_manhwaweb_new_menu
        
        result = manga_manhwaweb_new_menu()
        result["_edit"] = True
        return result
    
    if data.startswith("manga:mw_new:"):
        # Formato: manga:mw_new:{timeframe}:{back_ref}
        parts = data.split(":")
        timeframe = parts[2] if len(parts) > 2 else "week"
        
        from app.tools.manga import manga_handle_new
        
        result = manga_handle_new(timeframe)
        result["_edit"] = True
        return result
    
    # MANGA - Manhwaweb (legacy, redirige a nuevos callbacks)
    
    if data == "manga:catalog":
        from app.tools.manga import manga_manhwaweb_catalog_menu
        
        result = manga_manhwaweb_catalog_menu()
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data == "manga:search_query":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "manga_search")

        logger.info(f"DEBUG CALLBACK: manga:search_query for chat_id={chat_id}, step=await_query")

        return {
            "type": "menu",
            "text": "🔍 BUSCAR MANGA\n\nEscribe el nombre del manga que buscas:",
            "buttons": []
        }

    if data == "manga:top10":
        # Legacy redirect to new callback format
        from app.tools.manga import manga_manhwaweb_top10_menu
        
        result = manga_manhwaweb_top10_menu()
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data == "manga:tp":
        from app.tools.manga import manga_handle_top10
        
        result = manga_handle_top10("popular")
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data == "manga:nr":
        from app.tools.manga import manga_handle_top10
        
        result = manga_handle_top10("rated")
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data in ("manga:nd", "manga:nw"):
        from app.tools.manga import manga_handle_new
        
        result = manga_handle_new("week")
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data == "manga:nm":
        from app.tools.manga import manga_handle_new
        
        result = manga_handle_new("month")
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data == "manga:top_rated":
        from app.tools.manga import manga_handle_top10
        
        result = manga_handle_top10("rated")
        result["_edit"] = True
        return result

    if data == "manga:top_newest":
        from app.tools.manga import manga_handle_top10
        
        result = manga_handle_top10("newest")
        result["_edit"] = True
        return result

    if data in ("manga:new", "manga:new_week"):
        from app.tools.manga import manga_manhwaweb_new_menu
        
        result = manga_manhwaweb_new_menu()
        result["_edit"] = True  # Forzar edicion en lugar de nuevo mensaje
        return result

    if data == "manga:new_month":
        from app.tools.manga import manga_handle_new
        
        result = manga_handle_new("month")
        result["_edit"] = True
        return result

    if data == "manga:tp":
        from app.tools.manga import manga_handle_top10

        result = manga_handle_top10("popular")
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    if data == "manga:nr":
        from app.tools.manga import manga_handle_top10

        result = manga_handle_top10("rated")
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    if data == "manga:nd":
        from app.tools.manga import manga_handle_top10

        result = manga_handle_top10("newest")
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    if data == "manga:nw":
        from app.tools.manga import manga_handle_new

        result = manga_handle_new("week")
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    if data == "manga:nm":
        from app.tools.manga import manga_handle_new

        result = manga_handle_new("month")
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    if data == "manga:top_rated":
        from app.tools.manga import manga_handle_top10

        result = manga_handle_top10("rated")
        result["_edit"] = True
        return result

    if data == "manga:top_newest":
        from app.tools.manga import manga_handle_top10

        result = manga_handle_top10("newest")
        result["_edit"] = True
        return result

    if data == "manga:new":
        from app.tools.manga import manga_manhwaweb_new_menu

        result = manga_manhwaweb_new_menu()
        result["_edit"] = True  # Forzar edición en lugar de nuevo mensaje
        return result

    if data == "manga:new_week":
        from app.tools.manga import manga_handle_new

        result = manga_handle_new("week")
        result["_edit"] = True
        return result

    if data == "manga:new_month":
        from app.tools.manga import manga_handle_new

        result = manga_handle_new("month")
        result["_edit"] = True
        return result

    if data == "manga:favorites":
        from app.tools.manga import manga_get_favorites

        result = manga_get_favorites(chat_id)
        result["_edit"] = True
        return result

    # MANGADEX CALLBACKS
    if data == "manga:mangadex":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "mangadex")

        logger.info(f"DEBUG CALLBACK: manga:mangadex for chat_id={chat_id}")

        result = mangadex_menu()
        result["_edit"] = True
        return result

    if data == "manga:mangadex_search":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "mangadex_search")

        logger.info(f"DEBUG CALLBACK: manga:mangadex_search for chat_id={chat_id}")

        result = mangadex_search_menu()
        result["_edit"] = True
        return result

    if data == "manga:mangadex_top":
        result = mangadex_top_menu()
        result["_edit"] = True
        return result

    if data == "manga:mangadex_top_popular":
        from app.tools.manga import mangadex_top, _compact_results_menu
        
        results = mangadex_top(limit=20).get("results", [])[:15]
        back_ref = _register_menu_callback(mangadex_top_menu())
        result = _compact_results_menu(
            "🔥 TOP 10 - MANGADEX\nPor popularidad",
            results,
            "No encontre mangas populares.",
            back_ref,
        )
        result["_edit"] = True
        return result

    if data == "manga:mangadex_recent":
        from app.tools.manga import mangadex_recent, _compact_results_menu
        
        results = mangadex_recent(limit=20).get("results", [])[:15]
        back_ref = _register_menu_callback(mangadex_menu())
        result = _compact_results_menu(
            "⭐ RECIENTES - MANGADEX\nUltimos agregados",
            results,
            "No encontre mangas recientes.",
            back_ref,
        )
        result["_edit"] = True
        return result

    # VERMANHWA CALLBACKS
    if data == "manga:vermanhwa_latest":
        from app.tools.manga import vermanhwa_handle_latest
        
        result = vermanhwa_handle_latest()
        result["_edit"] = True
        return result

    if data == "manga:vermanhwa_genres":
        from app.tools.manga import vermanhwa_genres_menu
        
        result = vermanhwa_genres_menu()
        result["_edit"] = True
        return result

    if data.startswith("manga:vermanhwa_genre:"):
        from app.tools.manga import vermanhwa_handle_genre
        
        genre_slug = data.split(":")[-1]
        result = vermanhwa_handle_genre(genre_slug)
        result["_edit"] = True
        return result

    if data == "manga:vermanhwa_completed":
        from app.tools.manga import vermanhwa_handle_completed
        
        result = vermanhwa_handle_completed()
        result["_edit"] = True
        return result

    if data.startswith("mangadex:chapter:"):
        from app.tools.manga import mangadex_read_chapter, _resolve_callback
        
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        
        chapter_url = _resolve_callback(token) or token
        return mangadex_read_chapter(chapter_url, chat_id)

    if data.startswith("mangadex:view:"):
        from app.tools.manga import mangadex_view_chapter, _resolve_callback
        
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        page = int(parts[-1]) if len(parts) > 3 and parts[-1].isdigit() else 0
        
        chapter_url = _resolve_callback(token) or token
        return mangadex_view_chapter(chat_id, chapter_url, page)

    if data.startswith("mangadex:manga:"):
        from app.tools.manga import mangadex_read_details, _resolve_callback
        
        parts = data.split(":")
        manga_ref = ":".join(parts[2:]) if len(parts) > 2 else ""
        
        result = mangadex_read_details(manga_ref, chat_id)
        result["_edit"] = True
        return result

    if data.startswith("read:"):
        from app.tools.manga import manga_read_details, mangadex_read_details, vermanhwa_read_details, _resolve_callback
        
        # El callback_data es: read:{token}
        token = data.split(":", 1)[1] if ":" in data else ""
        
        # Resolver el token a la URL real
        resolved_raw = _resolve_callback(token)
        resolved_url = resolved_raw if isinstance(resolved_raw, str) else token
        
        # Determinar si es MangaDex, VerManhwa o Manhwaweb
        is_mangadex = False
        is_vermanhwa = False
        if isinstance(resolved_url, str):
            if resolved_url.startswith("mangadex:manga:"):
                is_mangadex = True
            elif ":" in resolved_url and "mangadex" in resolved_url.split(":")[0]:
                is_mangadex = True
            elif resolved_url.startswith("http") and "vermanhwa" in resolved_url:
                is_vermanhwa = True
        
        if is_mangadex:
            result = mangadex_read_details(resolved_url, chat_id)
        elif is_vermanhwa:
            result = vermanhwa_read_details(resolved_url, chat_id)
        else:
            result = manga_read_details(resolved_url, chat_id)
        
        result["_edit"] = True
        return result

    if data == "manga:vermanhwa":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "manga_vermanhwa")

        logger.info(f"DEBUG CALLBACK: manga:vermanhwa for chat_id={chat_id}")

        result = vermanhwa_menu()
        result["_edit"] = True
        return result

    if data == "manga:vermanhwa_search":
        from app.core.chat_state import set_pending_followup

        callback_message_id = callback["message"]["message_id"]

        set_pending_followup(chat_id, "manga_vermanhwa_search")

        logger.info(f"DEBUG CALLBACK: manga:vermanhwa_search for chat_id={chat_id}")

        result = vermanhwa_search_menu()
        result["_edit"] = True
        return result

    if data.startswith("vermanhwa:chapter:"):
        from app.tools.manga import vermanhwa_read_chapter, _resolve_callback
        
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        
        chapter_url = _resolve_callback(token) or token
        return vermanhwa_read_chapter(chapter_url, chat_id)

    if data.startswith("vermanhwa:view:"):
        from app.tools.manga import vermanhwa_view_chapter, _resolve_callback
        
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        page = int(parts[-1]) if len(parts) > 3 and parts[-1].isdigit() else 0
        
        chapter_url = _resolve_callback(token) or token
        return vermanhwa_view_chapter(chat_id, chapter_url, page)


    if data.startswith("manga:chapter:"):
        from app.tools.manga import manga_read_chapter, mangadex_read_chapter, vermanhwa_read_chapter, _resolve_callback
        
        # Formato: manga:chapter:{token}:{detail_ref}
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        back_ref = parts[3] if len(parts) > 3 else ""
        
        chapter_url = _resolve_callback(token) or token
        
        is_mangadex = False
        is_vermanhwa = False
        if isinstance(chapter_url, str):
            if chapter_url.startswith("mangadex:chapter:"):
                is_mangadex = True
            elif ":" in chapter_url and "mangadex" in chapter_url.split(":")[0]:
                is_mangadex = True
            elif chapter_url.startswith("http") and "vermanhwa" in chapter_url:
                is_vermanhwa = True
        
        if is_mangadex:
            chapter_ref = f"{chapter_url}:{back_ref}" if back_ref else chapter_url
            return mangadex_read_chapter(chapter_ref, chat_id)
        elif is_vermanhwa:
            return vermanhwa_read_chapter(chapter_url, chat_id)
        return manga_read_chapter(chapter_url, chat_id)

    if data.startswith("manga:fav:"):
        from app.tools.manga import manga_add_favorite, _resolve_callback
        
        # El callback_data es: manga:fav:{token}
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        
        manga_ref = _resolve_callback(token) or token
        return manga_add_favorite(chat_id, manga_ref)

    if data.startswith("manga:unfav:"):
        from app.tools.manga import manga_remove_favorite, _resolve_callback
        
        # El callback_data es: manga:unfav:{token}
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        
        manga_ref = _resolve_callback(token) or token
        return manga_remove_favorite(chat_id, manga_ref)

    if data.startswith("manga:read:"):
        from app.tools.manga import manga_read_details, mangadex_read_details, vermanhwa_read_details, _resolve_callback
        
        # El callback_data es: manga:read:{token}:{back_ref}
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        back_ref = parts[3] if len(parts) > 3 else ""
        
        resolved_url = _resolve_callback(token) or token
        
        is_mangadex = False
        is_vermanhwa = False
        if isinstance(resolved_url, str):
            if resolved_url.startswith("mangadex:manga:"):
                is_mangadex = True
            elif ":" in resolved_url and "mangadex" in resolved_url.split(":")[0]:
                is_mangadex = True
            elif resolved_url.startswith("http") and "vermanhwa" in resolved_url:
                is_vermanhwa = True
        
        if is_mangadex:
            manga_ref = f"{resolved_url}:{back_ref}" if back_ref else resolved_url
            result = mangadex_read_details(manga_ref, chat_id)
        elif is_vermanhwa:
            result = vermanhwa_read_details(resolved_url, chat_id)
        else:
            result = manga_read_details(resolved_url, chat_id)
        
        result["_edit"] = True
        return result

    # Visualizacion de capitulo
    if data.startswith("view_chap:"):
        from app.tools.manga import manga_view_chapter, _resolve_callback
        
        # El callback_data es: view_chap:{token}
        token = data.split(":", 1)[1] if ":" in data else ""
        
        chapter_url = _resolve_callback(token) or token
        result = manga_view_chapter(chat_id, chapter_url)
        result["_edit"] = True
        return result

    if data.startswith("view:"):
        from app.tools.manga import manga_view_chapter, vermanhwa_view_chapter, _resolve_callback
        
        # partes: "view", "token", "page"
        parts = data.split(":")
        token = parts[2] if len(parts) > 2 else ""
        page = int(parts[-1]) if len(parts) > 3 and parts[-1].isdigit() else 0
        
        chapter_url = _resolve_callback(token) or token
        
        is_vermanhwa = False
        if isinstance(chapter_url, str) and chapter_url.startswith("http") and "vermanhwa" in chapter_url:
            is_vermanhwa = True
        
        if is_vermanhwa:
            result = vermanhwa_view_chapter(chat_id, chapter_url, page)
        else:
            result = manga_view_chapter(chat_id, chapter_url, page)
        result["_edit"] = True
        return result

    # Descarga de capitulo (ZIP) - formato: manga:download_chap:{token} o download_chap:{token}
    if data.startswith("manga:download_chap:") or data.startswith("download_chap:"):
        from app.tools.manga import manga_download_chapter, mangadex_read_chapter, vermanhwa_read_chapter, _resolve_callback
        
        prefix = "manga:" if data.startswith("manga:") else ""
        token = data[len(prefix + "download_chap:"):]
        
        resolved_url = _resolve_callback(token) or token
        
        is_mangadex = False
        is_vermanhwa = False
        if isinstance(resolved_url, str):
            if resolved_url.startswith("mangadex:chapter:"):
                is_mangadex = True
            elif ":" in resolved_url and "mangadex" in resolved_url.split(":")[0]:
                is_mangadex = True
            elif resolved_url.startswith("http") and "vermanhwa" in resolved_url:
                is_vermanhwa = True
        
        if is_mangadex:
            return mangadex_read_chapter(resolved_url, chat_id)
        elif is_vermanhwa:
            return vermanhwa_read_chapter(resolved_url, chat_id)
        return manga_download_chapter(chat_id, resolved_url)

    # Exportar capitulo como PDF - formato: pdf_chap:{token}
    if data.startswith("pdf_chap:"):
        from app.tools.manga import manga_export_chapter_pdf, mangadex_read_chapter, vermanhwa_read_chapter, _resolve_callback
        
        token = data[len("pdf_chap:"):]
        
        resolved_url = _resolve_callback(token) or token
        
        is_mangadex = False
        is_vermanhwa = False
        if isinstance(resolved_url, str):
            if resolved_url.startswith("mangadex:chapter:"):
                is_mangadex = True
            elif ":" in resolved_url and "mangadex" in resolved_url.split(":")[0]:
                is_mangadex = True
            elif resolved_url.startswith("http") and "vermanhwa" in resolved_url:
                is_vermanhwa = True
        
        if is_mangadex:
            return mangadex_read_chapter(resolved_url, chat_id)
        elif is_vermanhwa:
            return vermanhwa_read_chapter(resolved_url, chat_id)
        return manga_export_chapter_pdf(chat_id, resolved_url)

    # Visualizacion manga completo
    if data.startswith("view_full:"):
        from app.tools.manga import manga_view_full, _resolve_callback
        
        # El callback_data es: view_full:{token}
        token = data.split(":", 1)[1] if ":" in data else ""
        
        manga_url = _resolve_callback(token) or token
        return manga_view_full(chat_id, manga_url)

    # Descarga manga completo (ZIP)
    if data.startswith("download_full:"):
        from app.tools.manga import manga_download_full, _resolve_callback
        
        token = data.split(":", 1)[1] if ":" in data else ""
        
        manga_url = _resolve_callback(token) or token
        return manga_download_full(chat_id, manga_url)

    # Descarga manga completo como PDF
    if data.startswith("pdf_full:"):
        from app.tools.manga import manga_export_full_pdf, _resolve_callback
        
        token = data.split(":", 1)[1] if ":" in data else ""
        
        manga_url = _resolve_callback(token) or token
        return manga_export_full_pdf(chat_id, manga_url)



    # Paginacion de resultados
    if data.startswith("manga:page:"):
        from app.tools.manga import (
            manga_get_favorites,
            manga_get_history,
            manga_handle_top10,
            manga_handle_new,
            _resolve_callback,
            manga_resolve_menu,
        )
        
        # Formato: manga:page:{back_ref}:{page}
        parts = data.split(":")
        back_ref = parts[2] if len(parts) > 2 else ""
        try:
            page = int(parts[-1])
        except (IndexError, ValueError):
            page = 0
        
        # Resolver el menu guardado
        menu_data = manga_resolve_menu(back_ref)
        
        if not menu_data or menu_data.get("type") != "menu":
            return {"type": "text", "text": "No se pudo cargar la pagina. Intenta de nuevo."}
        
        results = menu_data.get("results", [])
        title = menu_data.get("text", "").split("\n")[0] if menu_data.get("text") else "Resultados"
        
        result = _results_menu(title, results, "Sin resultados.", menu_data.get("back_ref", ""), page=page)
        result["_edit"] = True
        return result

    # Ver mas capitulos (paginacion de lista de caps)
    if data.startswith("manga:more_chaps:"):
        from app.tools.manga import manga_read_details, mangadex_read_details, _resolve_callback
        
        # Formato: manga:more_chaps:{manga_id}:{detail_ref}
        parts = data.split(":")
        manga_id = parts[2] if len(parts) > 2 else ""
        detail_ref = parts[3] if len(parts) > 3 else ""
        
        resolved_url = _resolve_callback(manga_id, "manga") or manga_id
        
        is_mangadex = False
        if isinstance(resolved_url, str):
            if resolved_url.startswith("mangadex:manga:"):
                is_mangadex = True
            elif ":" in resolved_url and "mangadex" in resolved_url.split(":")[0]:
                is_mangadex = True
        
        if is_mangadex:
            result = mangadex_read_details(resolved_url, chat_id)
        else:
            result = manga_read_details(f"{manga_id}:{detail_ref}")
        
        result["_edit"] = True
        return result

    # Ver mas capitulos - VerManhwa
    if data.startswith("vermanhwa:more_chaps:"):
        from app.tools.manga import vermanhwa_read_details, _resolve_callback
        
        # Formato: vermanhwa:more_chaps:{manga_id}:{detail_ref}
        parts = data.split(":")
        manga_id = parts[2] if len(parts) > 2 else ""
        detail_ref = parts[3] if len(parts) > 3 else ""
        
        resolved_url = _resolve_callback(manga_id, "manga") or manga_id
        
        result = vermanhwa_read_details(resolved_url, chat_id)
        result["_edit"] = True
        return result

    # VerManhwa chapter from search results (read: callback with VerManhwa URL)
    if data.startswith("fav:"):
        from app.tools.manga import manga_add_favorite, _resolve_callback
        
        token = data.split(":", 1)[1] if ":" in data else ""
        resolved_url = _resolve_callback(token) or token
        
        return manga_add_favorite(chat_id, token)

    if data == "manga:back":
        from app.tools.manga import manga_menu
        
        # Eliminar todos los menus manga anteriores antes de volver al menu principal
        _delete_old_manga_menu(chat_id)
        
        result = manga_menu(chat_id)
        result["_edit"] = True
        return result

    if data.startswith("manga:back:"):
        from app.tools.manga import manga_resolve_menu
        
        # Extraer el back_ref (puede contener varios partes separadas por :)
        parts = data.split(":")
        back_ref = ":".join(parts[2:]) if len(parts) > 2 else ""
        
        if not back_ref:
            return {"type": "text", "text": "No pude determinar a donde volver."}
        
        # Resolver el menu guardado y mostrarlo
        result = manga_resolve_menu(back_ref)
        if result and result.get("type") == "menu":
            _delete_old_manga_menu(chat_id)
            result["_edit"] = True
            return result
        
        # Si no se pudo resolver, volver al menu principal
        from app.tools.manga import manga_menu
        _delete_old_manga_menu(chat_id)
        result = manga_menu(chat_id)
        result["_edit"] = True
        return result

    # ========== REMINDER CALLBACKS ==========
    if data == "reminder:create":
        from app.core.chat_state import set_pending_followup, set_reminder_session
        from app.utils.reminder_ui import reminder_create_step1

        set_pending_followup(chat_id, "reminder")
        set_reminder_session(chat_id, {"step": "await_task"})
        return reminder_create_step1()

    if data == "reminder:list":
        from app.tools.reminders import list_reminders
        from app.utils.reminder_ui import reminder_list_menu

        reminders = list_reminders(chat_id)
        result = reminder_list_menu(reminders)
        result["_edit"] = True
        return result

    if data == "reminder:delete_menu":
        from app.tools.reminders import list_reminders
        from app.utils.reminder_ui import reminder_delete_menu

        reminders = [r for r in list_reminders(chat_id) if not r.get("completed")]
        result = reminder_delete_menu(reminders)
        result["_edit"] = True
        return result

    if data == "reminder:date_manual":
        from app.core.chat_state import get_reminder_session, set_pending_followup, set_reminder_session
        from app.utils.reminder_ui import reminder_create_manual_date

        session = get_reminder_session(chat_id) or {}
        task = session.get("task", "")
        set_pending_followup(chat_id, "reminder")
        set_reminder_session(chat_id, {"step": "await_date_manual", "task": task})
        return reminder_create_manual_date()

    # Date selection: reminder:date:YYYY-MM-DD
    if data.startswith("reminder:date:"):
        from app.core.chat_state import get_reminder_session, clear_pending_followup, clear_reminder_session
        from app.tools.reminders import add_reminder
        from app.utils.reminder_ui import reminder_created_menu

        session = get_reminder_session(chat_id)
        task = session.get("task", "") if session else ""
        target_date_str = data.split(":", 2)[2] if ":" in data else ""

        clear_pending_followup(chat_id)
        clear_reminder_session(chat_id)

        result = add_reminder(chat_id, task, target_date_str)
        if result["ok"]:
            return reminder_created_menu(result)
        return {"type": "text", "text": f"No pude crear el recordatorio: {result['message']}", "_edit": True}

    if data.startswith("reminder:complete:"):
        from app.core.chat_state import clear_pending_followup, clear_reminder_session
        from app.tools.reminders import complete_reminder, list_reminders
        from app.utils.reminder_ui import reminder_list_menu

        reminder_id = data.split(":", 2)[2] if ":" in data else ""
        action_result = complete_reminder(chat_id, reminder_id)
        clear_pending_followup(chat_id)
        clear_reminder_session(chat_id)

        reminders = list_reminders(chat_id)
        result = reminder_list_menu(reminders)
        if not action_result.get("ok"):
            result["text"] = f"{action_result['message']}\n\n{result.get('text', '')}"
        result["_edit"] = True
        return result

    if data.startswith("reminder:delete:"):
        from app.core.chat_state import clear_pending_followup, clear_reminder_session
        from app.tools.reminders import delete_reminder, list_reminders
        from app.utils.reminder_ui import reminder_delete_menu

        reminder_id = data.split(":", 2)[2] if ":" in data else ""
        action_result = delete_reminder(chat_id, reminder_id)
        clear_pending_followup(chat_id)
        clear_reminder_session(chat_id)

        reminders = [r for r in list_reminders(chat_id) if not r.get("completed")]
        result2 = reminder_delete_menu(reminders)
        if not action_result.get("ok"):
            result2["text"] = f"{action_result['message']}\n\n{result2.get('text', '')}"
        result2["_edit"] = True
        return result2

    if data == "reminder:back":
        from app.core.chat_state import clear_pending_followup, clear_reminder_session
        from app.utils.reminder_ui import reminder_main_menu

        clear_pending_followup(chat_id)
        clear_reminder_session(chat_id)
        return reminder_main_menu()

    return None
