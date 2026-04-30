import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from yt_dlp import YoutubeDL

from app.config import FFMPEG_LOCATION, YOUTUBE_MAX_HEIGHT

logger = logging.getLogger("youtube")


TEMP_DIR = Path("data/youtube_temp")
TEMP_TTL_SECONDS = 3600
SEARCH_CACHE_TTL_SECONDS = 900
DOWNLOAD_CACHE_TTL_SECONDS = 3600

_search_cache = {}
_download_cache = {}
_cache_lock = threading.Lock()


class _SilentYTDLPLogger:
    def debug(self, msg):
        return None

    def warning(self, msg):
        return None

    def error(self, msg):
        return None


def _youtube_watch_url(video_id: str):
    return f"https://www.youtube.com/watch?v={video_id}"


def _ensure_temp_dir():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def _manifest_path(video_id: str, media_type: str):
    return TEMP_DIR / f"{video_id}.{media_type}.json"


def _write_manifest(video_id: str, media_type: str, payload: dict):
    try:
        _manifest_path(video_id, media_type).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _read_manifest(video_id: str, media_type: str):
    path = _manifest_path(video_id, media_type)
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cleanup_temp_videos():
    _ensure_temp_dir()
    now = time.time()

    for path in TEMP_DIR.iterdir():
        try:
            if not path.is_file():
                continue

            if now - path.stat().st_mtime > TEMP_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except Exception:
            continue

    with _cache_lock:
        expired_search = [
            key for key, value in _search_cache.items()
            if now - value.get("saved_at", 0) > SEARCH_CACHE_TTL_SECONDS
        ]
        for key in expired_search:
            _search_cache.pop(key, None)

        expired_download = [
            key for key, value in _download_cache.items()
            if now - value.get("saved_at", 0) > DOWNLOAD_CACHE_TTL_SECONDS
        ]
        for key in expired_download:
            cached_path = Path(value.get("path", ""))
            if not cached_path.exists():
                _download_cache.pop(key, None)


def _pick_thumbnail(entry: dict):
    thumbnails = entry.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumb in sorted(
            thumbnails,
            key=lambda item: (item.get("height", 0), item.get("width", 0)),
            reverse=True,
        ):
            if thumb.get("url"):
                return thumb["url"]

    if entry.get("thumbnail"):
        return entry["thumbnail"]

    return None


def _mode_tokens(mode: str):
    mode = (mode or "generic").lower()
    if mode == "music":
        return {
            "bonus_title": ["official audio", "audio oficial", "topic", "provided to youtube", "audio"],
            "penalty_title": ["lyrics", "lyric", "letra", "live", "directo", "cover", "karaoke", "reaction", "slowed", "nightcore", "clip", "skills", "goals"],
            "bonus_channel": ["topic", "vevo", "official"],
        }
    if mode == "video":
        return {
            "bonus_title": ["official video", "video oficial", "official music video", "vevo"],
            "penalty_title": ["lyrics", "lyric", "letra", "audio", "topic", "slowed", "nightcore"],
            "bonus_channel": ["vevo", "official"],
        }
    return {
        "bonus_title": ["official", "oficial"],
        "penalty_title": ["lyrics", "lyric", "letra", "live", "directo", "cover", "karaoke", "reaction", "slowed", "nightcore"],
        "bonus_channel": ["official", "topic", "vevo"],
    }


def _score_entry(entry: dict, query: str, mode: str = "generic"):
    title = (entry.get("title") or "").lower()
    uploader = (entry.get("uploader") or entry.get("channel") or "").lower()
    view_count = int(entry.get("view_count") or 0)
    query_lower = (query or "").lower()
    token_config = _mode_tokens(mode)

    score = view_count

    for token in token_config["bonus_title"]:
        if token in title:
            score += 40_000_000

    for token in token_config["bonus_channel"]:
        if token in uploader:
            score += 15_000_000

    for token in token_config["penalty_title"]:
        if token in title:
            score -= 20_000_000

    for token in query_lower.split():
        if token and token in title:
            score += 500_000

    return score


