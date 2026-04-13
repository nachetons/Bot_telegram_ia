import json
import shutil
import threading
import time
from pathlib import Path

from yt_dlp import YoutubeDL

from app.config import YOUTUBE_MAX_HEIGHT


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
        return {"error": "¿Qué vídeo quieres buscar en YouTube?"}

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
                "title": entry.get("title") or "Sin título",
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
        return {"error": "No encontré vídeos en YouTube para esa búsqueda."}

    top = items[0]
    lines = [f"Resultados de YouTube para: {cleaned_query}"]
    buttons = []

    for index, item in enumerate(items[:5], start=1):
        lines.append(f"{index}. {item['title']} - {item['channel']}")
        buttons.append(
            [
                {"text": f"📥 TG {index}", "callback_data": f"youtube_play:{item['video_id']}"},
                {"text": f"🔗 {index}", "url": item["url"]},
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
        return None, "No encontré un resultado válido."

    return top_result, None


def download_youtube_video(video_id: str):
    cleanup_temp_videos()
    _ensure_temp_dir()

    clean_video_id = (video_id or "").strip()
    if not clean_video_id:
        return {"error": "No pude identificar el vídeo de YouTube."}

    cached = _get_cached_download(clean_video_id, "video")
    if cached:
        return cached

    output_template = str(TEMP_DIR / f"{clean_video_id}-%(title).80s.%(ext)s")
    source_url = _youtube_watch_url(clean_video_id)
    preferred_height = int(YOUTUBE_MAX_HEIGHT or 1080)
    height_filter = f"[height<={preferred_height}]" if preferred_height > 0 else ""

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
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    path = Path(downloaded_path)
    if not path.exists():
        alt_path = path.with_suffix(".mp4")
        if alt_path.exists():
            path = alt_path
        else:
            return {"error": "No pude descargar el vídeo seleccionado."}

    title = info.get("title") or "Vídeo de YouTube"
    uploader = info.get("uploader") or info.get("channel") or "Canal desconocido"

    result = {
        "type": "local_video",
        "path": str(path),
        "title": title,
        "caption": f"{title}\nCanal: {uploader}",
        "url": source_url,
    }
    _set_cached_download(clean_video_id, "video", result)
    return result


def download_youtube_audio(video_id: str):
    cleanup_temp_videos()
    _ensure_temp_dir()

    clean_video_id = (video_id or "").strip()
    if not clean_video_id:
        return {"error": "No pude identificar el audio de YouTube."}

    cached = _get_cached_download(clean_video_id, "audio")
    if cached:
        return cached

    output_template = str(TEMP_DIR / f"{clean_video_id}-%(title).80s.%(ext)s")
    source_url = _youtube_watch_url(clean_video_id)
    has_ffmpeg = bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": output_template,
        "restrictfilenames": True,
        "logger": _SilentYTDLPLogger(),
    }

    if has_ffmpeg:
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    path = Path(downloaded_path)
    mp3_path = path.with_suffix(".mp3")
    final_path = mp3_path if has_ffmpeg and mp3_path.exists() else path

    if not final_path.exists():
        return {"error": "No pude descargar el audio seleccionado."}

    title = info.get("title") or "Audio de YouTube"
    uploader = info.get("uploader") or info.get("channel") or "Canal desconocido"
    duration = info.get("duration")

    result = {
        "type": "local_audio",
        "path": str(final_path),
        "title": title,
        "performer": uploader,
        "caption": f"{title}\nCanal: {uploader}",
        "duration": duration,
        "url": source_url,
        "needs_ffmpeg": not has_ffmpeg,
    }
    _set_cached_download(clean_video_id, "audio", result)
    return result


def download_best_youtube_video(query: str, max_results: int = 4):
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
