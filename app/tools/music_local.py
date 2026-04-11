import json
import re
import time
from pathlib import Path

from app.tools.youtube import (
    download_best_youtube_audio,
    download_youtube_audio,
    find_best_youtube_match,
    search_youtube,
)


DATA_DIR = Path("data/music/users")


def _ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _user_file(chat_id):
    _ensure_storage()
    return DATA_DIR / f"{chat_id}.json"


def _default_payload():
    return {
        "history": [],
        "favorites": [],
        "playlists": {},
    }


def _load_user(chat_id):
    path = _user_file(chat_id)
    if not path.exists():
        return _default_payload()

    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return _default_payload()


def _save_user(chat_id, payload):
    path = _user_file(chat_id)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_name(value: str):
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    return cleaned


def _split_batch_lines(value: str):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _find_best_result(query: str):
    item, error = find_best_youtube_match(query, max_results=4, mode="music")
    if error:
        return None, error
    return item, None


def _normalize_lookup_error(error):
    if not error:
        return None

    if isinstance(error, dict):
        if error.get("error"):
            return str(error.get("error"))
        if error.get("text"):
            return str(error.get("text"))
        return "No pude resolver esa canción ahora mismo."

    return str(error)


def _track_summary(item):
    if not item:
        return "Sin título"

    channel = item.get("channel") or "Canal desconocido"
    return f"{item.get('title', 'Sin título')} - {channel}"


def _append_history(chat_id, item, query):
    payload = _load_user(chat_id)
    payload["history"].insert(
        0,
        {
            "video_id": item.get("video_id"),
            "title": item.get("title"),
            "channel": item.get("channel"),
            "url": item.get("url"),
            "query": query,
            "saved_at": int(time.time()),
        },
    )
    payload["history"] = payload["history"][:100]
    _save_user(chat_id, payload)


def _add_favorite_item(chat_id, item):
    payload = _load_user(chat_id)
    video_id = item.get("video_id")
    if any(fav.get("video_id") == video_id for fav in payload["favorites"]):
        return False

    payload["favorites"].insert(
        0,
        {
            "video_id": video_id,
            "title": item.get("title"),
            "channel": item.get("channel"),
            "url": item.get("url"),
            "saved_at": int(time.time()),
        },
    )
    payload["favorites"] = payload["favorites"][:100]
    _save_user(chat_id, payload)
    return True


def _playlist_buttons(tracks):
    buttons = []
    for track in tracks[:10]:
        video_id = track.get("video_id")
        title = track.get("title", "Sin título")[:40]
        if not video_id:
            continue
        buttons.append(
            [
                {"text": f"🎵 {title}", "callback_data": f"music_play:{video_id}"},
                {"text": "🔗", "url": track.get("url", "")},
            ]
        )
    return buttons


def _top_channels(payload, limit=3):
    scores = {}
    for item in payload.get("favorites", []) + payload.get("history", [])[:30]:
        channel = item.get("channel")
        if channel:
            scores[channel] = scores.get(channel, 0) + 1
    return [name for name, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:limit]]