def _search_cache_key(query: str, max_results: int, mode: str):
    return ((query or "").strip().lower(), int(max_results), (mode or "generic").lower())


def _get_cached_search(query: str, max_results: int, mode: str):
    key = _search_cache_key(query, max_results, mode)
    with _cache_lock:
        payload = _search_cache.get(key)
        if not payload:
            return None

        if time.time() - payload.get("saved_at", 0) > SEARCH_CACHE_TTL_SECONDS:
            _search_cache.pop(key, None)
            return None

        return payload.get("data")


def _set_cached_search(query: str, max_results: int, mode: str, data: dict):
    key = _search_cache_key(query, max_results, mode)
    with _cache_lock:
        _search_cache[key] = {
            "saved_at": time.time(),
            "data": data,
        }


def _download_cache_key(video_id: str, media_type: str):
    return f"{media_type}:{(video_id or '').strip()}"


def _get_cached_download(video_id: str, media_type: str):
    key = _download_cache_key(video_id, media_type)
    with _cache_lock:
        cached = _download_cache.get(key)

    if cached:
        path = Path(cached.get("path", ""))
        if path.exists():
            return dict(cached)

    manifest = _read_manifest(video_id, media_type)
    if manifest:
        path = Path(manifest.get("path", ""))
        if path.exists():
            manifest["saved_at"] = time.time()
            with _cache_lock:
                _download_cache[key] = manifest
            return dict(manifest)

    for path in TEMP_DIR.glob(f"{video_id}-*"):
        if not path.is_file() or path.suffix == ".json":
            continue

        if media_type == "audio" and path.suffix.lower() not in {".mp3", ".m4a", ".webm", ".opus"}:
            continue
        if media_type == "video" and path.suffix.lower() not in {".mp4", ".mkv", ".webm"}:
            continue

        guessed = {
            "type": "local_audio" if media_type == "audio" else "local_video",
            "path": str(path),
            "title": path.stem.split("-", 1)[-1].replace("_", " "),
            "performer": "" if media_type == "audio" else None,
            "caption": path.stem.split("-", 1)[-1].replace("_", " "),
            "url": _youtube_watch_url(video_id),
            "saved_at": time.time(),
        }
        with _cache_lock:
            _download_cache[key] = guessed
        return guessed

    return None


def _set_cached_download(video_id: str, media_type: str, data: dict):
    payload = dict(data)
    payload["saved_at"] = time.time()
    key = _download_cache_key(video_id, media_type)
    with _cache_lock:
        _download_cache[key] = payload
    _write_manifest(video_id, media_type, payload)


def search_youtube(query: str, max_results: int = 5, mode: str = "generic"):
    cleanup_temp_videos()

    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {"error": "Â¿QuÃ© vÃ­deo quieres buscar en YouTube?"}

    cached = _get_cached_search(cleaned_query, max_results, mode)
    if cached:
        return cached

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "logger": _SilentYTDLPLogger(),
    }

    with YoutubeDL(options) as ydl:
        data = ydl.extract_info(
            f"ytsearch{max(1, min(max_results, 10))}:{cleaned_query}",
            download=False
        )

    items = []
    raw_entries = [entry for entry in (data.get("entries", []) or []) if isinstance(entry, dict)]
    raw_entries.sort(key=lambda item: _score_entry(item, cleaned_query, mode), reverse=True)

    for entry in raw_entries:
        video_id = (entry.get("id") or "").strip()
        if not video_id:
            continue

        uploader = entry.get("uploader") or entry.get("channel") or "Canal desconocido"
        items.append(
            {
                "video_id": video_id,
                "title": entry.get("title") or "Sin tÃ­tulo",
                "channel": uploader,
                "description": entry.get("description") or "",
                "thumbnail": _pick_thumbnail(entry),
                "published_at": str(entry.get("upload_date") or ""),
                "url": _youtube_watch_url(video_id),
                "duration": entry.get("duration"),
                "view_count": int(entry.get("view_count") or 0),
            }
        )

    if not items:
        return {"error": "No encontrÃ© vÃ­deos en YouTube para esa bÃºsqueda."}

    top = items[0]
    lines = [f"Resultados de YouTube para: {cleaned_query}"]
    buttons = []

    for index, item in enumerate(items[:5], start=1):
        lines.append(f"{index}. {item['title']} - {item['channel']}")
        buttons.append(
            [
                {"text": f"ðŸ“¥ TG {index}", "callback_data": f"youtube_play:{item['video_id']}"},
                {"text": f"ðŸ”— {index}", "url": item["url"]},
            ]
        )

    caption_parts = [top["title"], f"Canal: {top['channel']}"]
    if top.get("published_at"):
        raw_date = top["published_at"]
        if len(raw_date) == 8 and raw_date.isdigit():
            raw_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        caption_parts.append(f"Publicado: {raw_date[:10]}")

    result = {
        "type": "youtube",
        "query": cleaned_query,
        "text": "\n".join(lines),
        "thumbnail": top.get("thumbnail"),
        "caption": "\n".join(caption_parts),
        "buttons": buttons,
        "results": items,
    }
    _set_cached_search(cleaned_query, max_results, mode, result)
    return result


