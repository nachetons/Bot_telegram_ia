import hashlib
import json
import logging
import re
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("manga_tool")

# Cache for API responses (TTL: 5 minutes)
_cache_lock = threading.Lock()
_api_cache: Dict[str, tuple] = {}
CACHE_TTL = 300  # 5 minutes


def _cache_get(key: str) -> Optional[dict]:
    """Get from cache if not expired."""
    with _cache_lock:
        if key in _api_cache:
            data, timestamp = _api_cache[key]
            if time.time() - timestamp < CACHE_TTL:
                return data
            else:
                del _api_cache[key]
    return None


def _cache_set(key: str, data: dict):
    """Store in cache with current timestamp."""
    with _cache_lock:
        _api_cache[key] = (data, time.time())


def _cache_clear():
    """Clear all cached data."""
    with _cache_lock:
        _api_cache.clear()

MANGA_TYPES = {
    "manhwa": "Manhwa",
    "manga": "Manga",
    "manhua": "Manhua",
    "doujinshi": "Doujinshi",
    "novela": "Novela",
    "one_shot": "One Shot",
}

DATA_DIR = Path("data/manga")
USER_FILE = DATA_DIR / "user_manga.json"
CALLBACK_FILE = DATA_DIR / "callbacks.json"


def _ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    _ensure_storage()
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return default


def _write_json(path: Path, payload):
    _ensure_storage()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_user_data(chat_id: str) -> dict:
    all_data = _read_json(USER_FILE, {})
    payload = all_data.get(str(chat_id)) or {}
    payload.setdefault("history", [])
    payload.setdefault("favorites", {})
    payload.setdefault("downloads", [])
    return payload


def _save_user_data(chat_id: str, data: dict):
    all_data = _read_json(USER_FILE, {})
    all_data[str(chat_id)] = data
    _write_json(USER_FILE, all_data)


def _callback_store():
    return _read_json(CALLBACK_FILE, {})


def _save_callback_store(store: dict):
    cutoff = int(time.time()) - 7 * 24 * 3600
    cleaned = {
        key: item
        for key, item in store.items()
        if int(item.get("saved_at", 0)) >= cutoff
    }
    _write_json(CALLBACK_FILE, cleaned)


def _register_callback(kind: str, url: str, title: str = "") -> str:
    value = f"{kind}:{url}"
    token = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    store = _callback_store()
    store[token] = {
        "kind": kind,
        "url": url,
        "title": title,
        "saved_at": int(time.time()),
    }
    _save_callback_store(store)
    return token


def _register_menu_callback(menu: dict) -> str:

    seed = json.dumps(menu, ensure_ascii=False, sort_keys=True) + str(time.time())
    token = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    _store_menu_callback(token, menu)
    return token


def _store_menu_callback(token: str, menu: dict):
    store = _callback_store()
    store[token] = {
        "kind": "menu",
        "menu": menu,
        "saved_at": int(time.time()),
    }
    _save_callback_store(store)


def _resolve_callback(value: str, expected_kind: str = "") -> Optional[str]:
    """Resuelve un callback token a su URL original."""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    
    item = _callback_store().get(value) or {}
    if isinstance(item, dict):
        if expected_kind and item.get("kind") and item.get("kind") != expected_kind:
            return None
        return item.get("url")
    return None


def _split_callback_ref(value: str) -> tuple[str, str]:
    if value.startswith("http://") or value.startswith("https://"):
        return value, ""
    parts = (value or "").split(":", 1)
    item_ref = parts[0]
    back_ref = parts[1] if len(parts) > 1 else ""
    return item_ref, back_ref


def manga_resolve_menu(menu_ref: str) -> dict:
    menu = _resolve_callback(menu_ref, "menu")
    if isinstance(menu, dict):
        return menu.get("menu", {})
    # Si es string, es un token de menú guardado
    store = _callback_store()
    item = store.get(menu_ref, {})
    if isinstance(item, dict) and "menu" in item:
        return item["menu"]
    return {"type": "text", "text": "No pude volver a ese menu. Abre /manga de nuevo."}


def _append_back_button(buttons: list, back_ref: str = "", label: str = "Volver"):
    callback_data = f"manga:back:{back_ref}" if back_ref else "manga:back"
    buttons.append([{"text": label, "callback_data": callback_data}])


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _short(value: str, limit: int = 42) -> str:
    value = _clean_text(value)
    return value if len(value) <= limit else value[: max(0, limit - 1)] + "..."


def _get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }


def _item_to_manga(item: dict, fallback_type: str = "") -> Optional[dict]:
    title = item.get("the_real_name") or item.get("name_esp") or item.get("_name")
    slug_id = item.get("_id") or item.get("real_id")
    if not title or not slug_id:
        return None

    manga_type = item.get("_tipo") or fallback_type or "manhwa"
    return {
        "title": title,
        "url": "",  # Server-specific URL builder should set this
        "image": item.get("_imagen"),
        "type": manga_type,
        "status": item.get("_status"),
        "chapters_count": item.get("_numero_cap") or item.get("numero_cap_esp"),
    }


