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

# Max retries for rate-limited requests
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _cover_url(manga_id: str, filename: str, size: int = 512) -> str:
    """Build a public MangaDex cover URL from the cover_art filename."""
    if not manga_id or not filename:
        return ""

    filename = filename.strip()
    suffix = f".{size}.jpg" if size else ""
    return f"https://uploads.mangadex.org/covers/{manga_id}/{filename}{suffix}"


def _request_with_retry(url: str, params: dict = None, headers: dict = None, timeout: int = 20) -> Optional[requests.Response]:
    """Make an HTTP request with exponential backoff for rate limiting."""
    last_exc = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)

            # Handle 429 Too Many Requests
            if response.status_code == 429 and attempt < MAX_RETRIES - 1:
                retry_after = int(response.headers.get("Retry-After", RETRY_DELAY * (attempt + 1)))
                logger.warning(f"MangaDex rate limited. Waiting {retry_after}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                retry_after = int(exc.response.headers.get("Retry-After", RETRY_DELAY * (attempt + 1)))
                logger.warning(f"MangaDex rate limited via HTTP error. Waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            last_exc = exc

        except requests.exceptions.Timeout:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"MangaDex timeout. Retrying in {wait_time}s")
                time.sleep(wait_time)
                continue
            break

        except requests.exceptions.ConnectionError:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"MangaDex connection error. Retrying in {wait_time}s")
                time.sleep(wait_time)
                continue
            break

    logger.error(f"MangaDex request failed after {MAX_RETRIES} attempts: {last_exc}")
    return None


def _get_popular_manga(limit: int = 20) -> List[dict]:
    """Obtiene los mangas mas populares de MangaDex."""
    try:
        params = {
            "limit": limit,
            "offset": 0,
            "order[followedCount]": "desc",
            "includes[]": "cover_art",
        }

        response = _request_with_retry(
            f"{API_BASE}/manga",
            params=params,
            timeout=20,
        )
        if not response:
            return []

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

        response = _request_with_retry(
            f"{API_BASE}/manga",
            params=params,
            timeout=20,
        )
        if not response:
            return []

        data = response.json()

        manga_list = data.get("data") or []
        logger.info(f"MangaDex recent: Found {len(manga_list)} results")

        return _parse_manga_list(manga_list, limit)

    except Exception as exc:
        logger.error(f"MangaDex recent error: {exc}")
        return []


def _extract_genre_name(tag_data: dict) -> str:
    """Extrae el nombre de un tag genero, manejando ambos formatos de la API.

    La API de MangaDex devuelve tags con esta estructura:
    {
      "id": "...",
      "type": "tag",
      "attributes": {
        "name": {"en": "Action", "es": "Acción"},
        "group": "genre"
      }
    }
    """
    if not isinstance(tag_data, dict):
        return ""

    attrs = tag_data.get("attributes", {})
    if not isinstance(attrs, dict):
        return ""

    # El nombre del genero está dentro de attributes.name (dict con idiomas)
    name_dict = attrs.get("name", {})
    if isinstance(name_dict, dict):
        genre = name_dict.get("en") or name_dict.get("es") or name_dict.get("ja-ro") or ""
        if not genre:
            # Si no hay idioma preferido, tomar el primer valor disponible
            for lang_val in name_dict.values():
                if isinstance(lang_val, str) and lang_val:
                    genre = lang_val
                    break
        return genre

    # Fallback: si name es un string directo (formato antiguo)
    direct_name = attrs.get("name")
    if isinstance(direct_name, str) and direct_name:
        return direct_name

    return ""