def find_best_youtube_match(query: str, max_results: int = 4, mode: str = "generic"):
    results = search_youtube(query, max_results=max_results, mode=mode)
    if results.get("error"):
        return None, results.get("error")

    top_result = (results.get("results") or [None])[0]
    if not top_result:
        return None, "No encontrÃ© un resultado vÃ¡lido."

    return top_result, None


def download_youtube_video(video_id: str):
    """Descarga video de YouTube con optimizaciÃ³n automÃ¡tica de resoluciÃ³n segÃºn tamaÃ±o."""
    cleanup_temp_videos()
    _ensure_temp_dir()

    # Si es un texto (query), buscar el primer resultado y extraer su ID
    if "youtube.com" not in video_id and "youtu.be" not in video_id:
        logger.info(f"ðŸ” Buscando video por query: {video_id}")
        search_result = _search_youtube(video_id)
        if search_result.get("error"):
            return search_result

        clean_video_id = search_result["video_id"]
        logger.info(f"âœ… Video encontrado: {clean_video_id} - {search_result['title']}")
    else:
        # Extraer video_id de la URL
        clean_video_id = _extract_video_id(video_id)

    cached = _get_cached_download(clean_video_id, "video")
    if cached:
        cached_path = Path(cached.get("path", ""))
        if cached_path.exists() and shutil.which("ffmpeg"):
            converted_path = _ensure_video_has_aac_audio(cached_path)
            if converted_path != cached_path:
                cached["path"] = str(converted_path)
                cached["size_mb"] = round(converted_path.stat().st_size / (1024 * 1024), 2)
                cached["send_as"] = "video" if converted_path.stat().st_size <= TELEGRAM_VIDEO_LIMIT_BYTES else "document"
                _set_cached_download(clean_video_id, "video", cached)
        return cached

    # Resoluciones a intentar en orden preferente (de mayor a menor)
    resolutions_to_try = [1080, 720, 480, 360]

    for height in resolutions_to_try:
        logger.info(f"ðŸŽ¬ Intentando descargar a {height}p...")
        result = _try_download_with_resolution(clean_video_id, height)

        if "error" in result:
            logger.warning(f"âš ï¸ FallÃ³ a {height}p: {result['error']}")
            continue

        # Verificar si el tamaÃ±o es aceptable (<50MB para documento o <20MB para video)
        path = Path(result.get("path", ""))
        if path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)

            # Si cabe en Telegram, devolverlo
            if size_mb <= 50:  # LÃ­mite de documento
                logger.info(f"âœ… Video descargado exitosamente: {size_mb:.2f} MB at {height}p")
                return result

            # Si es muy grande pero ya intentamos la mejor resoluciÃ³n, seguir probando
            if height == resolutions_to_try[0]:  # 1080p fue el primero
                logger.info(f"âš ï¸ Video de {size_mb:.2f} MB a {height}p, intentando con menor resoluciÃ³n...")

    return {"error": "No se pudo descargar un video que quepa en Telegram"}


