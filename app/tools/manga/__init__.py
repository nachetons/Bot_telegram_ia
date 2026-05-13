"""
Manga tool - Multi-server manga browsing and downloading for Telegram bot.

Usage:
    from app.tools.manga import manga_search, manga_menu, ...
    
Servers:
    - manhwaweb: Manhwaweb.com scraping (default)
    - mangadex: MangaDex.org API (no API key required)
"""

import logging
import re
import requests
from datetime import datetime

logger = logging.getLogger("manga_tool")

from app.tools.manga import base, servers

# Re-export shared utilities (for internal use by other modules)
from app.tools.manga.base import (
    MANGA_TYPES,
    CACHE_TTL,
    MAX_DESCRIPTION_LENGTH,
    MAX_MENU_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    RESULTS_PER_PAGE,
    IMAGES_PER_PAGE,
    CHAPTERS_TO_SHOW_INITIAL,
    _cache_get,
    _cache_set,
    _cache_clear,
    _load_user_data,
    _save_user_data,
    _register_callback,
    _register_menu_callback,
    _store_menu_callback,
    _resolve_callback,
    _split_callback_ref,
    manga_resolve_menu,
    _append_back_button,
    _clean_text,
    _short,
    _get_headers,
    _results_menu,
    _compact_results_menu,
    _get_status_emoji,
)

# Server-specific functions (used by public API below)
_manhwaweb = servers.manhwaweb
_mangadex = servers.mangadex
_vermanhwa = servers.vermanhwa