def _extract_title(title_field: dict | str, alt_titles: list) -> str:
    """Extrae el titulo principal de un manga desde la API de MangaDex.

    Prioridad: en > es > ja-ro > primer altTitle con idioma legible > fallback

    La API puede devolver 'title' como:
    - dict con idiomas: {"en": "Solo Leveling", "ko-ro": "..."}
    - dict vacio o sin 'en': {} o {"ko-ro": "..."}
    - string directo: "Some Title"

    Si no hay titulo en el campo principal, busca en altTitles.
    """
    # Caso 1: title es un string directo
    if isinstance(title_field, str) and title_field.strip():
        return title_field

    # Caso 2: title es un dict con idiomas
    if isinstance(title_field, dict):
        # Prioridad de idiomas
        for lang in ["en", "es", "ja-ro"]:
            val = title_field.get(lang, "")
            if isinstance(val, str) and val.strip():
                return val.strip()

        # Si no hay idioma preferido, tomar el primer valor string disponible
        for val in title_field.values():
            if isinstance(val, str) and val.strip():
                return val.strip()

    # Caso 3: Buscar en altTitles (lista de dicts con idiomas)
    if isinstance(alt_titles, list):
        for at in alt_titles:
            if not isinstance(at, dict):
                continue
            # Prioridad: en > es > primer idioma disponible
            for lang in ["en", "es"]:
                val = at.get(lang, "")
                if isinstance(val, str) and val.strip():
                    return val.strip()
            # Fallback: primer valor string
            for val in at.values():
                if isinstance(val, str) and val.strip():
                    return val.strip()

    return ""


def _is_genre_tag(tag_data: dict) -> bool:
    """Determina si un tag es un genero real (no formato, contenido, etc.)."""
    if not isinstance(tag_data, dict):
        return False

    attrs = tag_data.get("attributes", {})
    if not isinstance(attrs, dict):
        return False

    group = attrs.get("group", "")
    # Solo tags con group="genre" son generos reales
    return group == "genre"


def _parse_manga_list(manga_list: list, limit: int = 20) -> List[dict]:
    """Parsea una lista de mangas desde la API de MangaDex."""
    results = []

    for item in manga_list[:limit]:
        attributes = item.get("attributes", {})
        manga_id = item.get("id")

        # Get cover art URL if available
        # NOTE: field is "fileName" (camelCase), NOT "filename"
        cover_url = ""
        relationships = item.get("relationships", [])
        for rel in relationships:
            if rel.get("type") == "cover_art":
                media_attributes = rel.get("attributes", {})
                # Fix: use fileName (camelCase) not filename
                cover_filename = media_attributes.get("fileName") or media_attributes.get("filename")
                if cover_filename:
                    cover_url = _cover_url(manga_id, cover_filename)
                break

        # Get alternative titles and extract main title
        alt_titles = attributes.get("altTitles", []) or []
        main_title = _extract_title(attributes.get("title", {}), alt_titles)

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

        # Get genres/tags - only actual genre tags (group="genre"), not format/content/etc.
        genres = []
        tags = attributes.get("tags", [])
        for tag in tags[:10]:  # Check more tags to find up to 5 genres
            if _is_genre_tag(tag):
                genre = _extract_genre_name(tag)
                if genre and len(genres) < 5:
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

        response = _request_with_retry(
            f"{API_BASE}/manga",
            params=params,
            timeout=20,
        )
        if not response:
            return []

        data = response.json()

        manga_list = data.get("data") or []
        logger.info(f"MangaDex search: Found {len(manga_list)} results for '{query}'")

        for item in manga_list[:limit]:
            attributes = item.get("attributes", {})
            manga_id = item.get("id")

            # Get cover art URL if available
            # NOTE: field is "fileName" (camelCase), NOT "filename"
            cover_url = ""
            relationships = item.get("relationships", [])
            for rel in relationships:
                if rel.get("type") == "cover_art":
                    media_attributes = rel.get("attributes", {})
                    # Fix: use fileName (camelCase) not filename
                    cover_filename = media_attributes.get("fileName") or media_attributes.get("filename")
                    if cover_filename:
                        cover_url = _cover_url(manga_id, cover_filename)
                    break

            # Get alternative titles and extract main title using improved parser
            alt_titles = attributes.get("altTitles", []) or []
            main_title = _extract_title(attributes.get("title", {}), alt_titles)

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

            # Get genres/tags - only actual genre tags (group="genre"), not format/content/etc.
            genres = []
            tags = attributes.get("tags", [])
            for tag in tags[:10]:  # Check more tags to find up to 5 genres
                if _is_genre_tag(tag):
                    genre = _extract_genre_name(tag)
                    if genre and len(genres) < 5:
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