def music_run(query: str, chat_id):
    cleaned = _normalize_name(query).strip()
    lowered = cleaned.lower()

    if not cleaned:
        payload = _load_user(chat_id)
        lines = [
            "Comandos de música:",
            "- /music <consulta>",
            "- /music buscar <consulta>",
            "- /music fav <consulta>",
            "- /music favs",
            "- /music recomendar",
            "- /playlist crear <nombre>",
            "- /playlist add <nombre> | <consulta>",
            "- /playlist ver <nombre>",
            "- /playlist play <nombre>",
        ]
        if payload.get("favorites"):
            lines.append(f"- Favoritos guardados: {len(payload['favorites'])}")
        if payload.get("playlists"):
            lines.append(f"- Playlists creadas: {len(payload['playlists'])}")
        return "\n".join(lines)

    if lowered == "favs":
        payload = _load_user(chat_id)
        favorites = payload.get("favorites", [])
        if not favorites:
            return "Todavía no tienes favoritos guardados."

        lines = ["Tus favoritos musicales:"]
        for index, item in enumerate(favorites[:10], start=1):
            lines.append(f"{index}. {_track_summary(item)}")

        return {
            "type": "menu",
            "text": "\n".join(lines),
            "buttons": _playlist_buttons(favorites[:10]),
        }

    if lowered == "recomendar":
        payload = _load_user(chat_id)
        channels = _top_channels(payload)
        if not channels:
            return "Necesito algo de historial o favoritos antes de recomendarte música."

        query_seed = f"{channels[0]} official music"
        results = search_youtube(query_seed, max_results=5, mode="music")
        if results.get("error"):
            return results

        lines = [f"Recomendaciones rápidas basadas en {channels[0]}:"]
        for index, item in enumerate(results.get("results", [])[:5], start=1):
            lines.append(f"{index}. {_track_summary(item)}")

        return {
            "type": "menu",
            "text": "\n".join(lines),
            "buttons": _playlist_buttons(results.get("results", [])[:5]),
        }

    if lowered.startswith("buscar "):
        search_query = cleaned[7:].strip()
        results = search_youtube(search_query, max_results=5, mode="music")
        if results.get("error"):
            return results

        tracks = results.get("results", [])[:5]
        lines = [f"Resultados de música para: {search_query}"]
        for index, item in enumerate(tracks, start=1):
            lines.append(f"{index}. {_track_summary(item)}")

        return {
            "type": "menu",
            "text": "\n".join(lines),
            "buttons": _playlist_buttons(tracks),
        }

    if lowered.startswith("fav "):
        fav_query = cleaned[4:].strip()
        item, error = _find_best_result(fav_query)
        if error:
            return error

        created = _add_favorite_item(chat_id, item)
        if not created:
            return f"Ya tenías guardado: {_track_summary(item)}"

        return f"Guardado en favoritos: {_track_summary(item)}"

    downloaded = download_best_youtube_audio(cleaned)
    if downloaded.get("error"):
        return downloaded

    _append_history(
        chat_id,
        {
            "video_id": downloaded.get("source_url", "").split("v=")[-1],
            "title": downloaded.get("title"),
            "channel": (downloaded.get("caption", "").split("Canal: ")[-1] if "Canal: " in downloaded.get("caption", "") else ""),
            "url": downloaded.get("source_url"),
        },
        cleaned,
    )
    return downloaded


def playlist_create(chat_id, name: str):
    playlist_name = _normalize_name(name)
    if not playlist_name:
        return "Indica un nombre de playlist."

    payload = _load_user(chat_id)
    playlists = payload.setdefault("playlists", {})
    if playlist_name in playlists:
        return f"La playlist '{playlist_name}' ya existe."

    playlists[playlist_name] = []
    _save_user(chat_id, payload)
    return f"Playlist creada: {playlist_name}"


def playlist_add(chat_id, playlist_name: str, query: str):
    playlist_name = _normalize_name(playlist_name)
    track_query = _normalize_name(query)

    if not playlist_name or not track_query:
        return "Usa este formato: /playlist add nombre | canción"

    payload = _load_user(chat_id)
    playlists = payload.setdefault("playlists", {})
    if playlist_name not in playlists:
        return f"No existe la playlist '{playlist_name}'."

    item, error = _find_best_result(track_query)
    normalized_error = _normalize_lookup_error(error)
    if normalized_error:
        return normalized_error

    if not isinstance(item, dict) or not item.get("video_id"):
        return "No pude encontrar una canción válida para añadir."

    if any(track.get("video_id") == item.get("video_id") for track in playlists[playlist_name]):
        return "Esa canción ya está en la playlist."

    playlists[playlist_name].append(
        {
            "video_id": item.get("video_id"),
            "title": item.get("title"),
            "channel": item.get("channel"),
            "url": item.get("url"),
            "query": track_query,
        }
    )
    _save_user(chat_id, payload)
    return f"Añadida a '{playlist_name}': {_track_summary(item)}"