def manga_search(query: str, manga_type: str = "manhwa") -> dict:
    try:
        return {
            "results": _manhwaweb._library_request(query, manga_type, limit=20),
            "query": query,
            "type": manga_type,
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("Manga search error for %s: %s", query, exc)
        return {"results": [], "query": query, "type": manga_type, "error": str(exc)}


def _search_manga(query: str, manga_type: str = "manhwa", limit: int = 20) -> dict:
    try:
        return {
            "results": _manhwaweb._library_request(query, manga_type, limit=limit),
            "query": query,
            "type": manga_type,
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("Manga search error for %s: %s", query, exc)
        return {"results": [], "query": query, "type": manga_type, "error": str(exc)}


def mangadex_search(query: str, limit: int = 20) -> dict:
    """Busca mangas en MangaDex."""
    try:
        if query.strip():
            results = _mangadex._search_manga(query, limit=limit)
        else:
            results = []
        return {
            "results": results,
            "query": query,
            "type": "mangadex",
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("MangaDex search error for %s: %s", query, exc)
        return {"results": [], "query": query, "type": "mangadex", "error": str(exc)}


def mangadex_top(limit: int = 20) -> dict:
    """Obtiene los mangas mas populares de MangaDex."""
    try:
        results = _mangadex._get_popular_manga(limit=limit)
        return {
            "results": results,
            "query": "",
            "type": "mangadex_top",
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("MangaDex top error: %s", exc)
        return {"results": [], "query": "", "type": "mangadex_top", "error": str(exc)}


def mangadex_recent(limit: int = 20) -> dict:
    """Obtiene los mangas mas recientes de MangaDex."""
    try:
        results = _mangadex._get_recent_manga(limit=limit)
        return {
            "results": results,
            "query": "",
            "type": "mangadex_recent",
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("MangaDex recent error: %s", exc)
        return {"results": [], "query": "", "type": "mangadex_recent", "error": str(exc)}


def mangadex_read_details(manga_ref: str, chat_id: str = "") -> dict:
    """Muestra detalles de un manga desde MangaDex."""
    
    # Acepta URL completa: "mangadex:manga:{id}" o token con back_ref
    manga_id_raw, back_ref = _split_callback_ref(manga_ref)
    resolved_manga = _resolve_callback(manga_id_raw, "manga") or manga_id_raw
    
    if not isinstance(resolved_manga, str) or not resolved_manga.startswith("mangadex:manga:"):
        return {"type": "text", "text": "No pude cargar ese manga desde MangaDex."}
    
    parts = resolved_manga.split(":")
    manga_id = parts[2] if len(parts) > 2 else ""
    
    details = _mangadex._get_manga_by_url(resolved_manga)
    if not details:
        return {"type": "text", "text": "No pude cargar ese manga desde MangaDex."}

    if chat_id:
        manga_add_history(chat_id, details["title"], resolved_manga)

    status = details.get("status") or ""
    status_emoji = _get_status_emoji(status)
    
    title = details.get("title", "Sin titulo")
    description = (details.get("description") or "")[:MAX_DESCRIPTION_LENGTH]
    authors = ", ".join(details.get("authors") or []) or "Desconocido"
    categories = details.get("categories", [])
    chapters_list = details.get("chapters", [])
    chapters_count = len(chapters_list)
    
    lines = [
        f"\U0001f310 {title}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "",
        f"{status_emoji} {status.capitalize() if status else 'Desconocido'}",
        f"\U0001f4da Tipo: {(details.get('type') or 'manga').capitalize()}",
        f"\u270d\ufe0f Autores: {authors}",
    ]
    
    if categories:
        lines.append(f"\U0001f3f7\ufe0f Generos: {', '.join(categories[:5])}")
    
    lines.extend(["", f"\U0001f4d6 Capitulos: {chapters_count}"])
    
    if description:
        lines.extend([
            "",
            "\U0001f4dd Sinopsis:",
            f"{description}...",
        ])

    buttons = []
    manga_id_token = _register_callback("manga", resolved_manga, title)
    detail_menu = {
        "type": "menu",
        "text": "\n".join(lines)[:MAX_MENU_TEXT_LENGTH],
        "buttons": buttons,
        "image": details.get("image"),
        "_is_manga": True,
    }
    detail_ref = _register_menu_callback(detail_menu)
    
    # Quick actions for latest chapter
    if chapters_list:
        latest_chap = chapters_list[0]
        chap_token = _register_callback("chapter", latest_chap.get("url", ""), "Ultimo cap")
        buttons.append([{"text": "\U0001f4d6 Leer ultimo cap", "callback_data": f"manga:chapter:{chap_token}:{detail_ref}"}])
        
        # Download options for latest chapter
        buttons.append([
            {"text": "\U0001f4e5 ZIP ultimo cap", "callback_data": f"manga:download_chap:{chap_token}"},
            {"text": "\U0001f4c4 PDF ultimo cap", "callback_data": f"pdf_chap:{chap_token}"},
        ])

    # Chapter list (first 15)
    chapters_to_show = chapters_list[:CHAPTERS_TO_SHOW_INITIAL]
    has_more_chapters = len(chapters_list) > CHAPTERS_TO_SHOW_INITIAL
    
    for chapter in chapters_to_show:
        chap_title = _short(chapter.get("title", f"Capitulo {chapter.get('number', '?')}"), MAX_TITLE_LENGTH)
        chapter_id = _register_callback("chapter", chapter.get("url", ""), chapter.get("title", "Capitulo"))
        buttons.append([{"text": f"\U0001f4d6 {chap_title}", "callback_data": f"manga:chapter:{chapter_id}:{detail_ref}"}])
    
    if has_more_chapters:
        remaining = len(chapters_list) - CHAPTERS_TO_SHOW_INITIAL
        buttons.append([{"text": f"Ver {remaining} caps mas...", "callback_data": f"manga:more_chaps:{manga_id_token}:{detail_ref}"}])

    buttons.extend([
        [
            {"text": "\u2b50 Favorito", "callback_data": f"manga:fav:{manga_id_token}"},
            {"text": "\U0001f310 Abrir en MangaDex", "url": f"https://mangadex.org/title/{parts[2]}"},
        ],
    ])
    
    _append_back_button(buttons, back_ref)
    
    _store_menu_callback(detail_ref, detail_menu)
    return detail_menu


def mangadex_view_chapter(chat_id: str, chapter_url: str, page: int = 0) -> dict:
    """Visualiza un capitulo de MangaDex con imagenes en Telegram."""
    images = _mangadex._get_chapter_images(chapter_url)
    
    if not images:
        return {"error": "Sin imagenes para este capitulo en MangaDex"}
    
    total_pages = (len(images) + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE
    
    if page >= total_pages:
        page = total_pages - 1
        
    start_idx = page * IMAGES_PER_PAGE
    end_idx = min(start_idx + IMAGES_PER_PAGE, len(images))
    current_images = images[start_idx:end_idx]
    
    lines = [
        f"📖 Capitulo {page + 1} de {total_pages}",
        "",
        f"📄 Pagina {start_idx + 1}-{end_idx} de {len(images)}",
    ]
    
    buttons = []
    
    chap_token = _register_callback("chapter", chapter_url)
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append({"text": "⬅️ Anterior", "callback_data": f"mangadex:view:{chap_token}:{page - 1}"})
    if end_idx < len(images):
        nav_buttons.append({"text": "Siguiente ➡️", "callback_data": f"mangadex:view:{chap_token}:{page + 1}"})
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Image links (max 8 per screen)
    for idx, img_url in enumerate(current_images[:8], start=start_idx + 1):
        buttons.append([{"text": f"🖼️ Pag {idx}", "url": img_url}])
    
    if len(current_images) > 8:
        remaining = len(current_images) - 8
        buttons.append([{"text": f"... y {remaining} mas", "url": current_images[8]}])
    
    # Download options
    buttons.extend([
        [
            {"text": "📥 ZIP cap.", "callback_data": f"manga:download_chap:{chap_token}"},
            {"text": "📄 PDF cap.", "callback_data": f"pdf_chap:{chap_token}"},
        ],
        [{"text": "⬅️ Volver", "callback_data": "manga:back"}],
    ])
    
    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
        "images": current_images[:3],
        "page": page,
        "total_pages": total_pages,
    }


def mangadex_read_chapter(chapter_ref: str, chat_id: str = "") -> dict:
    """Muestra opciones para un capitulo de MangaDex."""
    
    # Acepta URL completa: "mangadex:chapter:{chap_id}:{manga_id}"
    chapter_id_raw, back_ref = _split_callback_ref(chapter_ref)
    resolved_chapter = _resolve_callback(chapter_id_raw, "chapter") or chapter_id_raw
    if not isinstance(resolved_chapter, str) or not resolved_chapter.startswith("mangadex:chapter:"):
        return {"type": "text", "text": "No pude cargar ese capitulo desde MangaDex."}

    parts = resolved_chapter.split(":")
    chapter_id = parts[2] if len(parts) > 2 else ""
    
    images = _mangadex._get_chapter_images(resolved_chapter)

    chap_token = _register_callback("chapter", resolved_chapter)
    
    mangadex_chap_url = f"https://mangadex.org/chapter/{chapter_id}"
    buttons = [[{"text": "🌐 Abrir en MangaDex", "url": mangadex_chap_url}]]
    
    # Show first 5 pages as quick links
    for index, image_url in enumerate(images[:5], start=1):
        buttons.append([{"text": f"🖼️ Pag {index}", "url": image_url}])
    
    if len(images) > 5:
        remaining = len(images) - 5
        buttons.append([{"text": f"... ver {remaining} paginas mas", "callback_data": f"mangadex:view:{chap_token}:0"}])
    
    # Download options
    if images:
        buttons.extend([
            [
                {"text": "📥 Descargar ZIP", "callback_data": f"manga:download_chap:{chap_token}"},
                {"text": "📄 Exportar PDF", "callback_data": f"pdf_chap:{chap_token}"},
            ],
        ])
    
    _append_back_button(buttons, back_ref)

    text = f"📖 Capitulo (MangaDex)\n📄 {len(images)} paginas detectadas"
    if not images:
        text += "\n\n⚠️ No pude extraer paginas de MangaDex, pero puedes abrirlo en la web."
    
    return {"type": "menu", "text": text, "buttons": buttons, "images": images[:3], "image": images[0] if images else None, "_is_manga": True}


def mangadex_menu() -> dict:
    back_ref = _register_menu_callback(manga_menu(""))
    return {
        "type": "menu",
        "text": "\U0001f310 MANGADEX\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nCatalogo global con portadas, lectura por paginas y apertura web.",
        "buttons": [
            [{"text": "\U0001f50d Buscar manga", "callback_data": "manga:mangadex_search"}],
            [{"text": "\U0001f525 Populares", "callback_data": "manga:mangadex_top_popular"}],
            [{"text": "\u2728 Ultimos agregados", "callback_data": "manga:mangadex_recent"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
        "_is_manga": True,
    }


def mangadex_search_menu() -> dict:
    back_ref = _register_menu_callback(mangadex_menu())
    return {
        "type": "menu",
        "text": "\U0001f50d MANGADEX - BUSQUEDA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nEscribe el nombre del manga que buscas.",
        "buttons": [[{"text": "Cancelar", "callback_data": f"manga:back:{back_ref}"}]],
        "_is_manga": True,
    }


def mangadex_top_menu() -> dict:
    back_ref = _register_menu_callback(mangadex_menu())
    return {
        "type": "menu",
        "text": "\U0001f3c6 MANGADEX - LISTADOS\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige el listado que quieres abrir.",
        "buttons": [
            [{"text": "\U0001f525 Popularidad", "callback_data": "manga:mangadex_top_popular"}],
            [{"text": "\u2728 Ultimos agregados", "callback_data": "manga:mangadex_recent"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
        "_is_manga": True,
    }


def mangadex_auto_search(chat_id: str, query: str) -> dict:
    """Busca en ambos servidores (Manhwaweb + MangaDex)."""
    query = _clean_text(query)
    if not query:
        return {"type": "text", "text": "Escribe el nombre del manga que quieres buscar."}

    results = []
    seen = set()
    
    # Buscar en Manhwaweb
    found_mw = _search_manga(query, manga_type="manhwa", limit=5).get("results", [])
    for manga in found_mw:
        if manga["url"] not in seen:
            seen.add(manga["url"])
            results.append(manga)
    
    # Buscar en MangaDex
    found_md = mangadex_search(query, limit=5).get("results", [])
    for manga in found_md:
        if manga.get("_mangadx_id") and f"mangadex:{manga['_mangadx_id']}" not in seen:
            seen.add(f"mangadex:{manga['_mangadx_id']}")
            results.append(manga)

    return _results_menu(
        f"Resultados para: {query}",
        results,
        f"No encontre mangas para '{query}' en ningun servicio.",
    )


def vermanhwa_search(query: str, limit: int = 20) -> dict:
    """Busca mangas en VerManhwa."""
    try:
        if query.strip():
            results = _vermanhwa._search_manga(query, limit=limit)
        else:
            results = []
        return {
            "results": results,
            "query": query,
            "type": "vermanhwa",
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("VerManhwa search error for %s: %s", query, exc)
        return {"results": [], "query": query, "type": "vermanhwa", "error": str(exc)}


def vermanhwa_read_details(manga_ref: str, chat_id: str = "") -> dict:
    """Muestra detalles de un manga desde VerManhwa."""
    
    # Acepta URL completa o token con back_ref
    manga_url, back_ref = _split_callback_ref(manga_ref)
    
    if not isinstance(manga_url, str) or not manga_url.startswith("http"):
        return {"type": "text", "text": "No pude cargar ese manga desde VerManhwa."}
    
    details = _vermanhwa._get_manga_by_url(manga_url)
    if not details:
        return {"type": "text", "text": "No pude cargar ese manga desde VerManhwa."}

    if chat_id:
        manga_add_history(chat_id, details["title"], manga_url)

    status = details.get("status") or ""
    status_emoji = _get_status_emoji(status)
    
    title = details.get("title", "Sin titulo")
    description = (details.get("description") or "")[:MAX_DESCRIPTION_LENGTH]
    authors = ", ".join(details.get("authors") or []) or "Desconocido"
    categories = details.get("categories", [])
    chapters_list = details.get("chapters", [])
    chapters_count = len(chapters_list)
    
    lines = [
        f"\U0001f4d6 {title}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "",
        f"{status_emoji} {status.capitalize() if status else 'Desconocido'}",
        f"\U0001f4da Tipo: {(details.get('type') or 'manhwa').capitalize()}",
        f"\u270d\ufe0f Autores: {authors}",
    ]
    
    if categories:
        lines.append(f"\U0001f3f7\ufe0f Generos: {', '.join(categories[:5])}")
    
    lines.extend(["", f"\U0001f4d6 Capitulos: {chapters_count}"])
    
    if description:
        lines.extend([
            "",
            "\U0001f4dd Sinopsis:",
            f"{description}...",
        ])

    buttons = []
    manga_id = _register_callback("manga", details.get("url", manga_url), title)
    detail_menu = {
        "type": "menu",
        "text": "\n".join(lines)[:MAX_MENU_TEXT_LENGTH],
        "buttons": buttons,
        "image": details.get("image"),
    }
    detail_ref = _register_menu_callback(detail_menu)
    
    # Quick actions for latest chapter
    if chapters_list:
        latest_chap = chapters_list[-1]
        chap_token = _register_callback("chapter", latest_chap.get("url", ""), "Ultimo cap")
        buttons.append([{"text": "\U0001f4d6 Leer ultimo cap", "callback_data": f"vermanhwa:chapter:{chap_token}:{detail_ref}"}])
        
        # Download options for latest chapter
        buttons.append([
            {"text": "\U0001f4e5 ZIP ultimo cap", "callback_data": f"manga:download_chap:{chap_token}"},
            {"text": "\U0001f4c4 PDF ultimo cap", "callback_data": f"pdf_chap:{chap_token}"},
        ])

    # Chapter list (first 15)
    chapters_to_show = chapters_list[:CHAPTERS_TO_SHOW_INITIAL]
    has_more_chapters = len(chapters_list) > CHAPTERS_TO_SHOW_INITIAL
    
    for chapter in chapters_to_show:
        chap_title = _short(chapter.get("title", f"Capitulo {chapter.get('number', '?')}"), MAX_TITLE_LENGTH)
        chapter_id = _register_callback("chapter", chapter.get("url", ""), chapter.get("title", "Capitulo"))
        buttons.append([{"text": f"\U0001f4d6 {chap_title}", "callback_data": f"vermanhwa:chapter:{chapter_id}:{detail_ref}"}])
    
    if has_more_chapters:
        remaining = len(chapters_list) - CHAPTERS_TO_SHOW_INITIAL
        buttons.append([{"text": f"Ver {remaining} caps mas...", "callback_data": f"vermanhwa:more_chaps:{manga_id}:{detail_ref}"}])

    buttons.extend([
        [
            {"text": "\u2b50 Favorito", "callback_data": f"manga:fav:{manga_id}"},
            {"text": "\U0001f310 Abrir en VerManhwa", "url": details.get("url", manga_url)},
        ],
    ])
    
    _append_back_button(buttons, back_ref)
    
    _store_menu_callback(detail_ref, detail_menu)
    return detail_menu


def vermanhwa_read_chapter(chapter_ref: str, chat_id: str = "") -> dict:
    """Muestra opciones para un capitulo de VerManhwa."""
    
    if not isinstance(chapter_ref, str) or not chapter_ref.startswith("http"):
        return {"type": "text", "text": "No pude cargar ese capitulo desde VerManhwa."}

    images = _vermanhwa._get_chapter_images(chapter_ref)

    chap_token = _register_callback("chapter", chapter_ref)
    
    buttons = [[{"text": "🌐 Abrir en VerManhwa", "url": chapter_ref}]]
    
    # Show first 5 pages as quick links
    for index, image_url in enumerate(images[:5], start=1):
        buttons.append([{"text": f"🖼️ Pag {index}", "url": image_url}])
    
    if len(images) > 5:
        remaining = len(images) - 5
        buttons.append([{"text": f"... ver {remaining} paginas mas", "callback_data": f"vermanhwa:view:{chap_token}:0"}])
    
    # Download options
    if images:
        buttons.extend([
            [
                {"text": "📥 Descargar ZIP", "callback_data": f"manga:download_chap:{chap_token}"},
                {"text": "📄 Exportar PDF", "callback_data": f"pdf_chap:{chap_token}"},
            ],
        ])
    
    buttons.append([{"text": "⬅️ Volver", "callback_data": "manga:back"}])

    text = f"📖 Capitulo (VerManhwa)\n📄 {len(images)} paginas detectadas"
    if not images:
        text += "\n\n⚠️ No pude extraer paginas de VerManhwa, pero puedes abrirlo en la web."
    
    return {"type": "menu", "text": text, "buttons": buttons, "images": images[:3], "image": images[0] if images else None}


def vermanhwa_view_chapter(chat_id: str, chapter_url: str, page: int = 0) -> dict:
    """Visualiza un capitulo de VerManhwa con imagenes en Telegram."""
    images = _vermanhwa._get_chapter_images(chapter_url)
    
    if not images:
        return {"error": "Sin imagenes para este capitulo en VerManhwa"}
    
    total_pages = (len(images) + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE
    
    if page >= total_pages:
        page = total_pages - 1
        
    start_idx = page * IMAGES_PER_PAGE
    end_idx = min(start_idx + IMAGES_PER_PAGE, len(images))
    current_images = images[start_idx:end_idx]
    
    lines = [
        f"📖 Capitulo {page + 1} de {total_pages}",
        "",
        f"📄 Pagina {start_idx + 1}-{end_idx} de {len(images)}",
    ]
    
    buttons = []
    
    chap_token = _register_callback("chapter", chapter_url)
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append({"text": "⬅️ Anterior", "callback_data": f"vermanhwa:view:{chap_token}:{page - 1}"})
    if end_idx < len(images):
        nav_buttons.append({"text": "Siguiente ➡️", "callback_data": f"vermanhwa:view:{chap_token}:{page + 1}"})
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Image links (max 8 per screen)
    for idx, img_url in enumerate(current_images[:8], start=start_idx + 1):
        buttons.append([{"text": f"🖼️ Pag {idx}", "url": img_url}])
    
    if len(current_images) > 8:
        remaining = len(current_images) - 8
        buttons.append([{"text": f"... y {remaining} mas", "url": current_images[8]}])
    
    # Download options
    buttons.extend([
        [
            {"text": "📥 ZIP cap.", "callback_data": f"manga:download_chap:{chap_token}"},
            {"text": "📄 PDF cap.", "callback_data": f"pdf_chap:{chap_token}"},
        ],
        [{"text": "⬅️ Volver", "callback_data": "manga:back"}],
    ])
    
    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
        "images": current_images[:3],
        "page": page,
        "total_pages": total_pages,
    }


def vermanhwa_menu() -> dict:
    """Menu principal de VerManhwa."""
    back_ref = _register_menu_callback(manga_menu(""))
    return {
        "type": "menu",
        "text": "\U0001f4d6 VERMANHWA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nBuscador de manhwas en espanol.",
        "buttons": [
            [{"text": "\u2728 Ultimas actualizaciones", "callback_data": "manga:vermanhwa_latest"}],
            [{"text": "\U0001f3f7\ufe0f Generos", "callback_data": "manga:vermanhwa_genres"}],
            [{"text": "\u2705 Completos", "callback_data": "manga:vermanhwa_completed"}],
            [{"text": "\U0001f50d Buscar", "callback_data": "manga:vermanhwa_search"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def vermanhwa_search_menu() -> dict:
    return {
        "type": "menu",
        "text": "\U0001f50d BUSQUEDA - VERMANHWA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nEscribe el nombre del manga que buscas.",
        "buttons": [[{"text": "Cancelar", "callback_data": "manga:back"}]],
    }


def vermanhwa_latest_menu() -> dict:
    """Menu para ultimas actualizaciones."""
    back_ref = _register_menu_callback(vermanhwa_menu())
    return {
        "type": "menu",
        "text": "\u2728 ULTIMAS ACTUALIZACIONES - VERMANHWA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nCargando...",
        "buttons": [
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def vermanhwa_completed_menu() -> dict:
    """Menu de series completas."""
    back_ref = _register_menu_callback(vermanhwa_menu())
    return {
        "type": "menu",
        "text": "\u2705 SERIES COMPLETAS - VERMANHWA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nCargando...",
        "buttons": [
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def vermanhwa_latest_menu() -> dict:
    """Menu para ultimas actualizaciones."""
    back_ref = _register_menu_callback(vermanhwa_menu())
    return {
        "type": "menu",
        "text": "VERMANHWA - ULTIMAS ACTUALIZACIONES\n\nCargando...",
        "buttons": [
            [{"text": "⬅️ Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def vermanhwa_genres_menu() -> dict:
    """Menu de generos disponibles en VerManhwa."""
    back_ref = _register_menu_callback(vermanhwa_menu())
    return {
        "type": "menu",
        "text": "\U0001f3f7\ufe0f GENEROS - VERMANHWA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nSelecciona un genero.",
        "buttons": [
            [{"text": "\U0001f3ad Drama", "callback_data": "manga:vermanhwa_genre:drama"}, {"text": "\u2764\ufe0f Romance", "callback_data": "manga:vermanhwa_genre:romance"}],
            [{"text": "\U0001f52e Maduro", "callback_data": "manga:vermanhwa_genre:maduro"}, {"text": "\U0001f3e5 Harem", "callback_data": "manga:vermanhwa_genre:harem"}],
            [{"text": "\U0001f3eb Vida escolar", "callback_data": "manga:vermanhwa_genre:vida-escolar"}, {"text": "\U0001f602 Comedia", "callback_data": "manga:vermanhwa_genre:comedia"}],
            [{"text": "\U0001f4ac Cosas de la vida", "callback_data": "manga:vermanhwa_genre:cosas-de-la-vida"}, {"text": "\U0001f47b Supernatural", "callback_data": "manga:vermanhwa_genre:supernatural"}],
            [{"text": "\U0001f525 Smut", "callback_data": "manga:vermanhwa_genre:smut"}, {"text": "\U0001f6ab Sin censura", "callback_data": "manga:vermanhwa_genre:sin-censura"}],
            [{"text": "\U0001f3dd\ufe0f Fantasia", "callback_data": "manga:vermanhwa_genre:fantasia"}, {"text": "\U0001f4a8 Acción", "callback_data": "manga:vermanhwa_genre:accion"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def vermanhwa_completed_menu() -> dict:
    """Menu de series completas."""
    back_ref = _register_menu_callback(vermanhwa_menu())
    return {
        "type": "menu",
        "text": "VERMANHWA - COMPLETOS\n\nCargando...",
        "buttons": [
            [{"text": "⬅️ Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def vermanhwa_fetch_latest(limit: int = 20) -> dict:
    """Obtiene los ultimos mangas actualizados desde la homepage."""
    try:
        response = requests.get(
            _vermanhwa.BASE_URL,
            headers=base._get_headers(),
            timeout=20
        )
        response.raise_for_status()
        
        return _parse_vermanhwa_homepage(response.text, limit)
    except Exception as exc:
        base.logger.error("VerManhwa latest error: %s", exc)
        return {"results": [], "error": str(exc)}


def vermanhwa_fetch_completed(limit: int = 20) -> dict:
    """Obtiene los mangas completos."""
    try:
        response = requests.get(
            f"{_vermanhwa.BASE_URL}/completos/",
            headers=base._get_headers(),
            timeout=20
        )
        response.raise_for_status()
        
        return _parse_vermanhwa_list_page(response.text, limit)
    except Exception as exc:
        base.logger.error("VerManhwa completed error: %s", exc)
        return {"results": [], "error": str(exc)}


def vermanhwa_fetch_by_genre(genre_slug: str, limit: int = 20) -> dict:
    """Obtiene mangas por genero."""
    try:
        response = requests.get(
            f"{_vermanhwa.BASE_URL}/manga-genre/{genre_slug}/",
            headers=base._get_headers(),
            timeout=20
        )
        response.raise_for_status()
        
        return _parse_vermanhwa_list_page(response.text, limit)
    except Exception as exc:
        base.logger.error("VerManhwa genre error (%s): %s", genre_slug, exc)
        return {"results": [], "error": str(exc)}


def _parse_vermanhwa_homepage(html: str, limit: int = 20) -> dict:
    """Parsea la homepage de VerManhwa para obtener ultimos mangas."""
    results = []
    
    # Pattern: h3 > a[href*="/manga/"] con imagen cercana
    manga_links = re.findall(
        r'<h3[^>]*>\s*<a[^>]*href=["\']([^"\']*?/manga/[^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        re.DOTALL | re.IGNORECASE
    )
    
    for manga_url, title_html in manga_links[:limit]:
        title = re.sub(r'<[^>]+>', '', title_html).strip()
        if not title:
            continue
        
        # Buscar imagen en el bloque siguiente (hasta 2000 chars despues del link)
        img_start = html.find(manga_url)
        image = ""
        if img_start >= 0:
            block = html[img_start:img_start + 2000]
            # Preferir data-src (lazy load), fallback a src
            img_match = re.search(r'<img[^>]*data-src=["\']([^"\']+wp-content[^"\']+)["\']', block, re.IGNORECASE)
            if not img_match:
                img_match = re.search(r'<img[^>]*src=["\']([^"\']+wp-content[^"\']+)["\']', block, re.IGNORECASE)
            if img_match:
                image = img_match.group(1)
        
        results.append({
            "title": title,
            "url": manga_url,
            "image": image,
            "type": "manhwa",
            "status": "",
            "chapters_count": 0,
        })
    
    return {"results": results}


def _parse_vermanhwa_list_page(html: str, limit: int = 20) -> dict:
    """Parsea una pagina de listado de VerManhwa (completos, generos, etc)."""
    results = []
    
    # Pattern: h3 > a[href*="/manga/"] con imagen cercana
    manga_links = re.findall(
        r'<h3[^>]*>\s*<a[^>]*href=["\']([^"\']*?/manga/[^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        re.DOTALL | re.IGNORECASE
    )
    
    for manga_url, title_html in manga_links[:limit]:
        title = re.sub(r'<[^>]+>', '', title_html).strip()
        if not title:
            continue
        
        # Buscar imagen en el bloque siguiente (hasta 2000 chars despues del link)
        img_start = html.find(manga_url)
        image = ""
        if img_start >= 0:
            block = html[img_start:img_start + 2000]
            # Preferir data-src (lazy load), fallback a src
            img_match = re.search(r'<img[^>]*data-src=["\']([^"\']+wp-content[^"\']+)["\']', block, re.IGNORECASE)
            if not img_match:
                img_match = re.search(r'<img[^>]*src=["\']([^"\']+wp-content[^"\']+)["\']', block, re.IGNORECASE)
            if img_match:
                image = img_match.group(1)
        
        results.append({
            "title": title,
            "url": manga_url,
            "image": image,
            "type": "manhwa",
            "status": "",
            "chapters_count": 0,
        })
    
    return {"results": results}


def vermanhwa_handle_latest() -> dict:
    """Handler para ultimas actualizaciones."""
    result = vermanhwa_fetch_latest()
    back_ref = _register_menu_callback(vermanhwa_latest_menu())
    return _compact_results_menu(
        "✨ ULTIMAS ACTUALIZACIONES - VERMANHWA",
        result.get("results", []),
        "No encontre mangas actualizados recientemente.",
        back_ref,
    )


def vermanhwa_handle_completed() -> dict:
    """Handler para series completas."""
    result = vermanhwa_fetch_completed()
    back_ref = _register_menu_callback(vermanhwa_completed_menu())
    return _compact_results_menu(
        "✅ SERIES COMPLETAS - VERMANHWA",
        result.get("results", []),
        "No encontre mangas completos.",
        back_ref,
    )


def vermanhwa_handle_genre(genre_slug: str) -> dict:
    """Handler para generos."""
    genre_name = genre_slug.replace("-", " ").title()
    result = vermanhwa_fetch_by_genre(genre_slug)
    back_ref = _register_menu_callback(vermanhwa_genres_menu())
    return _compact_results_menu(
        f"🏷️ {genre_name} - VERMANHWA",
        result.get("results", []),
        f"No encontre mangas para el genero {genre_name}.",
        back_ref,
    )


def vermanhwa_auto_search(chat_id: str, query: str) -> dict:
    """Busca en VerManhwa."""
    query = _clean_text(query)
    if not query:
        return {"type": "text", "text": "Escribe el nombre del manga que quieres buscar."}

    results = []
    seen = set()
    
    # Buscar en VerManhwa
    found_vw = vermanhwa_search(query, limit=10).get("results", [])
    for manga in found_vw:
        if manga["url"] not in seen:
            seen.add(manga["url"])
            results.append(manga)

    return _results_menu(
        f"Resultados para: {query}",
        results,
        f"No encontre mangas para '{query}' en VerManhwa.",
    )


def manga_search(query: str, manga_type: str = "manhwa") -> dict:
    try:
        return {
            "results": _manhwaweb._library_request(query, manga_type, limit=20),
            "query": query,
            "type": manga_type,
        }
    except Exception as exc:
        from app.tools.manga import base
        base.logger.error("Manga search error for %s: %s", query, exc)
        return {"results": [], "query": query, "type": manga_type, "error": str(exc)}


def manga_menu(chat_id: str = "") -> dict:
    payload = _load_user_data(chat_id) if chat_id else {"history": [], "favorites": {}, "downloads": []}
    
    history_count = len(payload.get('history', []))
    fav_count = len(payload.get('favorites', {}))
    download_count = len(payload.get('downloads', []))
    
    text = (
        f"\U0001f4da MANGA AGENT\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\n"
        f"\U0001f4d6 Historial: {history_count}\n"
        f"\u2b50 Favoritos: {fav_count}\n"
        f"\U0001f4e5 Descargas: {download_count}\n"
        "\n"
        f"\U0001f50d 3 servidores disponibles"
    )
    
    return {
        "type": "menu",
        "text": text,
        "buttons": [
            [{"text": "\U0001f50d Buscar manga", "callback_data": "manga:search"}],
            [{"text": "\U0001f4da ManhwaWeb", "callback_data": "manga:manhwaweb"}, {"text": "\U0001f310 MangaDex", "callback_data": "manga:mangadex"}],
            [{"text": "\U0001f4d6 VerManhwa", "callback_data": "manga:vermanhwa"}],
            [{"text": "\u2b50 Favoritos", "callback_data": "manga:favorites"}, {"text": "\U0001f4d6 Historial", "callback_data": "manga:history"}],
        ],
    }


def manga_search_menu() -> dict:
    return {
        "type": "menu",
        "text": "\U0001f50d BUSQUEDA DE MANGA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige donde quieres buscar.",
        "buttons": [
            [{"text": "Auto (todos)", "callback_data": "manga:auto"}],
            [{"text": "\U0001f4da ManhwaWeb", "callback_data": "manga:manhwaweb"}, {"text": "\U0001f310 MangaDex", "callback_data": "manga:mangadex"}],
            [{"text": "\U0001f4d6 VerManhwa", "callback_data": "manga:vermanhwa"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": "manga:back"}],
        ],
    }


def manga_manhwaweb_menu() -> dict:
    return {
        "type": "menu",
        "text": "\U0001f4da MANHWA WEB\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nSelecciona una opcion.",
        "buttons": [
            [{"text": "\U0001f4cb Catalogo", "callback_data": "manga:mw_catalog"}],
            [{"text": "\U0001f50d Buscar manga", "callback_data": "manga:search_query"}],
            [{"text": "\U0001f3c6 Top 10", "callback_data": "manga:mw_top10"}],
            [{"text": "\u2728 Novedades", "callback_data": "manga:mw_new"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": "manga:back"}],
        ],
    }


def manga_manhwaweb_catalog_menu() -> dict:
    """Menu principal del catalogo con filtros disponibles en la web."""
    back_ref = _register_menu_callback(manga_manhwaweb_menu())
    
    return {
        "type": "menu",
        "text": "\U0001f4cb CATALOGO - MANHWA WEB\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige un filtro para refinar.",
        "buttons": [
            [{"text": "\U0001f1f0\U0001f1f1 Manhwa", "callback_data": f"manga:mw_filter:tipo:manhwa:{back_ref}"}, {"text": "\U0001f1ef\U0001f1f5 Manga", "callback_data": f"manga:mw_filter:tipo:manga:{back_ref}"}],
            [{"text": "\U0001f1e8\U0001f1f3 Manhua", "callback_data": f"manga:mw_filter:tipo:manhua:{back_ref}"}, {"text": "\U0001f4d6 Novela", "callback_data": f"manga:mw_filter:tipo:novela:{back_ref}"}],
            [{"text": "\U0001f3a8 Doujinshi", "callback_data": f"manga:mw_filter:tipo:doujinshi:{back_ref}"}, {"text": "\U0001f4c4 One Shot", "callback_data": f"manga:mw_filter:tipo:one_shot:{back_ref}"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def manga_manhwaweb_state_menu() -> dict:
    """Menu para filtrar por estado de publicacion."""
    back_ref = _register_menu_callback(manga_manhwaweb_catalog_menu())
    
    return {
        "type": "menu",
        "text": "\U0001f4ca FILTRO - ESTADO\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige el estado.",
        "buttons": [
            [{"text": "\U0001f504 Publicandose", "callback_data": f"manga:mw_filter:estado:publicandose:{back_ref}"}, {"text": "\u23f8\ufe0f Pausado", "callback_data": f"manga:mw_filter:estado:pausado:{back_ref}"}],
            [{"text": "\u2705 Finalizado", "callback_data": f"manga:mw_filter:estado:finalizado:{back_ref}"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def manga_manhwaweb_demo_menu() -> dict:
    """Menu para filtrar por demografia."""
    back_ref = _register_menu_callback(manga_manhwaweb_catalog_menu())
    
    return {
        "type": "menu",
        "text": "\U0001f465 FILTRO - DEMOGRAFIA\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige la demografia.",
        "buttons": [
            [{"text": "\U0001f9d1 Seinen", "callback_data": f"manga:mw_filter:demografia:seinen:{back_ref}"}, {"text": "\U0001f466 Shonen", "callback_data": f"manga:mw_filter:demografia:shonen:{back_ref}"}],
            [{"text": "\U0001f469 Josei", "callback_data": f"manga:mw_filter:demografia:josei:{back_ref}"}, {"text": "\U0001f467 Shojo", "callback_data": f"manga:mw_filter:demografia:shojo:{back_ref}"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def manga_manhwaweb_erotic_menu() -> dict:
    """Menu para filtrar por contenido erotico."""
    back_ref = _register_menu_callback(manga_manhwaweb_catalog_menu())
    
    return {
        "type": "menu",
        "text": "\U0001f52e FILTRO - EROTICO\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige el tipo.",
        "buttons": [
            [{"text": "\u2705 Si", "callback_data": f"manga:mw_filter:erotico:si:{back_ref}"}, {"text": "\u274c No", "callback_data": f"manga:mw_filter:erotico:no:{back_ref}"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def manga_manhwaweb_genre_menu() -> dict:
    """Menu para filtrar por genero."""
    back_ref = _register_menu_callback(manga_manhwaweb_catalog_menu())
    
    # Generos mas populares primero - organizados en filas de 2
    popular_genres = [
        (2, "\u2764\ufe0f Romance"), (1, "\U0001f3aa Drama"), (18, "\U0001f602 Comedia"), (6, "\U0001f3e5 Harem"),
        (23, "\U0001f3dd\ufe0f Fantasía"), (30, "\U0001f525 Ecchi"), (37, "\u2694\ufe0f Sistema de niveles"),
        (41, "\U0001f501 Reencarnación"), (3, "\U0001f4a8 Acción"), (29, "\U0001f3c0 Aventura"),
    ]
    
    buttons = []
    for gid, name in popular_genres:
        buttons.append([{"text": f"{name}", "callback_data": f"manga:mw_filter:genero:{gid}:{back_ref}"}])
    
    # Mas generos en segunda fila si hay espacio
    other_genres = [
        (31, "\U0001f47b Sobrenatural"), (5, "\u2696\ufe0f Venganza"), (25, "\U0001f494 Tragedia"),
        (43, "\U0001f9e8 Psicológico"), (8, "\U0001f470 Milf"), (42, "\U0001f3e0 Recuentos de la vida"),
    ]
    
    for gid, name in other_genres:
        buttons.append([{"text": f"{name}", "callback_data": f"manga:mw_filter:genero:{gid}:{back_ref}"}])
    
    if buttons:
        buttons.append([{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}])
    
    return {
        "type": "menu",
        "text": "\U0001f3f7\ufe0f FILTRO - GENEROS\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige un genero.",
        "buttons": buttons,
    }


def manga_manhwaweb_top10_menu() -> dict:
    """Menu para elegir criterio en Top 10."""
    back_ref = _register_menu_callback(manga_manhwaweb_menu())
    
    return {
        "type": "menu",
        "text": "\U0001f3c6 TOP 10 - MANHWA WEB\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige el criterio.",
        "buttons": [
            [{"text": "\U0001f525 Popularidad", "callback_data": f"manga:mw_top:popular:{back_ref}"}, {"text": "\u2b50 Valoracion", "callback_data": f"manga:mw_top:rated:{back_ref}"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def manga_manhwaweb_new_menu() -> dict:
    """Menu para elegir periodo en Novedades."""
    back_ref = _register_menu_callback(manga_manhwaweb_menu())
    
    return {
        "type": "menu",
        "text": "\u2728 NOVEDADES - MANHWA WEB\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nElige el periodo.",
        "buttons": [
            [{"text": "\U0001f4c5 Esta semana", "callback_data": f"manga:mw_new:week:{back_ref}"}, {"text": "\U0001f4c6 Este mes", "callback_data": f"manga:mw_new:month:{back_ref}"}],
            [{"text": "\u2b07\ufe0f Volver", "callback_data": f"manga:back:{back_ref}"}],
        ],
    }


def manga_manhwaweb_list(type_key: str, order_item: str = "alfabetico", filters: dict = None) -> dict:
    """Muestra resultados de un tipo especifico con ordenamiento y filtros."""
    labels = {
        "manhwa": "🇰🇷 MANHWA",
        "manga": "🇯🇵 MANGA",
        "manhua": "🇨🇳 MANHUA",
        "doujinshi": "🎨 DOUJINSHI",
        "novela": "📖 NOVELAS",
        "one_shot": "📄 ONE SHOT",
    }
    
    title = labels.get(type_key, f"📚 {type_key.upper()}")
    
    # Combinar filtros base (tipo) con filtros adicionales
    combined_filters = {"tipo": type_key}
    if filters:
        combined_filters.update(filters)
    
    try:
        # IMPORTANTE: No pasar manga_type al API porque ya lo manejamos via filters
        # El API ignora los parametros, asi que fetcheamos todo y filtramos del lado del cliente
        results = _manhwaweb._library_request("", "", order_item=order_item, limit=20, filters=combined_filters)
    except Exception as exc:
        return {"type": "text", "text": f"No pude cargar {title}: {exc}"}
    
    if not results:
        return {"type": "text", "text": f"No hay resultados para '{type_key}' con estos filtros."}
    
    back_ref = _register_menu_callback(manga_manhwaweb_catalog_menu())
    return _compact_results_menu(
        title,
        results,
        f"No hay {type_key} disponibles.",
        back_ref,
    )


def manga_handle_top10(sort_type: str) -> dict:
    """Muestra Top 10 de un criterio especifico."""
    labels = {"popular": "🔥 Popularidad", "rated": "⭐ Valoracion"}
    
    order_by = {
        "popular": "view_count",
        "rated": "rate_avg",
    }.get(sort_type, "view_count")
    
    try:
        results = _manhwaweb._library_request("", "", order_item=order_by, limit=20)
    except Exception as exc:
        logger.error(f"manga_handle_top10 error ({sort_type}): {exc}")
        results = []
    
    if not results:
        return {"type": "text", "text": f"No hay resultados para {labels.get(sort_type, sort_type)}."}
    
    back_ref = _register_menu_callback(manga_manhwaweb_top10_menu())
    return _compact_results_menu(
        f"🏆 TOP 10 {labels.get(sort_type, sort_type)} - MANHWA WEB",
        results,
        f"No encontre mangas por {labels.get(sort_type, sort_type)}.",
        back_ref,
    )


def manga_handle_new(timeframe: str) -> dict:
    """Muestra novedades de un periodo especifico."""
    labels = {"week": "📅 Esta semana", "month": "🗓️ Este mes"}
    
    try:
        results = _manhwaweb._library_request("", "", order_item="timestamp", limit=20)
    except Exception as exc:
        logger.error(f"manga_handle_new error ({timeframe}): {exc}")
        results = []
    
    if not results:
        return {"type": "text", "text": f"No hay novedades para {labels.get(timeframe, timeframe)}."}
    
    back_ref = _register_menu_callback(manga_manhwaweb_new_menu())
    return _compact_results_menu(
        f"✨ NOVEDADES - MANHWA WEB\n{labels.get(timeframe, timeframe)}",
        results,
        "No encontre novedades recientes.",
        back_ref,
    )


def manga_catalog_menu(chat_id: str, page: int = 0) -> dict:
    """Deprecated: usa manga_manhwaweb_catalog_menu() en su lugar."""
    return manga_manhwaweb_catalog_menu()


def manga_top10_menu() -> dict:
    """Deprecated: usa manga_manhwaweb_top10_menu() en su lugar."""
    return manga_manhwaweb_top10_menu()


def manga_new_menu() -> dict:
    """Deprecated: usa manga_manhwaweb_new_menu() en su lugar."""
    return manga_manhwaweb_new_menu()


def manga_auto_search(chat_id: str, query: str) -> dict:
    query = _clean_text(query)
    if not query:
        return {"type": "text", "text": "Escribe el nombre del manga que quieres buscar."}

    results = []
    seen = set()
    for type_key in MANGA_TYPES:
        found = _search_manga(query, manga_type=type_key, limit=5).get("results", [])
        for manga in found:
            if manga["url"] in seen:
                continue
            seen.add(manga["url"])
            results.append(manga)

    return _results_menu(
        f"Resultados para: {query}",
        results,
        f"No encontre mangas para '{query}'.",
    )


def manga_read(query: str, manga_type: str = "manhwa") -> dict:
    query = _clean_text(query)
    if not query:
        return {"type": "text", "text": "Escribe el nombre del manga."}
    result = _search_manga(query, manga_type=manga_type, limit=15)
    return _results_menu(
        f"Resultados para: {query}",
        result.get("results", []),
        f"No encontre mangas para '{query}'.",
    )


def manga_read_details(manga_ref: str, chat_id: str = "") -> dict:
    manga_id, back_ref = _split_callback_ref(manga_ref)
    resolved = _resolve_callback(manga_id, "manga") if manga_id else None
    if isinstance(resolved, dict):
        manga_url = resolved.get("url") or manga_id
    else:
        manga_url = resolved or manga_id
    
    details = _manhwaweb._get_manga_by_url(manga_url)
    if not details:
        return {"type": "text", "text": "No pude cargar ese manga de ManhwaWeb."}

    if chat_id:
        manga_add_history(chat_id, details["title"], details.get("url", manga_url))

    # Status emoji
    status = details.get("status") or ""
    status_emoji = _get_status_emoji(status)
    
    title = details.get("title", "Sin titulo")
    description = _clean_text(details.get("description"))[:MAX_DESCRIPTION_LENGTH]
    authors = ", ".join(details.get("authors") or []) or "Desconocido"
    categories = details.get("categories", [])
    chapters_list = details.get("chapters", [])
    chapters_count = len(chapters_list)
    
    # Build formatted text
    lines = [
        f"\U0001f4da {title}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "",
        f"{status_emoji} {status.capitalize() if status else 'Desconocido'}",
        f"\U0001f4da Tipo: {(details.get('type') or 'manga').capitalize()}",
        f"\u270d\ufe0f Autores: {authors}",
    ]
    
    if categories:
        lines.append(f"\U0001f3f7\ufe0f Generos: {', '.join(categories[:5])}")
    
    lines.extend(["", f"\U0001f4d6 Capitulos: {chapters_count}"])
    
    if description:
        lines.extend([
            "",
            "\U0001f4dd Sinopsis:",
            f"{description}...",
        ])

    buttons = []
    manga_id_token = _register_callback("manga", details.get("url", manga_url), title)
    detail_menu = {
        "type": "menu",
        "text": "\n".join(lines)[:MAX_MENU_TEXT_LENGTH],
        "buttons": buttons,
        "image": details.get("image"),
    }
    detail_ref = _register_menu_callback(detail_menu)
    
    # Quick actions
    if chapters_list:
        latest_chap = chapters_list[-1]  # Last chapter (most recent)
        chap_token = _register_callback("chapter", latest_chap.get("url", ""), "Ultimo cap")
        buttons.append([{"text": "\U0001f4d6 Leer ultimo cap", "callback_data": f"manga:chapter:{chap_token}:{detail_ref}"}])
        
        # Download latest chapter options
        buttons.append([
            {"text": "\U0001f4e5 ZIP ultimo cap", "callback_data": f"manga:download_chap:{chap_token}"},
            {"text": "\U0001f4c4 PDF ultimo cap", "callback_data": f"pdf_chap:{chap_token}"},
        ])

    # Chapter list (first 15, with pagination for more)
    chapters_to_show = chapters_list[:CHAPTERS_TO_SHOW_INITIAL]
    has_more_chapters = len(chapters_list) > CHAPTERS_TO_SHOW_INITIAL
    
    for chapter in chapters_to_show:
        chap_title = _short(chapter.get("title", f"Capitulo {chapter.get('number', '?')}"), MAX_TITLE_LENGTH)
        chapter_id = _register_callback("chapter", chapter.get("url", ""), chapter.get("title", "Capitulo"))
        buttons.append([{"text": f"\U0001f4d6 {chap_title}", "callback_data": f"manga:chapter:{chapter_id}:{detail_ref}"}])
    
    if has_more_chapters:
        remaining = len(chapters_list) - CHAPTERS_TO_SHOW_INITIAL
        buttons.append([{"text": f"Ver {remaining} caps mas...", "callback_data": f"manga:more_chaps:{manga_id_token}:{detail_ref}"}])

    buttons.extend([
        [
            {"text": "\u2b50 Favorito", "callback_data": f"manga:fav:{manga_id_token}"},
            {"text": "\U0001f310 Abrir web", "url": details.get("url", manga_url)},
        ],
    ])
    
    _append_back_button(buttons, back_ref)
    _store_menu_callback(detail_ref, detail_menu)
    return detail_menu


def _store_menu_callback(token: str, menu: dict):
    base._store_menu_callback(token, menu)


def manga_read_chapter(chapter_ref: str, chat_id: str = "") -> dict:
    chapter_id, back_ref = _split_callback_ref(chapter_ref)
    resolved = _resolve_callback(chapter_id, "chapter") if chapter_id else None
    if isinstance(resolved, dict):
        chapter_url = resolved.get("url") or chapter_id
    else:
        chapter_url = resolved or chapter_id
    
    images = _manhwaweb._get_chapter_images(chapter_url)

    chap_token = _register_callback("chapter", chapter_url)
    
    buttons = [[{"text": "🌐 Abrir capitulo web", "url": chapter_url}]]
    
    # Check if images are real full-page images (not Manhwaweb thumbnails via weserv proxy)
    is_weserv_thumbs = any("images.weserv.nl" in u for u in images)
    
    if not is_weserv_thumbs and len(images) > 5:
        buttons.append([{"text": f"... ver {len(images) - 5} paginas mas", "callback_data": f"manga:view:{chap_token}:0"}])
    
    # Download options only for real images (not thumbnails)
    if not is_weserv_thumbs and len(images) > 1:
        buttons.extend([
            [
                {"text": "📥 Descargar ZIP", "callback_data": f"manga:download_chap:{chap_token}"},
                {"text": "📄 Exportar PDF", "callback_data": f"pdf_chap:{chap_token}"},
            ],
        ])
    
    _append_back_button(buttons, back_ref)

    text = f"📖 Capitulo\n📄 {len(images)} paginas detectadas"
    if is_weserv_thumbs:
        text += "\n⚠️ Solo thumbnails disponibles. Abre el capitulo en la web para ver las paginas completas."
    elif not images:
        text += "\n\n⚠️ No pude extraer paginas, pero puedes abrirlo en la web."
    
    return {"type": "menu", "text": text, "buttons": buttons, "images": images[:3] if not is_weserv_thumbs else None, "image": images[0] if (not is_weserv_thumbs and images) else None}


def manga_add_history(chat_id: str, title: str, url: str):
    payload = _load_user_data(chat_id)
    payload["history"] = [item for item in payload["history"] if item.get("url") != url]
    payload["history"].insert(0, {"title": title, "url": url, "added_at": datetime.now().isoformat()})
    payload["history"] = payload["history"][:30]
    _save_user_data(chat_id, payload)


def manga_add_favorite(chat_id: str, title_or_ref: str, url: str = ""):
    if not url:
        resolved = _resolve_callback(title_or_ref, "manga")
        if isinstance(resolved, dict):
            title = resolved.get("title") or title_or_ref or "Manga"
            manga_url = resolved.get("url") or ""
        else:
            title = title_or_ref or "Manga"
            manga_url = resolved or ""
    else:
        title = title_or_ref or "Manga"
        manga_url = url
    if not manga_url:
        return {"type": "text", "text": "No pude guardar ese manga."}

    payload = _load_user_data(chat_id)
    if manga_url in payload["favorites"]:
        return {"type": "text", "text": f"Ya estaba en favoritos: {title}"}

    payload["favorites"][manga_url] = {"title": title, "url": manga_url, "added_at": datetime.now().isoformat()}
    _save_user_data(chat_id, payload)
    return {"type": "text", "text": f"Añadido a favoritos: {title}"}


def manga_remove_favorite(chat_id: str, ref: str) -> dict:
    resolved = _resolve_callback(ref, "manga")
    if isinstance(resolved, dict):
        manga_url = resolved.get("url") or ref
    else:
        manga_url = resolved or ref
    payload = _load_user_data(chat_id)
    removed = payload["favorites"].pop(manga_url, None)
    _save_user_data(chat_id, payload)
    if removed:
        return {"type": "text", "text": f"Eliminado de favoritos: {removed.get('title', 'Manga')}"}
    return {"type": "text", "text": "Ese manga no estaba en favoritos."}


def manga_get_history(chat_id: str) -> dict:
    payload = _load_user_data(chat_id)
    items = payload.get("history", [])
    if not items:
        return {"type": "text", "text": "Sin historial de mangas."}

    gallery_images = []
    buttons = []
    
    for i, item in enumerate(items):
        global_idx = i + 1
        manga_url = item.get("url", "")
        
        # Collect cover image if available
        img = item.get("image", "") or ""
        if img and ("http" in img or "https" in img):
            gallery_images.append(img)
        
        hist_id = _register_callback("manga", manga_url, item.get("title", "Sin titulo"))
        buttons.append([{"text": str(global_idx), "callback_data": f"read:{hist_id}"}])

    _append_back_button(buttons, "")
    
    return {
        "type": "menu",
        "text": "\U0001f4d6 HISTORIAL DE MANGAS\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n" + f"{len(items)} leidos",
        "buttons": buttons,
        "images": gallery_images,
    }


def manga_get_favorites(chat_id: str) -> dict:
    payload = _load_user_data(chat_id)
    items = list(payload.get("favorites", {}).values())
    if not items:
        return {"type": "text", "text": "Sin favoritos guardados."}

    gallery_images = []
    buttons = []
    
    for i, item in enumerate(items):
        global_idx = i + 1
        manga_url = item.get("url", "")
        manga_title = _short(item.get("title", "Sin titulo"), 25)
        
        # Collect cover image
        img = item.get("image", "") or ""
        if img and ("http" in img or "https" in img):
            gallery_images.append(img)
        
        fav_id = _register_callback("manga", manga_url, manga_title)
        buttons.append([{"text": str(global_idx), "callback_data": f"read:{fav_id}"}])

    _append_back_button(buttons, "")
    
    return {
        "type": "menu",
        "text": "\U0001f310 MIS FAVORITOS\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n" + f"{len(items)} guardados",
        "buttons": buttons,
        "images": gallery_images,
    }


def manga_get_downloads(chat_id: str) -> dict:
    payload = _load_user_data(chat_id)
    downloads = payload.get("downloads", [])
    if not downloads:
        return {"type": "text", "text": "Sin descargas registradas."}

    lines = ["DESCARGAS DE MANGA"]
    for item in downloads[:10]:
        lines.append(f"- {item.get('title')} - {item.get('chapter')} ({item.get('images_count', 0)} paginas)")
    return {"type": "text", "text": "\n".join(lines)}


def manga_download(chat_id: str, query: str) -> dict:
    result = _search_manga(query, limit=1)
    if not result.get("results"):
        return {"type": "text", "text": f"No encontre '{query}'."}

    first = result["results"][0]
    details = _manhwaweb._get_manga_by_url(first["url"])
    if not details or not details.get("chapters"):
        return {"type": "text", "text": "No pude encontrar capitulos descargables."}

    chapter = details["chapters"][0]
    images = _manhwaweb._get_chapter_images(chapter["url"])
    payload = _load_user_data(chat_id)
    payload["downloads"].insert(
        0,
        {
            "title": details["title"],
            "chapter": chapter["title"],
            "images_count": len(images),
            "downloaded_at": datetime.now().isoformat(),
        },
    )
    payload["downloads"] = payload["downloads"][:10]
    _save_user_data(chat_id, payload)
    return manga_read_chapter(_register_callback("chapter", chapter["url"], chapter["title"]))


def manga_view_chapter(chat_id: str, chapter_url: str, page: int = 0) -> dict:
    """Visualiza un capitulo con imagenes en Telegram."""
    images = _manhwaweb._get_chapter_images(chapter_url)
    
    if not images:
        return {"error": "Sin imagenes para este capitulo"}
    
    # Check if images are Manhwaweb thumbnails via weserv proxy
    is_weserv_thumbs = any("images.weserv.nl" in u for u in images)
    
    if is_weserv_thumbs:
        return {
            "type": "menu",
            "text": "⚠️ Solo hay thumbnails disponibles para este capitulo.\nAbre el capitulo en la web para ver las paginas completas.",
            "buttons": [[{"text": "🌐 Abrir capitulo web", "url": chapter_url}]],
        }
    
    # Mostrar 15 paginas por pantalla para mejor UX
    total_pages = (len(images) + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE
    
    if page >= total_pages:
        page = total_pages - 1
        
    start_idx = page * IMAGES_PER_PAGE
    end_idx = min(start_idx + IMAGES_PER_PAGE, len(images))
    current_images = images[start_idx:end_idx]
    
    lines = [
        f"📖 Capitulo {page + 1} de {total_pages}",
        "",
        f"📄 Pagina {start_idx + 1}-{end_idx} de {len(images)}",
    ]
    
    buttons = []
    
    chap_token = _register_callback("chapter", chapter_url)
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append({"text": "⬅️ Anterior", "callback_data": f"manga:view:{chap_token}:{page - 1}"})
    if end_idx < len(images):
        nav_buttons.append({"text": "Siguiente ➡️", "callback_data": f"manga:view:{chap_token}:{page + 1}"})
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Image links (max 8 per screen to avoid Telegram limits)
    for idx, img_url in enumerate(current_images[:8], start=start_idx + 1):
        buttons.append([{"text": f"🖼️ Pag {idx}", "url": img_url}])
    
    if len(current_images) > 8:
        remaining = len(current_images) - 8
        buttons.append([{"text": f"... y {remaining} mas", "url": current_images[8]}])
    
    # Download options
    buttons.extend([
        [
            {"text": "📥 ZIP cap.", "callback_data": f"manga:download_chap:{chap_token}"},
            {"text": "📄 PDF cap.", "callback_data": f"pdf_chap:{chap_token}"},
        ],
        [{"text": "⬅️ Volver", "callback_data": "manga:back"}],
    ])
    
    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
        "images": current_images[:3],  # Send first few as preview
        "page": page,
        "total_pages": total_pages,
    }


def manga_download_chapter(chat_id: str, chapter_url: str) -> dict:
    """Descarga un capitulo como ZIP."""
    import zipfile
    from io import BytesIO
    
    images = _manhwaweb._get_chapter_images(chapter_url)
    
    if not images:
        return {"error": "Sin imagenes para descargar"}
    
    # Check if images are Manhwaweb thumbnails via weserv proxy (not downloadable as full pages)
    is_weserv_thumbs = any("images.weserv.nl" in u for u in images)
    if is_weserv_thumbs:
        return {"error": "Solo hay thumbnails disponibles. Abre el capitulo en la web para descargar."}
    
    base.logger.info(f"manga_download_chapter: Found {len(images)} images")
    
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for idx, img_url in enumerate(images):
            try:
                resp = requests.get(img_url, headers=base._get_headers(), timeout=10)
                zf.writestr(f"page_{idx + 1:03d}.jpg", resp.content)
            except Exception:
                pass
    
    zip_buffer.seek(0)
    
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    chapter_title = f"capitulo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    file_path = base.DATA_DIR / f"{chapter_title}.zip"
    
    with open(file_path, 'wb') as f:
        f.write(zip_buffer.getvalue())
    
    return {
        "type": "document",
        "path": str(file_path),
        "caption": f"✅ Descargado: {chapter_title}.zip\n{len(images)} paginas",
    }


def manga_download_full(chat_id: str, manga_url: str) -> dict:
    """Descarga un manga completo como ZIP."""
    import zipfile
    from io import BytesIO
    
    details = _manhwaweb._get_manga_by_url(manga_url)
    
    if not details:
        return {"error": "Manga no encontrado"}
    
    chapters = details.get("chapters", [])
    
    if not chapters:
        return {"error": "Sin capitulos disponibles"}
    
    base.logger.info(f"manga_download_full: Found {len(chapters)} chapters")
    
    zip_buffer = BytesIO()
    manga_title = re.sub(r'[^\w\s-]', '', details.get("title", "manga"))[:50]
    
    downloaded_chapters = 0
    failed_chapters = []
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for chapter in chapters:
            chapter_num = chapter.get("number") or chapter.get("chapter", 1)
            
            # Obtener imagenes usando la funcion del servidor
            images = _manhwaweb._get_chapter_images(chapter.get("url", ""))
            
            if not images:
                failed_chapters.append(str(chapter_num))
                continue
            
            # Skip chapters with weserv thumbnails (not real full-page images)
            is_weserv_thumbs = any("images.weserv.nl" in u for u in images)
            if is_weserv_thumbs:
                failed_chapters.append(f"{chapter_num} (thumbnails)")
                continue
            
            for idx, img_url in enumerate(images):
                try:
                    resp = requests.get(img_url, headers=base._get_headers(), timeout=10)
                    if resp.ok:
                        zf.writestr(f"{manga_title}/cap_{chapter_num:03d}_p{idx+1}.jpg", resp.content)
                        downloaded_chapters += 1
                except Exception as e:
                    base.logger.warning(f"Error downloading chapter {chapter_num}, image {idx}: {e}")
    
    zip_buffer.seek(0)
    
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = base.DATA_DIR / f"{manga_title}_completo.zip"
    
    with open(file_path, 'wb') as f:
        f.write(zip_buffer.getvalue())
    
    error_msg = ""
    if failed_chapters:
        error_msg = f"\n\n⚠️ Fallaron {len(failed_chapters)} capitulos"
    
    return {
        "type": "document",
        "path": str(file_path),
        "caption": f"✅ Manga completo ZIP\n{len(chapters)} caps - {downloaded_chapters} paginas descargadas{error_msg}\n{file_path.name}",
    }


def manga_view_full(chat_id: str, manga_url: str) -> dict:
    details = _manhwaweb._get_manga_by_url(manga_url)
    
    if not details:
        return {"error": "Manga no encontrado"}
    
    chapters = details.get("chapters", [])
    
    # Check if any chapter has real images (not just thumbnails) for download options
    has_real_images = False
    for chapter in chapters[:5]:  # Check first 5 chapters as sample
        images = _manhwaweb._get_chapter_images(chapter.get("url", ""))
        if images and not any("images.weserv.nl" in u for u in images):
            has_real_images = True
            break
    
    lines = [
        f"{details.get('title', 'Sin titulo')}",
        f"Capitulos: {len(chapters)}"
    ]
    
    buttons = []
    
    # Token para manga completo
    manga_token = _register_callback("manga", manga_url)
    
    for idx, chapter in enumerate(chapters[:20], 1):
        chap_title = chapter.get("title", f"Capitulo {idx}")[:30]
        chap_url = chapter.get("url", "")
        
        # Token para cada capitulo
        chap_token = _register_callback("chapter", chap_url)
        
        buttons.append([
            {
                "text": f"{idx}. {chap_title}",
                "callback_data": f"view_chap:{chap_token}"
            },
            {
                "text": "📥",
                "callback_data": f"download_chap:{chap_token}"
            },
        ])
    
    # Only show full download options if we have real images (not thumbnails)
    if has_real_images:
        buttons.append([
            {
                "text": "⬇️ Descargar ZIP todo",
                "callback_data": f"download_full:{manga_token}"
            },
            {
                "text": "📄 Exportar PDF todo",
                "callback_data": f"pdf_full:{manga_token}"
            },
        ])
    
    buttons.append([
        {
            "text": "⬇️ Descargar ZIP todo",
            "callback_data": f"download_full:{manga_token}"
        },
        {
            "text": "📄 Exportar PDF todo",
            "callback_data": f"pdf_full:{manga_token}"
        },
    ])
    buttons.append([{"text": "↩️ Volver", "callback_data": "manga:back"}])
    
    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
    }


def manga_export_chapter_pdf(chat_id: str, chapter_url: str) -> dict:
    """Exporta un capitulo como PDF."""
    import img2pdf
    
    images = _manhwaweb._get_chapter_images(chapter_url)
    
    if not images:
        return {"error": "Sin imagenes para exportar"}
    
    # Check if images are Manhwaweb thumbnails via weserv proxy (not downloadable as full pages)
    is_weserv_thumbs = any("images.weserv.nl" in u for u in images)
    if is_weserv_thumbs:
        return {"error": "Solo hay thumbnails disponibles. Abre el capitulo en la web para exportar."}
    
    base.logger.info(f"manga_export_chapter_pdf: Found {len(images)} images")
    
    pdf_pages = []
    downloaded_count = 0
    
    for idx, img_url in enumerate(images):
        try:
            resp = requests.get(img_url, headers=base._get_headers(), timeout=10)
            if resp.ok:
                from PIL import Image as PILImage
                from io import BytesIO
                
                img = PILImage.open(BytesIO(resp.content))
                
                # Convertir a RGB si es necesario (PNG con transparencia, etc.)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                
                # Guardar como JPEG en memoria para compatibilidad con img2pdf
                jpeg_buffer = BytesIO()
                img.save(jpeg_buffer, format='JPEG', quality=85)
                jpeg_buffer.seek(0)
                
                pdf_pages.append(img2pdf.convert(jpeg_buffer.getvalue()))
                downloaded_count += 1
        except Exception as e:
            base.logger.warning(f"Error processing image {idx}: {e}")
    
    if not pdf_pages:
        return {"error": "No se pudo descargar ninguna imagen"}
    
    pdf_bytes = b"".join(pdf_pages)
    
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_path = base.DATA_DIR / f"capitulo_{timestamp}.pdf"
    
    with open(file_path, 'wb') as f:
        f.write(pdf_bytes)
    
    return {
        "type": "document",
        "path": str(file_path),
        "caption": f"✅ PDF: {downloaded_count} paginas\n{file_path.name}",
    }


def manga_export_full_pdf(chat_id: str, manga_url: str) -> dict:
    """Exporta un manga completo como PDF."""
    import img2pdf
    
    details = _manhwaweb._get_manga_by_url(manga_url)
    
    if not details:
        return {"error": "Manga no encontrado"}
    
    chapters = details.get("chapters", [])
    
    if not chapters:
        return {"error": "Sin capitulos disponibles"}
    
    base.logger.info(f"manga_export_full_pdf: Found {len(chapters)} chapters")
    
    pdf_pages = []
    total_downloaded = 0
    
    for chapter in chapters:
        chapter_num = chapter.get("number") or chapter.get("chapter", 1)
        
        images = _manhwaweb._get_chapter_images(chapter.get("url", ""))
        
        if not images:
            base.logger.warning(f"No images for chapter {chapter_num}")
            continue
        
        # Skip chapters with weserv thumbnails (not real full-page images)
        is_weserv_thumbs = any("images.weserv.nl" in u for u in images)
        if is_weserv_thumbs:
            base.logger.warning(f"Chapter {chapter_num} has only thumbnails, skipping")
            continue
        
        for idx, img_url in enumerate(images):
            try:
                resp = requests.get(img_url, headers=base._get_headers(), timeout=10)
                if resp.ok:
                    from PIL import Image as PILImage
                    from io import BytesIO
                    
                    img = PILImage.open(BytesIO(resp.content))
                    
                    # Convertir a RGB si es necesario
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    elif img.mode not in ('RGB', 'L'):
                        img = img.convert('RGB')
                    
                    # Guardar como JPEG en memoria para compatibilidad con img2pdf
                    jpeg_buffer = BytesIO()
                    img.save(jpeg_buffer, format='JPEG', quality=85)
                    jpeg_buffer.seek(0)
                    
                    pdf_pages.append(img2pdf.convert(jpeg_buffer.getvalue()))
                    total_downloaded += 1
            except Exception as e:
                base.logger.warning(f"Error processing chapter {chapter_num}, image {idx}: {e}")
    
    if not pdf_pages:
        return {"error": "No se pudo descargar ninguna imagen"}
    
    try:
        pdf_bytes = img2pdf.convert(pdf_pages)
        
        base.DATA_DIR.mkdir(parents=True, exist_ok=True)
        manga_title = re.sub(r'[^\w\s-]', '', details.get("title", "manga"))[:50]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = base.DATA_DIR / f"{manga_title}_{timestamp}.pdf"
        
        with open(file_path, 'wb') as f:
            f.write(pdf_bytes)
        
        return {
            "type": "document",
            "path": str(file_path),
            "caption": f"✅ Manga completo PDF\n{len(chapters)} caps - {total_downloaded} paginas\n{file_path.name}",
        }
    except Exception as e:
        base.logger.error(f"Error creating full PDF: {e}")
        return {"error": f"Error creando PDF: {str(e)[:200]}"}
