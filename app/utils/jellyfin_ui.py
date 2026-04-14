from app.tools.jellyfin import jellyfin


def format_jellyfin_lang(lang):
    if not lang:
        return "Desconocido"

    lang = lang.lower()

    if lang.startswith("spa"):
        return "🇪🇸 Español"
    if lang.startswith("eng"):
        return "🇬🇧 Inglés"
    if lang.startswith("ger"):
        return "🇩🇪 Alemán"
    if lang.startswith("rus"):
        return "🇷🇺 Ruso"
    return f"🎧 {lang.upper()}"


def build_jellyfin_audio_buttons(item_id, audio_tracks):
    buttons = []
    used_langs = set()

    for track in audio_tracks:
        lang = track.get("language")
        if not lang or lang in used_langs:
            continue

        used_langs.add(lang)
        index = jellyfin.get_audio_stream_by_language(item_id, lang)
        if index is None:
            continue

        url = jellyfin.get_stream_url(item_id, index)
        buttons.append([
            {
                "text": format_jellyfin_lang(lang),
                "url": url,
            }
        ])

    if not buttons:
        buttons = [[{"text": "▶ Reproducir", "url": jellyfin.get_stream_url(item_id, 0)}]]

    return buttons