def _search_youtube(query: str):
    """Busca un video por query y devuelve el primer resultado."""
    from app.tools.youtube import YoutubeDL

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "search": query,
        "default_search": "ytsearch1",  # Solo el primer resultado
    }

    with YoutubeDL(options) as ydl:
        result = ydl.extract_info(f"ytsearch1:{query}", download=False)

        if result and "entries" in result and result["entries"]:
            entry = result["entries"][0]
            video_id = entry.get("id")
            title = entry.get("title", "")

            return {"video_id": video_id, "title": title}

        return {"error": f"No se encontrÃ³ el video: {query}"}


def _extract_video_id(url: str) -> str:
    """Extrae el video_id de una URL de YouTube."""
    import re

    # Pattern para youtube.com/watch?v=VIDEO_ID
    match = re.search(r"v=([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)

    # Pattern para youtu.be/VIDEO_ID
    match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)

    return url.strip()


def _try_download_with_resolution(video_id: str, max_height: int):
    """Intenta descargar un video con una resoluciÃ³n mÃ¡xima especÃ­fica."""
    output_template = str(TEMP_DIR / f"{video_id}-%(title).80s.%(ext)s")
    source_url = _youtube_watch_url(video_id)

    height_filter = f"[height<={max_height}]" if max_height > 0 else ""

    # Verificar si ffmpeg estÃ¡ disponible
    has_ffmpeg = bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "format": (
            f"bestvideo{height_filter}[ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo{height_filter}+bestaudio/"
            f"best{height_filter}[ext=mp4]/"
            f"best{height_filter}/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best[ext=mp4]/best"
        ),
        "outtmpl": output_template,
        "restrictfilenames": True,
        "merge_output_format": "mp4",
        "logger": _SilentYTDLPLogger(),
        # Filtro de duraciÃ³n mÃ¡xima: 30 minutos (1800 segundos)
        "max_duration": 1800,
    }

    logger.info(f"ðŸ“¥ Descargando video {video_id} a {max_height}p...")

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=True)
        downloaded_path = ydl.prepare_filename(info)


    path = Path(downloaded_path)
    mp3_path = path.with_suffix(".mp3")
    final_path = mp3_path if has_ffmpeg and mp3_path.exists() else path

    if not final_path.exists():
        return {"error": "No pude descargar el audio seleccionado."}

    title = info.get("title") or "Audio de YouTube"

    result = {
        "type": "local_audio",
        "path": str(path),
        "title": title,
        "url": source_url,
        "size_mb": size_mb,
    }

    result["source_url"] = top_result.get("url")
    result["thumbnail"] = top_result.get("thumbnail")
    result["query"] = query

    return result


def download_best_youtube_video(query: str, max_results: int = 4):
    """Descarga video de YouTube con optimizaciÃ³n automÃ¡tica."""
    top_result, error = find_best_youtube_match(query, max_results=max_results, mode="video")
    if error:
        return {"error": error}

    downloaded = download_youtube_video(top_result["video_id"])
    if downloaded.get("error"):
        return downloaded

    downloaded["source_url"] = top_result.get("url")
    downloaded["thumbnail"] = top_result.get("thumbnail")
    downloaded["query"] = query
    return downloaded