def playlist_add_many(chat_id, playlist_name: str, queries):
    playlist_name = _normalize_name(playlist_name)
    payload = _load_user(chat_id)
    playlists = payload.setdefault("playlists", {})

    if playlist_name not in playlists:
        return f"No existe la playlist '{playlist_name}'."

    added = []
    skipped = []

    for raw_query in queries:
        track_query = _normalize_name(raw_query)
        if not track_query:
            continue

        item, error = _find_best_result(track_query)
        normalized_error = _normalize_lookup_error(error)
        if normalized_error or not isinstance(item, dict) or not item.get("video_id"):
            skipped.append(f"{track_query} (sin resultado)")
            continue

        if any(track.get("video_id") == item.get("video_id") for track in playlists[playlist_name]):
            skipped.append(f"{track_query} (duplicada)")
            continue

        playlists[playlist_name].append(
            {
                "video_id": item.get("video_id"),
                "title": item.get("title"),
                "channel": item.get("channel"),
                "url": item.get("url"),
                "query": track_query,
            }
        )
        added.append(_track_summary(item))

    _save_user(chat_id, payload)

    if not added and skipped:
        return "No pude añadir canciones.\n" + "\n".join(f"- {item}" for item in skipped[:10])

    lines = [f"Playlist actualizada: {playlist_name}"]
    if added:
        lines.append("Añadidas:")
        lines.extend(f"- {item}" for item in added[:10])
    if skipped:
        lines.append("Omitidas:")
        lines.extend(f"- {item}" for item in skipped[:10])

    return "\n".join(lines)


def playlist_view(chat_id, playlist_name: str):
    playlist_name = _normalize_name(playlist_name)
    payload = _load_user(chat_id)
    tracks = payload.get("playlists", {}).get(playlist_name)
    if tracks is None:
        return f"No existe la playlist '{playlist_name}'."

    if not tracks:
        return f"La playlist '{playlist_name}' está vacía."

    lines = [f"Playlist: {playlist_name}"]
    for index, item in enumerate(tracks[:20], start=1):
        lines.append(f"{index}. {_track_summary(item)}")

    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": _playlist_buttons(tracks[:10]),
    }


def playlist_list(chat_id):
    payload = _load_user(chat_id)
    playlists = payload.get("playlists", {})
    if not playlists:
        return "Todavía no has creado ninguna playlist."

    lines = ["Tus playlists:"]
    for name, tracks in playlists.items():
        lines.append(f"- {name} ({len(tracks)} canciones)")
    return "\n".join(lines)


def playlist_names(chat_id):
    payload = _load_user(chat_id)
    return list(payload.get("playlists", {}).keys())


def playlist_tracks(chat_id, playlist_name: str):
    playlist_name = _normalize_name(playlist_name)
    payload = _load_user(chat_id)
    tracks = payload.get("playlists", {}).get(playlist_name)
    return tracks if isinstance(tracks, list) else None


def playlist_remove(chat_id, playlist_name: str, index_value: str):
    playlist_name = _normalize_name(playlist_name)
    payload = _load_user(chat_id)
    tracks = payload.get("playlists", {}).get(playlist_name)

    if tracks is None:
        return f"No existe la playlist '{playlist_name}'."

    if not index_value.isdigit():
        return "Indica la posición numérica a borrar. Ejemplo: /playlist remove motivacion | 2"

    index = int(index_value) - 1
    if index < 0 or index >= len(tracks):
        return "La posición indicada no existe en esa playlist."

    removed = tracks.pop(index)
    _save_user(chat_id, payload)
    return f"Eliminada de '{playlist_name}': {_track_summary(removed)}"


def playlist_delete(chat_id, playlist_name: str):
    playlist_name = _normalize_name(playlist_name)
    payload = _load_user(chat_id)
    playlists = payload.get("playlists", {})

    if playlist_name not in playlists:
        return f"No existe la playlist '{playlist_name}'."

    del playlists[playlist_name]
    _save_user(chat_id, payload)
    return f"Playlist eliminada: {playlist_name}"


def playlist_play(chat_id, playlist_name: str):
    playlist_name = _normalize_name(playlist_name)
    payload = _load_user(chat_id)
    tracks = payload.get("playlists", {}).get(playlist_name)
    if tracks is None:
        return f"No existe la playlist '{playlist_name}'."

    if not tracks:
        return f"La playlist '{playlist_name}' está vacía."

    first = tracks[0]
    video_id = first.get("video_id")
    if not video_id:
        return "No pude reproducir el primer elemento de la playlist."

    return download_youtube_audio(video_id)
