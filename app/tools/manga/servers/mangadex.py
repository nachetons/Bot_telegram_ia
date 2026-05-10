import logging
import re
import time
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import requests

from app.tools.manga import base

logger = logging.getLogger("manga_tool")

# MangaDex API configuration
API_BASE = "https://api.mangadex.org"
HEADERS = {
    "User-Agent": "TelegramMangaBot/1.0",
    "Accept": "application/json",
}


def _get_popular_manga(limit: int = 20) -> List[dict]:
    """Obtiene los mangas mas populares de MangaDex."""
    try:
        params = {
            "limit": limit,
            "offset": 0,
            "order[latestUploadedChapter]": "desc",
            "includes[]": "cover_art",
        }
        
        response = requests.get(
            f"{API_BASE}/manga",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        manga_list = data.get("data") or []
        logger.info(f"MangaDex popular: Found {len(manga_list)} results")
        
        return _parse_manga_list(manga_list, limit)
    
    except Exception as exc:
        logger.error(f"MangaDex popular error: {exc}")
        return []


def _get_recent_manga(limit: int = 20) -> List[dict]:
    """Obtiene los mangas mas recientes de MangaDex."""
    try:
        params = {
            "limit": limit,
            "offset": 0,
            "order[createdAt]": "desc",
            "includes[]": "cover_art",
        }
        
        response = requests.get(
            f"{API_BASE}/manga",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        manga_list = data.get("data") or []
        logger.info(f"MangaDex recent: Found {len(manga_list)} results")
        
        return _parse_manga_list(manga_list, limit)
    
    except Exception as exc:
        logger.error(f"MangaDex recent error: {exc}")
        return []


def _parse_manga_list(manga_list: list, limit: int = 20) -> List[dict]:
    """Parsea una lista de mangas desde la API de MangaDex."""
    results = []
    
    for item in manga_list[:limit]:
        attributes = item.get("attributes", {})
        manga_id = item.get("id")
        
        # Get cover art URL if available
        cover_url = ""
        relationships = item.get("relationships", [])
        for rel in relationships:
            if rel.get("type") == "cover_art":
                media_attributes = rel.get("attributes", {})
                cover_filename = media_attributes.get("filename")
                if cover_filename:
                    cover_url = f"https://uploads.mangadex.org/manga/{manga_id}/{cover_filename}"
                break
        
        # Get alternative titles (English, Spanish, etc.)
        alt_titles = attributes.get("altTitles", []) or []
        main_title = attributes.get("title", {}).get("en") or attributes.get("title", {}).get("es") or ""
        
        # Try to find a readable title
        for t in alt_titles:
            if isinstance(t, dict):
                en_title = t.get("en") or t.get("es") or ""
                if en_title and main_title == "":
                    main_title = en_title
        
        if not main_title:
            titles = attributes.get("title", {})
            if isinstance(titles, dict):
                main_title = titles.get("en") or titles.get("es") or titles.get("ja-ro") or ""
        
        if not main_title:
            continue
        
        # Get description (English or Spanish)
        desc_key = None
        for key in ["en", "es"]:
            desc_map = attributes.get("description", {}).get(key, "")
            if desc_map:
                desc_key = key
                break
        
        description = ""
        if desc_key:
            description = attributes["description"].get(desc_key, "")[:500]
        
        # Get status
        status_map = {
            "completed": "Completado",
            "ongoing": "Publicandose",
            "hiatus": "En pausa",
            "cancelled": "Cancelado",
        }
        raw_status = attributes.get("status") or ""
        status = status_map.get(raw_status, raw_status) if raw_status else "Desconocido"
        
        # Get genres/tags
        genres = []
        tags = attributes.get("tags", [])
        for tag in tags[:5]:
            if isinstance(tag, dict):
                name = tag.get("attributes", {}).get("name", {})
                if isinstance(name, dict):
                    genre = name.get("en") or name.get("es") or ""
                    if genre:
                        genres.append(genre)
        
        # Get chapter count from attributes
        chapters_count = attributes.get("availableChaptersCount", "")
        
        results.append({
            "title": main_title,
            "url": f"mangadex:manga:{manga_id}",
            "image": cover_url,
            "type": "manga",
            "status": status,
            "chapters_count": chapters_count,
            "description": description,
            "genres": genres,
            "_mangadx_id": manga_id,
        })
    
    return results


def _search_manga(query: str, limit: int = 20) -> List[dict]:
    """Busca manga en MangaDex usando la API oficial."""
    results = []
    
    try:
        # Step 1: Search for manga titles (simplified params)
        params = {
            "title": query,
            "limit": limit,
            "offset": 0,
            "includes[]": "cover_art",
        }
        
        response = requests.get(
            f"{API_BASE}/manga",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        manga_list = data.get("data") or []
        logger.info(f"MangaDex search: Found {len(manga_list)} results for '{query}'")
        
        for item in manga_list[:limit]:
            attributes = item.get("attributes", {})
            manga_id = item.get("id")
            
            # Get cover art URL if available
            cover_url = ""
            relationships = item.get("relationships", [])
            for rel in relationships:
                if rel.get("type") == "cover_art":
                    media_attributes = rel.get("attributes", {})
                    cover_filename = media_attributes.get("filename")
                    if cover_filename:
                        lang = media_attributes.get("language", "")
                        cover_url = f"https://uploads.mangadex.org/manga/{manga_id}/cover.jpg"
                        # Try to use the actual cover
                        cover_url = f"https://uploads.mangadex.org/manga/{manga_id}/{cover_filename}"
                    break
            
            # Get alternative titles (English, Spanish, etc.)
            alt_titles = attributes.get("altTitles", []) or []
            main_title = attributes.get("title", {}).get("en") or attributes.get("title", {}).get("es") or ""
            
            # Try to find a readable title
            for t in alt_titles:
                if isinstance(t, dict):
                    en_title = t.get("en") or t.get("es") or ""
                    if en_title and main_title == "":
                        main_title = en_title
            
            if not main_title:
                titles = attributes.get("title", {})
                if isinstance(titles, dict):
                    main_title = titles.get("en") or titles.get("es") or titles.get("ja-ro") or ""
            
            if not main_title:
                main_title = "Sin titulo"
            
            # Get description (English or Spanish)
            desc_key = None
            for key in ["en", "es"]:
                desc_map = attributes.get("description", {}).get(key, "")
                if desc_map:
                    desc_key = key
                    break
            
            description = ""
            if desc_key:
                description = attributes["description"].get(desc_key, "")[:500]
            
            # Get status
            status_map = {
                "completed": "Completado",
                "ongoing": "Publicandose",
                "hiatus": "En pausa",
                "cancelled": "Cancelado",
            }
            raw_status = attributes.get("status") or ""
            status = status_map.get(raw_status, raw_status) if raw_status else "Desconocido"
            
            # Get genres/tags
            genres = []
            tags = attributes.get("tags", [])
            for tag in tags[:5]:
                if isinstance(tag, dict):
                    name = tag.get("attributes", {}).get("name", {})
                    if isinstance(name, dict):
                        genre = name.get("en") or name.get("es") or ""
                        if genre:
                            genres.append(genre)
            
            # Get chapter count from attributes
            chapters_count = attributes.get("availableChaptersCount", "")
            
            results.append({
                "title": main_title,
                "url": f"mangadex:manga:{manga_id}",
                "image": cover_url,
                "type": "manga",
                "status": status,
                "chapters_count": chapters_count,
                "description": description,
                "genres": genres,
                "_mangadx_id": manga_id,
            })
        
        return results
        
    except Exception as exc:
        logger.error(f"MangaDex search error: {exc}")
        raise


def _get_manga_details(manga_id: str) -> Optional[dict]:
    """Obtiene detalles completos de un manga por su ID."""
    # Check cache first
    cache_key = f"mangadex:manga:{manga_id}"
    cached = base._cache_get(cache_key)
    if cached:
        logger.debug(f"MangaDex cache hit for manga: {manga_id}")
        return cached
    
    try:
        # Fetch manga details with chapters using individual endpoint
        response = requests.get(
            f"{API_BASE}/manga/{manga_id}",
            params={
                "includes[]": "author",
                "includes[]": "artist", 
                "includes[]": "cover_art",
            },
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        item = data.get("data")
        if not item:
            return None
        
        attributes = item.get("attributes", {})
        
        # Get title - handle both dict and string formats
        raw_title = attributes.get("title") or {}
        if isinstance(raw_title, dict):
            main_title = raw_title.get("en") or raw_title.get("es") or raw_title.get("ja-ro") or "Sin titulo"
        elif isinstance(raw_title, str):
            main_title = raw_title or "Sin titulo"
        else:
            main_title = "Sin titulo"
        
        # Get alt titles for additional context
        alt_titles = attributes.get("altTitles") or []
        for t in alt_titles:
            if isinstance(t, dict):
                es_title = t.get("es") or t.get("en") or ""
                if es_title and es_title != main_title:
                    main_title = f"{main_title} ({es_title})"
                    break
        
        # Get description
        desc_key = None
        for key in ["en", "es"]:
            if attributes.get("description", {}).get(key):
                desc_key = key
                break
        
        description = ""
        if desc_key:
            description = attributes["description"].get(desc_key, "")[:1000]
        
        # Get authors and artists
        authors = []
        artists = []
        relationships = item.get("relationships", [])
        for rel in relationships:
            rel_type = rel.get("type")
            if rel_type == "author":
                attrs = rel.get("attributes", {})
                name = attrs.get("name", "")
                if name:
                    authors.append(name)
            elif rel_type == "artist":
                attrs = rel.get("attributes", {})
                name = attrs.get("name", "")
                if name:
                    artists.append(name)
        
        all_creators = [a for a in authors] + [a for a in artists]
        
        # Get status
        status_map = {
            "completed": "Completado",
            "ongoing": "Publicandose",
            "hiatus": "En pausa",
            "cancelled": "Cancelado",
            "upcoming": "Por publicar",
        }
        raw_status = attributes.get("status") or ""
        status = status_map.get(raw_status, raw_status) if raw_status else "Desconocido"
        
        # Get type
        type_map = {
            "manga": "Manga",
            "manhwa": "Manhwa",
            "manhua": "Manhua",
            "one_shot": "One Shot",
            "doujin": "Doujinshi",
            "novel": "Novela",
        }
        raw_type = attributes.get("type") or ""
        manga_type = type_map.get(raw_type, raw_type.capitalize()) if raw_type else "Manga"
        
        # Get genres/tags
        categories = []
        tags = attributes.get("tags", [])
        for tag in tags[:5]:
            if isinstance(tag, dict):
                name = tag.get("attributes", {}).get("name", {})
                if isinstance(name, dict):
                    cat = name.get("en") or name.get("es") or ""
                    if cat:
                        categories.append(cat)
        
        # Get cover image
        cover_url = ""
        for rel in relationships:
            if rel.get("type") == "cover_art":
                media_attrs = rel.get("attributes", {})
                filename = media_attrs.get("filename")
                if filename:
                    cover_url = f"https://uploads.mangadex.org/manga/{manga_id}/{filename}"
                break
        
        # Fetch chapters for this manga
        chapters = _fetch_chapters(manga_id)
        
        result = {
            "title": main_title,
            "description": description,
            "image": cover_url,
            "type": manga_type,
            "status": status,
            "authors": all_creators or ["Desconocido"],
            "categories": categories,
            "chapters": chapters,
            "url": f"mangadex:manga:{manga_id}",
            "_mangadx_id": manga_id,
        }
        
        # Cache the result
        base._cache_set(cache_key, result)
        logger.debug(f"MangaDex cached details for: {main_title}")
        
        return result
        
    except Exception as exc:
        logger.error(f"MangaDex error fetching manga {manga_id}: {exc}")
        return None


def _fetch_chapters(manga_id: str, limit: int = 100) -> List[dict]:
    """Obtiene los capitulos de un manga."""
    chapters = []
    
    try:
        params = {
            "limit": min(limit, 100),
            "offset": 0,
            "order[chapter]": "desc",
        }
        
        response = requests.get(
            f"{API_BASE}/manga/{manga_id}/feed",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        chapter_list = data.get("result") == "ok" and (data.get("data") or [])
        logger.info(f"MangaDex chapters: Found {len(chapter_list)} for manga {manga_id}")
        
        # Limit to 100 most recent chapters
        for chap in chapter_list[:100]:
            attributes = chap.get("attributes", {})
            chap_num = attributes.get("chapter") or ""
            title = attributes.get("title") or f"Capitulo {chap_num}"
            volume = attributes.get("volume") or ""
            
            if volume:
                display_title = f"Vol. {volume} - Cap. {chap_num}"
            else:
                display_title = f"Capitulo {chap_num}"
            
            chapters.append({
                "title": display_title,
                "number": chap_num,
                "url": f"mangadex:chapter:{chap.get('id')}:{manga_id}",
                "_mangadx_chapter_id": chap.get("id"),
                "_mangadx_manga_id": manga_id,
            })
        
        return chapters
        
    except Exception as exc:
        logger.error(f"MangaDex error fetching chapters for {manga_id}: {exc}")
        return []


def _get_chapter_images(chapter_url: str) -> List[str]:
    """Obtiene las imagenes de un capitulo de MangaDex."""
    # Parse the URL format: mangadex:chapter:{chapter_id}:{manga_id}
    if not chapter_url.startswith("mangadex:chapter:"):
        return []
    
    parts = chapter_url.split(":")
    if len(parts) < 4:
        return []
    
    chapter_id = parts[2]
    manga_id = parts[3]
    
    # Check cache first
    cache_key = f"mangadex:images:{chapter_id}"
    cached = base._cache_get(cache_key)
    if cached:
        logger.debug(f"MangaDex image cache hit for chapter: {chapter_id}")
        return cached
    
    try:
        # Fetch chapter data with agent (for images)
        response = requests.get(
            f"{API_BASE}/at-home/server/{chapter_id}",
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        result = data.get("result") == "ok"
        if not result:
            logger.warning(f"MangaDex returned non-ok result for chapter {chapter_id}")
            return []
        
        # MangaDex API structure: baseUrl at root, images in chapter.data
        base_url = data.get("baseUrl", "")
        chapter_data = data.get("chapter", {})
        hash_id = chapter_data.get("hash", "")
        images_data = chapter_data.get("data") or chapter_data.get("images", [])
        
        if not base_url or not images_data:
            logger.warning(f"MangaDex no data found for chapter {chapter_id}")
            return []
        
        # Build image URLs - MangaDex uses webp format
        image_urls = [f"{base_url}/data/{hash_id}/{img}" for img in images_data]
        
        # Cache the result
        base._cache_set(cache_key, image_urls)
        logger.info(f"MangaDex fetched {len(image_urls)} images for chapter {chapter_id}")
        
        return image_urls
        
    except Exception as exc:
        logger.error(f"MangaDex error fetching images for chapter {chapter_id}: {exc}")
        return []


def _get_manga_by_url(manga_url: str) -> Optional[dict]:
    """Resuelve una URL de MangaDex y devuelve los detalles del manga."""
    if not manga_url.startswith("mangadex:manga:"):
        return None
    
    parts = manga_url.split(":")
    if len(parts) < 3:
        return None
    
    manga_id = parts[2]
    return _get_manga_details(manga_id)


def search_mangadx(query: str, limit: int = 20) -> List[dict]:
    """Busca mangas en MangaDex."""
    try:
        return _search_manga(query, limit=limit)
    except Exception as exc:
        logger.error(f"MangaDex search error: {exc}")
        return []