def download_best_youtube_audio(query: str, max_results: int = 4):

    """Descarga audio de YouTube (mÃºsica) con optimizaciÃ³n de tamaÃ±o."""
    top_result, error = find_best_youtube_match(query, max_results=max_results, mode="music")
    if error:
        return {"error": error}

    video_id = top_result["video_id"]

    # Descargar solo el audio directamente (no el video completo)
    output_template = str(TEMP_DIR / f"{video_id}-%(title).80s.%(ext)s")
    source_url = _youtube_watch_url(video_id)

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractaudio": True,
        "audio_format": "m4a",
        "outtmpl": output_template,
        # Filtro de duraciÃ³n mÃ¡xima: 10 minutos (600 segundos) para mÃºsica
        "max_duration": 600,
    }

    logger.info(f"ðŸŽµ Descargando audio {video_id}...")

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    path = Path(downloaded_path)

    # Verificar si el archivo existe y obtener su tamaÃ±o
    if not path.exists():
        alt_path = path.with_suffix(".m4a")
        if alt_path.exists():
            path = alt_path

    if not path.exists():
        return {"error": "No se pudo descargar el audio"}

    size_mb = path.stat().st_size / (1024 * 1024)
    logger.info(f"âœ… Audio descargado: {size_mb:.2f} MB")

    result = {
        "type": "local_audio",
        "path": str(path),
        "title": info.get("title"),
        "url": source_url,
        "size_mb": size_mb,
    }

    result["source_url"] = top_result.get("url")
    result["thumbnail"] = top_result.get("thumbnail")
    result["query"] = query

    return result


# ---------------------------------------------------------------------------
# Telegram-safe download layer
# ---------------------------------------------------------------------------
# These definitions intentionally live at the end of the module so they replace
# the experimental versions above without touching the search/cache code.

TELEGRAM_VIDEO_LIMIT_BYTES = 20_000_000
TELEGRAM_DOCUMENT_LIMIT_BYTES = 50_000_000
TELEGRAM_DOWNLOAD_TARGET_BYTES = 47_000_000
VIDEO_COMPAT_VERSION = 2


def _find_executable(name: str):
    configured = (FFMPEG_LOCATION or "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.is_dir():
            candidate = configured_path / name
            if candidate.exists():
                return str(candidate)
            if not name.endswith(".exe"):
                candidate = configured_path / f"{name}.exe"
                if candidate.exists():
                    return str(candidate)
        elif configured_path.name.lower().startswith(name.lower()) and configured_path.exists():
            return str(configured_path)

    found = shutil.which(name)
    if found:
        return found

    for candidate in (
        Path("/usr/bin") / name,
        Path("/usr/local/bin") / name,
        Path("/bin") / name,
        Path("C:/ffmpeg/bin") / f"{name}.exe",
        Path("C:/Program Files/ffmpeg/bin") / f"{name}.exe",
    ):
        if candidate.exists():
            return str(candidate)

    return None


def _ffmpeg_path():
    return _find_executable("ffmpeg")


def _has_ffmpeg():
    return bool(_ffmpeg_path())


def _apply_ffmpeg_location(options: dict):
    ffmpeg = _ffmpeg_path()
    if ffmpeg:
        options["ffmpeg_location"] = str(Path(ffmpeg).parent)
    return options


def _extract_video_id(value: str) -> str:
    import re

    cleaned = (value or "").strip()
    if not cleaned:
        return ""

    for pattern in (
        r"(?:v=|/shorts/|/embed/)([a-zA-Z0-9_-]{6,})",
        r"youtu\.be/([a-zA-Z0-9_-]{6,})",
    ):
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1)

    return cleaned


def _resolve_video_id(value: str):
    cleaned = (value or "").strip()
    if not cleaned:
        return None, "No pude identificar el video de YouTube."

    if "youtube.com" in cleaned or "youtu.be" in cleaned:
        return _extract_video_id(cleaned), None

    top_result, error = find_best_youtube_match(cleaned, max_results=4, mode="video")
    if error:
        return None, error
    return top_result.get("video_id"), None


def _estimated_size(format_info: dict):
    value = format_info.get("filesize") or format_info.get("filesize_approx")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _has_video(format_info: dict):
    return format_info.get("vcodec") not in (None, "none")


def _has_audio(format_info: dict):
    return format_info.get("acodec") not in (None, "none")


def _format_height(format_info: dict):
    try:
        return int(format_info.get("height") or 0)
    except (TypeError, ValueError):
        return 0