def _fetch_person_name(person_id: str, role: str = "author") -> Optional[str]:
    """Fetches author/artist name from the appropriate endpoint.

    MangaDex has separate endpoints for authors and artists:
    - /author/{id} for creators with role 'writer'/'story'/'art'
    - /artist/{id} for illustrators

    The manga detail relationship only returns {id, type} without attributes.
    We need to call the correct endpoint based on the role.
    """
    cache_key = f"mangadex:{role}:{person_id}"
    cached = base._cache_get(cache_key)
    if cached:
        return cached

    try:
        # Try /author/{id} first, then /artist/{id} as fallback
        for endpoint in [f"{API_BASE}/{role}/{person_id}", f"{API_BASE}/artist/{person_id}" if role == "author" else None]:
            if not endpoint:
                continue
            try:
                response = _request_with_retry(endpoint, timeout=10)
                if response and response.status_code == 200:
                    data = response.json()
                    person_data = data.get("data", {})
                    attrs = person_data.get("attributes", {})
                    name = attrs.get("name", "")

                    if name:
                        base._cache_set(cache_key, name)
                        return name
            except Exception:
                continue  # Try next endpoint

        logger.debug(f"Failed to fetch {role} name for {person_id}")
    except Exception as exc:
        logger.debug(f"Error fetching {role} {person_id}: {exc}")

    return None


def _fetch_author_name(author_id: str) -> Optional[str]:
    """Fetches author (writer/story) name from the author endpoint."""
    return _fetch_person_name(author_id, role="author")


def _fetch_artist_name(artist_id: str) -> Optional[str]:
    """Fetches artist (illustrator) name from the artist endpoint."""
    return _fetch_person_name(artist_id, role="artist")


def _get_manga_details(manga_id: str) -> Optional[dict]:
    """Obtiene detalles completos de un manga por su ID."""
    # Check cache first
    cache_key = f"mangadex:v2:manga:{manga_id}"
    cached = base._cache_get(cache_key)
    if cached:
        logger.debug(f"MangaDex cache hit for manga: {manga_id}")
        return cached

    try:
        # Fetch manga details with chapters using individual endpoint
        response = _request_with_retry(
            f"{API_BASE}/manga/{manga_id}",
            params=[
                ("includes[]", "author"),
                ("includes[]", "artist"),
                ("includes[]", "cover_art"),
            ],
            timeout=20,
        )
        if not response:
            return None

        data = response.json()

        item = data.get("data")
        if not item:
            return None

        attributes = item.get("attributes", {})

        # Get title using improved parser (handles empty/non-English dicts + altTitles fallback)
        raw_title = attributes.get("title") or {}
        alt_titles = attributes.get("altTitles") or []
        main_title = _extract_title(raw_title, alt_titles) or "Sin titulo"

        # Get description
        desc_key = None
        for key in ["en", "es"]:
            if attributes.get("description", {}).get(key):
                desc_key = key
                break

        description = ""
        if desc_key:
            description = attributes["description"].get(desc_key, "")[:1000]

        # Get authors and artists - need to fetch names from /person/{id} endpoint
        author_ids = []
        artist_ids = []
        authors = []
        artists = []
        relationships = item.get("relationships", [])
        for rel in relationships:
            rel_type = rel.get("type")
            rel_name = (rel.get("attributes") or {}).get("name") or ""
            if rel_type == "author":
                aid = rel.get("id")
                if rel_name and rel_name not in authors:
                    authors.append(rel_name)
                elif aid and aid not in author_ids:
                    author_ids.append(aid)
            elif rel_type == "artist":
                art_id = rel.get("id")
                if rel_name and rel_name not in artists:
                    artists.append(rel_name)
                elif art_id and art_id not in artist_ids:
                    artist_ids.append(art_id)

        # Fetch names for authors and artists (relationships don't include attributes)
        for aid in author_ids[: max(0, 3 - len(authors))]:
            name = _fetch_author_name(aid) or "Desconocido"
            if name != "Desconocido":
                authors.append(name)

        for art_id in artist_ids[: max(0, 3 - len(artists))]:
            name = _fetch_artist_name(art_id) or "Desconocido"
            if name != "Desconocido":
                artists.append(name)

        all_creators = authors + artists

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

        # Get genres/tags - only actual genre tags (group="genre"), not format/content/etc.
        categories = []
        tags = attributes.get("tags", [])
        for tag in tags[:10]:  # Check more tags to find up to 5 genres
            if _is_genre_tag(tag):
                cat = _extract_genre_name(tag)
                if cat and len(categories) < 5:
                    categories.append(cat)

        # Get cover image - NOTE: field is "fileName" (camelCase), NOT "filename"
        cover_url = ""
        for rel in relationships:
            if rel.get("type") == "cover_art":
                media_attrs = rel.get("attributes", {})
                # Fix: use fileName (camelCase) not filename
                filename = media_attrs.get("fileName") or media_attrs.get("filename")
                if filename:
                    cover_url = _cover_url(manga_id, filename)
                break

        # Fetch chapters for this manga (increased limit)
        chapters = _fetch_chapters(manga_id, limit=200)

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