def _results_menu(title: str, results: List[dict], empty_text: str, back_ref: str = "", page: int = 0, per_page: int = 10) -> dict:
    if not results:
        return {"type": "text", "text": empty_text}

    total_pages = max(1, (len(results) + per_page - 1) // per_page)
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(results))
    page_results = results[start_idx:end_idx]

    lines = [title]
    if total_pages > 1:
        lines.append(f"\n📄 Pagina {page + 1}/{total_pages}")
    
    lines.append("")
    
    buttons = []
    gallery_images = []
    
    for local_idx, manga in enumerate(page_results, start=1):
        global_idx = start_idx + local_idx
        manga_title = manga.get("title", "Sin titulo")
        manga_url = manga.get("url", "")
        manga_type = (manga.get("type") or "manga").capitalize()
        chapters = manga.get("chapters_count")
        status = manga.get("status")
        
        # Status emoji
        status_emoji = _get_status_emoji(status) if status else ""
        
        # Build display line
        suffix_parts = [f"({manga_type})"]
        if chapters:
            suffix_parts.append(f"{chapters} caps")
        if status_emoji:
            suffix_parts.insert(0, status_emoji)
        
        suffix = " ".join(suffix_parts)
        display_text = f"{global_idx}. {_short(manga_title, 50)} {suffix}"
        lines.append(display_text)

        # Collect cover image for gallery - accept any valid HTTP URL
        manga_image = manga.get("image", "") or ""
        if manga_image and ("http" in manga_image or "https" in manga_image):
            gallery_images.append(manga_image)

        read_id = _register_callback("manga", manga_url, manga_title)
        buttons.append(
            [
                {"text": f"📖 Ver {global_idx}", "callback_data": f"read:{read_id}"},
                {"text": "⭐ Fav", "callback_data": f"fav:{read_id}"},
            ]
        )

    # Pagination buttons
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append({"text": "⬅️ Anterior", "callback_data": f"manga:page:{back_ref}:{page - 1}"})
        if end_idx < len(results):
            nav_buttons.append({"text": "Siguiente ➡️", "callback_data": f"manga:page:{back_ref}:{page + 1}"})
        if nav_buttons:
            buttons.append(nav_buttons)

    _append_back_button(buttons, back_ref)
    
    menu = {
        "type": "menu",
        "text": "\n".join(lines)[:4096],
        "buttons": buttons,
        "results": results,
        "image": gallery_images[0] if gallery_images else None,  # First cover for backward compat
        "images": gallery_images,  # All covers for gallery mode
        "total_pages": total_pages,
        "current_page": page,
    }
    return menu


def _get_status_emoji(status: str) -> str:
    """Get emoji for manga status."""
    status_lower = (status or "").lower()
    if "complet" in status_lower:
        return "✅"
    elif "publicandose" in status_lower or "ongoing" in status_lower:
        return "🔄"
    elif "pausado" in status_lower or "hiatus" in status_lower:
        return "⏸️"
    elif "cancel" in status_lower:
        return "❌"
    return "📖"


def _compact_results_menu(title: str, results: List[dict], empty_text: str, back_ref: str = "", page: int = 0, per_page: int = 12) -> dict:
    """Catalog-style listing with cover images - gallery feel.
    
    Shows manga covers as photos with compact captions and inline keyboard.
    Returns all cover images for gallery mode (album + separate buttons message).
    """
    if not results:
        return {"type": "text", "text": empty_text}

    total_pages = max(1, (len(results) + per_page - 1) // per_page)
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(results))
    page_results = results[start_idx:end_idx]

    # Collect ALL cover images for this page (gallery mode) - accept any valid image URL
    gallery_images = []
    for manga in page_results:
        img = manga.get("image", "") or ""
        if img and ("http" in img or "https" in img):
            gallery_images.append(img)
    
    lines = [title, ""]
    
    if total_pages > 1:
        lines.append(f"📄 Pagina {page + 1}/{total_pages}")
        lines.append("")
    
    buttons = []
    
    for local_idx, manga in enumerate(page_results):
        global_idx = start_idx + local_idx + 1
        manga_title = _short(manga.get("title", "Sin titulo"), 35)
        manga_url = manga.get("url", "")
        manga_type = (manga.get("type") or "manga").capitalize()
        chapters = manga.get("chapters_count")
        status = manga.get("status")
        
        # Status emoji
        status_emoji = _get_status_emoji(status) if status else ""
        
        # Compact card: [Status] Title (Type | Caps)
        meta_parts = []
        if chapters:
            meta_parts.append(f"{chapters} caps")
        meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
        
        header = f"{status_emoji}{global_idx}. {manga_title}" if status_emoji else f"{global_idx}. {manga_title}"
        lines.append(header)
        if meta_str:
            lines.append(f"   📚 {manga_type}{meta_str}")

        read_id = _register_callback("manga", manga_url, manga_title)
        buttons.append(
            [{"text": f"📖 Ver {global_idx}", "callback_data": f"read:{read_id}"}]
        )

    # Pagination buttons
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append({"text": "⬅️ Anterior", "callback_data": f"manga:page:{back_ref}:{page - 1}"})
        if end_idx < len(results):
            nav_buttons.append({"text": "Siguiente ➡️", "callback_data": f"manga:page:{back_ref}:{page + 1}"})
        if nav_buttons:
            buttons.insert(0, nav_buttons)

    _append_back_button(buttons, back_ref)
    
    menu = {
        "type": "menu",
        "text": "\n".join(lines)[:4096],
        "buttons": buttons,
        "results": results,
        "image": gallery_images[0] if gallery_images else None,  # First cover for backward compat
        "images": gallery_images,  # All covers for gallery mode
        "total_pages": total_pages,
        "current_page": page,
    }
    return menu
