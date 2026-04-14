def extract_playlist_batch_queries(playlist_name: str, raw_query_block: str):
    queries = []
    normalized_playlist = (playlist_name or "").strip().lower()

    for raw_line in (raw_query_block or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lowered = line.lower()
        prefix = f"/playlist add {normalized_playlist} |"
        if lowered.startswith(prefix):
            line = line[len(prefix):].strip()
        elif lowered.startswith("/playlist add ") and "|" in line:
            _, line = line.split("|", 1)
            line = line.strip()

        if line:
            queries.append(line)

    return queries


def handle_playlist_command(command: str, chat_id, logger=None):
    from app.tools.music_local import (
        playlist_add,
        playlist_add_many,
        playlist_create,
        playlist_delete,
        playlist_list,
        playlist_play,
        playlist_remove,
        playlist_view,
    )
    from app.utils.playlist_ui import coerce_playlist_feedback, playlist_picker_menu

    if not command:
        return playlist_picker_menu(chat_id), ["music_tool"]
    if command.startswith("crear "):
        return playlist_create(chat_id, command[6:].strip()), ["music_tool"]
    if command.startswith("add "):
        payload = command[4:].strip()
        if "|" not in payload:
            return "Usa este formato: /playlist add nombre | canción", ["music_tool"]

        playlist_name, track_query = [part.strip() for part in payload.split("|", 1)]
        batch_queries = extract_playlist_batch_queries(playlist_name, track_query)
        if len(batch_queries) > 1:
            return playlist_add_many(chat_id, playlist_name, batch_queries), ["music_tool"]

        single_query = batch_queries[0] if batch_queries else track_query
        raw_result = playlist_add(chat_id, playlist_name, single_query)
        if logger is not None:
            logger.info(
                "🎵 PLAYLIST DIRECT ADD RESULT TYPE: %s | VALUE PREVIEW: %s",
                type(raw_result).__name__,
                str(raw_result)[:300]
            )
        return coerce_playlist_feedback(raw_result), ["music_tool"]
    if command.startswith("ver "):
        return playlist_view(chat_id, command[4:].strip()), ["music_tool"]
    if command.startswith("play "):
        return playlist_play(chat_id, command[5:].strip()), ["music_tool"]
    if command == "listas":
        return playlist_list(chat_id), ["music_tool"]
    if command.startswith("remove "):
        payload = command[7:].strip()
        if "|" not in payload:
            return "Usa este formato: /playlist remove nombre | posicion", ["music_tool"]

        playlist_name, index_value = [part.strip() for part in payload.split("|", 1)]
        return playlist_remove(chat_id, playlist_name, index_value), ["music_tool"]
    if command.startswith("borrar "):
        return playlist_delete(chat_id, command[7:].strip()), ["music_tool"]

    return (
        "Comandos de playlist:\n"
        "- /playlist listas\n"
        "- /playlist crear <nombre>\n"
        "- /playlist add <nombre> | <canción>\n"
        "- /playlist remove <nombre> | <posición>\n"
        "- /playlist borrar <nombre>\n"
        "- /playlist ver <nombre>\n"
        "- /playlist play <nombre>"
    ), ["music_tool"]
