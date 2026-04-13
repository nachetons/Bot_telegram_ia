from app.tools.jellyfin import jellyfin
from app.tools.youtube import download_youtube_audio, download_youtube_video
import logging

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

    return None