def _fetch_chapters(manga_id: str, limit: int = 200) -> List[dict]:
    """Obtiene los capitulos de un manga.

    Args:
        manga_id: ID del manga en MangaDex
        limit: Maximo de capitulos a devolver (default 200, antes 100)
    """
    chapters = []

    try:
        params = {
            "limit": min(limit, 100),  # API max per page is 100
            "offset": 0,
            "order[chapter]": "desc",
        }

        response = _request_with_retry(
            f"{API_BASE}/manga/{manga_id}/feed",
            params=params,
            timeout=20,
        )
        if not response:
            return []

        data = response.json()

        chapter_list = data.get("result") == "ok" and (data.get("data") or [])
        logger.info(f"MangaDex chapters: Found {len(chapter_list)} for manga {manga_id}")

        # Limit to requested number of most recent chapters
        for chap in chapter_list[:limit]:
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
        response = _request_with_retry(
            f"{API_BASE}/at-home/server/{chapter_id}",
            headers=HEADERS,
            timeout=20,
        )
        if not response:
            return []

        data = response.json()

        result_ok = data.get("result") == "ok"
        if not result_ok:
            logger.warning(f"MangaDex returned non-ok result for chapter {chapter_id}")
            return []

        # MangaDex API structure: baseUrl at root, images in chapter.data
        base_url = data.get("baseUrl", "")
        chapter_data = data.get("chapter", {})

        # The official API returns images as chapter.data (list of filenames)
        # Some older responses may use chapter.images
        images_data = chapter_data.get("data") or chapter_data.get("images", [])

        if not base_url:
            logger.warning(f"MangaDex no baseUrl found for chapter {chapter_id}")
            return []

        if not images_data or not isinstance(images_data, list):
            logger.warning(f"MangaDex no valid images data for chapter {chapter_id}: type={type(images_data)}")
            return []

        # Filter out empty strings and build image URLs
        hash_id = chapter_data.get("hash", "")
        image_urls = [
            f"{base_url}/data/{hash_id}/{img}"
            for img in images_data
            if isinstance(img, str) and img.strip()
        ]

        if not image_urls:
            logger.warning(f"MangaDex built 0 image URLs from {len(images_data)} entries for chapter {chapter_id}")
            return []

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
