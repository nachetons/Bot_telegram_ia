from app.tools.jellyfin import jellyfin
import logging

logger = logging.getLogger("bot")

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
    # 2. SELECCIÓN DE SERIE -> MOSTRAR EPISODIOS
    # ---------------------------------------------------------
    if data.startswith("open_series:"):
        series_id = data.split(":")[1]
        
        # Obtenemos todos los episodios y filtramos por la serie seleccionada
        try:
            all_episodes = jellyfin.get_all_tv()
            # IMPORTANTE: Filtramos para que solo salgan los episodios de esta serie
            episodes = [e for e in all_episodes if e.get("SeriesId") == series_id or e.get("ParentId") == series_id]
            
            if not episodes:
                # Si get_all_tv no trae los IDs de padre, podrías necesitar una función específica 
                # en jellyfin.py llamada get_episodes_by_series(series_id)
                return {"type": "text", "text": "No se encontraron episodios para esta serie."}
        except Exception as e:
            logger.error(f"Error filtrando episodios: {e}")
            return {"type": "text", "text": "Error al cargar episodios."}

        buttons = []
        for e in episodes[:50]: # Mostramos hasta 50 episodios
            buttons.append([
                {
                    "text": f"▶️ {e.get('Name', 'Episodio')}",
                    "callback_data": f"play_episode:{e['Id']}"
                }
            ])

        return {
            "type": "menu",
            "text": "📺 **Selecciona un episodio:**",
            "buttons": buttons
        }

    # ---------------------------------------------------------
    # 3. REPRODUCIR (Película o Episodio)
    # ---------------------------------------------------------
    if data.startswith("play_movie:") or data.startswith("play_episode:"):
        item_id = data.split(":")[1]
        return jellyfin.run_by_id(item_id)

    return None