def _format_tbr(format_info: dict):
    try:
        return float(format_info.get("tbr") or format_info.get("vbr") or format_info.get("abr") or 0)
    except (TypeError, ValueError):
        return 0


def _probe_youtube_info(video_id: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "logger": _SilentYTDLPLogger(),
    }
    with YoutubeDL(options) as ydl:
        return ydl.extract_info(_youtube_watch_url(video_id), download=False)


def _build_video_candidates(info: dict, max_bytes: int):
    preferred_height = int(YOUTUBE_MAX_HEIGHT or 1080)
    formats = [item for item in (info.get("formats") or []) if isinstance(item, dict)]
    has_ffmpeg = _has_ffmpeg()
    audio_formats = [
        item for item in formats
        if item.get("format_id") and _has_audio(item) and not _has_video(item)
    ]
    compatible_audio = [item for item in audio_formats if item.get("ext") == "m4a"]
    audio_formats = (compatible_audio or audio_formats) if has_ffmpeg else []
    audio_formats.sort(key=lambda item: (item.get("ext") == "m4a", _format_tbr(item)), reverse=True)

    candidates = []
    for fmt in formats:
        format_id = fmt.get("format_id")
        height = _format_height(fmt)
        if not format_id or not _has_video(fmt) or height <= 0 or height > preferred_height:
            continue

        video_size = _estimated_size(fmt)
        if _has_audio(fmt):
            if video_size and video_size <= max_bytes:
                candidates.append({
                    "format": format_id,
                    "height": height,
                    "estimated_bytes": video_size,
                    "audio_ext": "m4a" if str(fmt.get("acodec") or "").startswith("mp4a") else fmt.get("ext"),
                    "score": (height, _format_tbr(fmt), 1 if fmt.get("ext") == "mp4" else 0, 1),
                })
            continue

        for audio in audio_formats[:8]:
            audio_size = _estimated_size(audio)
            total_size = video_size + audio_size if video_size and audio_size else None
            if not total_size or total_size > max_bytes:
                continue
            candidates.append({
                "format": f"{format_id}+{audio['format_id']}",
                "height": height,
                "estimated_bytes": total_size,
                "audio_ext": audio.get("ext"),
                "score": (
                    height,
                    _format_tbr(fmt),
                    1 if fmt.get("ext") == "mp4" else 0,
                    1 if audio.get("ext") == "m4a" else 0,
                ),
            })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    unique = []
    seen = set()
    for item in candidates:
        if item["format"] in seen:
            continue
        seen.add(item["format"])
        unique.append(item)

    return unique


def _existing_downloaded_path(prepared_path: str):
    path = Path(prepared_path)
    preferred_compat = path.with_name(f"{path.stem}.aac.mp4")
    if preferred_compat.exists():
        return preferred_compat

    for candidate in (
        path,
        path.with_name(f"{path.stem}.compat.mp4"),
        path.with_suffix(".mp4"),
        path.with_suffix(".mkv"),
        path.with_suffix(".webm"),
        path.with_suffix(".m4a"),
        path.with_suffix(".mp3"),
    ):
        if candidate.exists():
            return candidate
    return None


def _convert_audio_to_mp3(source_path: Path):
    if source_path.suffix.lower() == ".mp3":
        return source_path

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return None

    target_path = source_path.with_suffix(".mp3")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(target_path),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.warning("No pude convertir audio a mp3: %s", exc)
        return None

    return target_path if target_path.exists() else None


def _ensure_video_has_aac_audio(source_path: Path):
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return source_path

    target_path = source_path.with_name(f"{source_path.stem}.aac{source_path.suffix}")
    if target_path == source_path:
        target_path = source_path.with_name(f"{source_path.stem}.compat.mp4")

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(target_path),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.warning("No pude asegurar audio AAC en el video: %s", exc)
        return source_path

    if target_path.exists():
        try:
            if target_path != source_path:
                source_path.unlink(missing_ok=True)
        except Exception:
            pass
        return target_path
    return source_path


