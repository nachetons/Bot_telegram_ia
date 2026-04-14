def playlist_manage_buttons(playlist_name):
    return [
        [
            {"text": "➕ Añadir", "callback_data": f"playlist_action:add:{playlist_name}"},
            {"text": "🗑 Quitar canción", "callback_data": f"playlist_action:remove:{playlist_name}"},
        ],
        [
            {"text": "📄 Ver", "callback_data": f"playlist_action:view:{playlist_name}"},
            {"text": "▶ Reproducir", "callback_data": f"playlist_action:play:{playlist_name}"},
        ],
        [
            {"text": "❌ Borrar playlist", "callback_data": f"playlist_action:delete:{playlist_name}"},
        ],
    ]


def playlist_picker_menu(chat_id):
    from app.tools.music_local import playlist_names

    names = playlist_names(chat_id)
    if not names:
        return (
            "No tienes playlists creadas todavía.\n"
            "Crea una con /playlist crear <nombre>"
        )

    buttons = [
        [{"text": name, "callback_data": f"playlist_manage:{name}"}]
        for name in names[:30]
    ]
    return {
        "type": "menu",
        "text": "¿Qué playlist quieres utilizar?",
        "buttons": buttons,
    }


def playlist_remove_menu(chat_id, playlist_name):
    from app.tools.music_local import playlist_tracks

    tracks = playlist_tracks(chat_id, playlist_name)
    if tracks is None:
        return {"type": "text", "text": f"No existe la playlist '{playlist_name}'."}
    if not tracks:
        return {"type": "text", "text": f"La playlist '{playlist_name}' está vacía."}

    buttons = []
    for index, track in enumerate(tracks[:20], start=1):
        title = track.get("title", "Sin título")[:40]
        buttons.append([
            {
                "text": f"🗑 {index}. {title}",
                "callback_data": f"playlist_remove_item:{playlist_name}:{index}",
            }
        ])

    return {
        "type": "menu",
        "text": f"¿Qué canción quieres quitar de '{playlist_name}'?",
        "buttons": buttons,
    }


def playlist_manage_menu(playlist_name, extra_text=None):
    text = f"Playlist seleccionada: {playlist_name}\n¿Qué quieres hacer?"
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    return {
        "type": "menu",
        "text": text,
        "buttons": playlist_manage_buttons(playlist_name),
    }


def coerce_playlist_feedback(value):
    if value is None:
        return "No pude completar la operación sobre la playlist."

    if isinstance(value, dict):
        if value.get("error"):
            return str(value.get("error"))
        if value.get("type") == "text":
            return str(value.get("text", "No pude completar la operación sobre la playlist."))
        if value.get("type") == "youtube":
            return "Encontré resultados de YouTube, pero no pude guardar la canción en la playlist."
        if value.get("type") == "menu":
            return "La operación devolvió un menú inesperado y no se guardó la canción."
        return "Recibí una respuesta inesperada al guardar la canción."

    return str(value)
