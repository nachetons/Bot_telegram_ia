import logging
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import requests

from app.tools.manga import base

logger = logging.getLogger("manga_tool")

# Server-specific configuration
BASE_URL = "https://www.manhwaweb.com"
API_BASE = "https://manhwawebbackend-production.up.railway.app"
LIBRARY_URL = f"{API_BASE}/manhwa/library"


def _slug_from_url(manga_url: str) -> str:
    path = urlparse(manga_url).path
    if "/manhwa/" in path:
        return path.split("/manhwa/", 1)[1].strip("/")
    if "/leer/" in path:
        value = path.split("/leer/", 1)[1].strip("/")
        return re.sub(r"-\d+(?:\.\d+)?$", "", value)
    return manga_url.strip().split("/")[-1]


def _chapter_from_url(chapter_url: str) -> Optional[str]:
    parsed = urlparse(chapter_url)
    query_value = parse_qs(parsed.query).get("cap", [None])[0]
    if query_value:
        return query_value

    match = re.search(r"-(\d+(?:\.\d+)?)$", parsed.path)
    return match.group(1) if match else None


def _manga_url(slug_id: str) -> str:
    return f"{BASE_URL}/manhwa/{slug_id}"


def _chapter_url(slug_id: str, chapter_number) -> str:
    return f"{BASE_URL}/leer/{slug_id}-{chapter_number}"


def _library_request(query: str = "", manga_type: str = "", order_item: str = "alfabetico", limit: int = 20) -> List[dict]:
    params = {
        "buscar": query or "",
        "tipo": manga_type or "",
        "order_item": order_item,
        "order_dir": "desc",
        "page": 0,
    }
    
    try:
        response = requests.get(LIBRARY_URL, params=params, headers=base._get_headers(), timeout=20)
        logger.info(f"_library_request: Status {response.status_code}")
        
        text_content = response.text[:500] if response.ok else "Error"
        logger.debug(f"_library_request: Response preview: {text_content}")
        
        data = response.json()
        results = []
        
        manga_list = data.get("data") or []
        logger.info(f"_library_request: Found {len(manga_list)} items in API response")
        
        for item in manga_list[:limit]:
            manga = base._item_to_manga(item, manga_type)
            if manga:
                # Set server-specific URL
                slug_id = ""
                extras = item.get("_extras") or {}
                slug_id = item.get("_id") or item.get("real_id")
                if slug_id:
                    manga["url"] = _manga_url(str(slug_id))
                
                # Debug: log image field for first 3 items to diagnose display issues
                if len(results) < 3 and not manga.get("image"):
                    logger.debug(f"_library_request: No image for '{manga.get('title')}', keys={list(item.keys())[:10]}")
                
                results.append(manga)
        
        return results
        
    except Exception as exc:
        logger.error(f"_library_request error: {exc}")
        raise


def _get_manga_by_url(manga_url: str) -> Optional[dict]:
    slug_id = _slug_from_url(manga_url)
    if not slug_id:
        return None
    
    # Check cache first
    cache_key = f"manga:{slug_id}"
    cached = base._cache_get(cache_key)
    if cached:
        logger.debug(f"Cache hit for manga: {slug_id}")
        return cached

    try:
        response = requests.get(
            f"{API_BASE}/manhwa/see/{slug_id}",
            headers=base._get_headers(),
            timeout=20,
        )
        response.raise_for_status()
        result = _parse_manga_details(response.json())
        
        # Store in cache
        if result:
            base._cache_set(cache_key, result)
            logger.debug(f"Cached manga: {slug_id}")
        
        return result
    except Exception as exc:
        logger.error("Error fetching manga %s: %s", manga_url, exc)
        return None


def _parse_manga_details(data: dict) -> dict:
    slug_id = str(data.get("_id") or data.get("real_id") or "")
    title = data.get("the_real_name") or data.get("name_esp") or data.get("_name") or "Sin titulo"
    extras = data.get("_extras") or {}
    authors = extras.get("autores") or []
    categories = []
    for raw in data.get("_categoris") or []:
        if isinstance(raw, dict):
            categories.extend(str(value) for value in raw.values())

    chapters = []
    for chapter in data.get("chapters") or data.get("chapters_esp") or []:
        if not isinstance(chapter, dict):
            continue
        number = chapter.get("chapter")
        link = chapter.get("link") or _chapter_url(slug_id, number)
        chapters.append(
            {
                "title": f"Capitulo {number}",
                "number": number,
                "url": link,
                "images": chapter.get("img") or [],
            }
        )

    chapters.sort(key=lambda item: float(item.get("number") or 0), reverse=True)
    return {
        "title": title,
        "description": data.get("_sinopsis") or "",
        "image": data.get("_imagen"),
        "type": data.get("_tipo") or "manhwa",
        "status": data.get("_status") or "desconocido",
        "authors": authors,
        "categories": categories,
        "chapters": chapters,
        "url": _manga_url(slug_id),
    }


def _get_chapter_images(chapter_url: str) -> List[str]:
    """Extrae las URLs de imágenes de un capítulo."""
    details = _get_manga_by_url(chapter_url)
    if not details:
        return []

    wanted = _chapter_from_url(chapter_url)
    
    for chapter in details.get("chapters", []):
        if str(chapter.get("number")) == str(wanted):
            images = chapter.get("images") or chapter.get("img") or []
            
            # Si es string (URL única), convertir a lista
            if isinstance(images, str) and images:
                logger.debug(f"_get_chapter_images: Found image URL: {images[:50]}...")
                return [images]
            
            # Si es lista, retornar tal cual
            if isinstance(images, list):
                logger.info(f"_get_chapter_images: Found {len(images)} images in list")
                return images
            
            # Si es dict con campo "url"
            if isinstance(images, dict) and images.get("url"):
                return [images["url"]]
    
    logger.warning(f"_get_chapter_images: No images found for chapter {wanted}")
    return []