def _download_video_candidate(video_id: str, candidate: dict):
    output_template = str(TEMP_DIR / f"{video_id}-%(title).80s.%(ext)s")
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "format": candidate["format"],
        "outtmpl": output_template,
        "restrictfilenames": True,
        "merge_output_format": "mp4",
        "logger": _SilentYTDLPLogger(),
    }
    _apply_ffmpeg_location(options)
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(_youtube_watch_url(video_id), download=True)
        prepared_path = ydl.prepare_filename(info)

    path = _existing_downloaded_path(prepared_path)
    if not path:
        return {"error": "No pude descargar el video seleccionado."}
    path = _ensure_video_has_aac_audio(path)

    size_bytes = path.stat().st_size
    title = info.get("title") or "Video de YouTube"
    uploader = info.get("uploader") or info.get("channel") or "Canal desconocido"
    resolution = candidate.get("height") or info.get("height") or "unknown"
    return {
        "type": "local_video",
        "path": str(path),
        "title": title,
        "caption": f"{title}\nCanal: {uploader}",
        "url": _youtube_watch_url(video_id),
        "resolution": resolution,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "send_as": "video" if size_bytes <= TELEGRAM_VIDEO_LIMIT_BYTES else "document",
        "audio_codec": "aac" if candidate.get("audio_ext") == "m4a" or _has_ffmpeg() else "unknown",
        "compat_version": VIDEO_COMPAT_VERSION,
        "used_ffmpeg": _has_ffmpeg(),
    }


def _drop_video_cache(video_id: str, cached_path: Path = None):
    with _cache_lock:
        _download_cache.pop(_download_cache_key(video_id, "video"), None)
    try:
        _manifest_path(video_id, "video").unlink(missing_ok=True)
    except Exception:
        pass
    if cached_path and cached_path.exists():
        try:
            cached_path.unlink(missing_ok=True)
        except Exception:
            pass


def download_youtube_video(video_id: str):
    cleanup_temp_videos()
    _ensure_temp_dir()
    logger.info("ffmpeg disponible para YouTube: %s", _ffmpeg_path() or "no")

    clean_video_id, error = _resolve_video_id(video_id)
    if error:
        return {"error": error}

    cached = _get_cached_download(clean_video_id, "video")
    if cached:
        cached_path = Path(cached.get("path", ""))
        cached_size = cached_path.stat().st_size if cached_path.exists() else 0
        if (
            cached.get("compat_version") != VIDEO_COMPAT_VERSION
            or cached.get("audio_codec") != "aac"
            or cached_size > TELEGRAM_DOCUMENT_LIMIT_BYTES
            or (_has_ffmpeg() and not cached.get("used_ffmpeg"))
        ):
            _drop_video_cache(clean_video_id, cached_path)
            cached = None
        elif cached_path.exists() and _has_ffmpeg():
            converted_path = _ensure_video_has_aac_audio(cached_path)
            if converted_path != cached_path:
                cached["path"] = str(converted_path)
                cached["size_mb"] = round(converted_path.stat().st_size / (1024 * 1024), 2)
                cached["send_as"] = "video" if converted_path.stat().st_size <= TELEGRAM_VIDEO_LIMIT_BYTES else "document"
                cached["audio_codec"] = "aac"
                cached["compat_version"] = VIDEO_COMPAT_VERSION
                cached["used_ffmpeg"] = True
                _set_cached_download(clean_video_id, "video", cached)
            return cached
    if cached:
        return cached

    try:
        info = _probe_youtube_info(clean_video_id)
    except Exception as exc:
        logger.warning("No pude leer formatos de YouTube: %s", exc)
        return {"error": "No pude leer las calidades disponibles de ese video."}

    candidates = _build_video_candidates(info, TELEGRAM_DOWNLOAD_TARGET_BYTES)
    if not candidates:
        return {"error": "No encontre una calidad de video que entre en el limite de Telegram."}

    last_error = None
    for candidate in candidates:
        try:
            result = _download_video_candidate(clean_video_id, candidate)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Fallo descargando candidato %s: %s", candidate.get("format"), exc)
            continue
        if result.get("error"):
            last_error = result["error"]
            continue

        path = Path(result["path"])
        size_bytes = path.stat().st_size
        if size_bytes <= TELEGRAM_DOCUMENT_LIMIT_BYTES:
            _set_cached_download(clean_video_id, "video", result)
            return result

        logger.info(
            "Descarga descartada por tamano: %.2f MB a %sp",
            size_bytes / (1024 * 1024),
            candidate.get("height"),
        )
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    return {"error": last_error or "No se pudo descargar un video que quepa en Telegram."}


def download_youtube_audio(video_id: str):
    cleanup_temp_videos()
    _ensure_temp_dir()

    clean_video_id = _extract_video_id(video_id)
    if not clean_video_id:
        return {"error": "No pude identificar el audio de YouTube."}

    cached = _get_cached_download(clean_video_id, "audio")
    if cached:
        cached_path = Path(cached.get("path", ""))
        if cached_path.suffix.lower() in {".opus", ".webm"}:
            converted_path = _convert_audio_to_mp3(cached_path)
            if converted_path:
                cached["path"] = str(converted_path)
                cached["needs_ffmpeg"] = False
                cached["size_mb"] = round(converted_path.stat().st_size / (1024 * 1024), 2)
                _set_cached_download(clean_video_id, "audio", cached)
                return cached
        if cached_path.suffix.lower() in {".mp3", ".m4a"}:
            return cached
        with _cache_lock:
            _download_cache.pop(_download_cache_key(clean_video_id, "audio"), None)

    output_template = str(TEMP_DIR / f"{clean_video_id}-%(title).80s.%(ext)s")
    source_url = _youtube_watch_url(clean_video_id)
    has_ffmpeg = _has_ffmpeg()
    audio_format = "bestaudio[ext=m4a]/bestaudio" if has_ffmpeg else "bestaudio[ext=m4a]"
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "format": audio_format,
        "outtmpl": output_template,
        "restrictfilenames": True,
        "logger": _SilentYTDLPLogger(),
    }
    if has_ffmpeg:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    _apply_ffmpeg_location(options)

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    path = Path(downloaded_path)
    final_path = path.with_suffix(".mp3") if has_ffmpeg and path.with_suffix(".mp3").exists() else _existing_downloaded_path(str(path))
    if not final_path:
        return {"error": "No pude descargar el audio seleccionado."}
    if final_path.suffix.lower() in {".opus", ".webm"}:
        converted_path = _convert_audio_to_mp3(final_path)
        if not converted_path:
            return {"error": "El audio vino en Opus/WebM y no pude convertirlo a MP3. Instala ffmpeg para hacerlo compatible."}
        final_path = converted_path

    size_bytes = final_path.stat().st_size
    if size_bytes > TELEGRAM_DOCUMENT_LIMIT_BYTES:
        return {"error": "El audio supera el limite de 50 MB de Telegram."}

    title = info.get("title") or "Audio de YouTube"
    uploader = info.get("uploader") or info.get("channel") or "Canal desconocido"
    result = {
        "type": "local_audio",
        "path": str(final_path),
        "title": title,
        "performer": uploader,
        "caption": f"{title}\nCanal: {uploader}",
        "duration": info.get("duration"),
        "url": source_url,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "needs_ffmpeg": not has_ffmpeg,
    }
    _set_cached_download(clean_video_id, "audio", result)
    return result


def download_best_youtube_audio(query: str, max_results: int = 4):
    top_result, error = find_best_youtube_match(query, max_results=max_results, mode="music")
    if error:
        return {"error": error}

    downloaded = download_youtube_audio(top_result["video_id"])
    if downloaded.get("error"):
        return downloaded

    downloaded["source_url"] = top_result.get("url")
    downloaded["thumbnail"] = top_result.get("thumbnail")
    downloaded["query"] = query
    return downloaded
