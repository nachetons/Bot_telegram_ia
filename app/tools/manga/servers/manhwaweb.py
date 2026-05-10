import json
import logging
import re
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import requests

from app.tools.manga import base

logger = logging.getLogger("manga_tool")

# Server-specific configuration
BASE_URL = "https://www.manhwaweb.com"
API_BASE = "https://manhwawebbackend-production.up.railway.app"
LIBRARY_URL = f"{API_BASE}/manhwa/library"

# Genre mapping from website HTML (ID -> name)
GENRE_MAP = {
    3: "Acción", 29: "Aventura", 18: "Comedia", 1: "Drama",
    42: "Recuentos de la vida", 2: "Romance", 5: "Venganza", 6: "Harem",
    23: "Fantasía", 31: "Sobrenatural", 25: "Tragedia", 43: "Psicológico",
    32: "Horror", 44: "Thriller", 28: "Historias cortas", 30: "Ecchi",
    34: "Gore", 27: "Girls love", 45: "Boys love", 41: "Reencarnación",
    37: "Sistema de niveles", 33: "Ciencia ficción", 38: "Apocalíptico",
    39: "Artes marciales", 40: "Superpoderes", 35: "Cultivación (cultivo)",
    8: "Milf"
}


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


def _normalize_genre_ids(raw_ids) -> list:
    """Extrae IDs enteros de una lista que puede contener ints o dicts.
    
    El API puede devolver generos como [2, 5] o como [{"id": 2}, {"id": 5}].
    Normaliza ambos formatos a una lista de ints validos para GENRE_MAP.
    """
    if not raw_ids:
        return []
    
    normalized = []
    for item in raw_ids:
        if isinstance(item, int):
            normalized.append(item)
        elif isinstance(item, dict):
            gid = item.get("id") or item.get("_id") or item.get("genre_id")
            if isinstance(gid, int):
                normalized.append(gid)
    return normalized


def _filter_results(results: List[dict], filters: dict) -> List[dict]:
    """Aplica filtros del lado del cliente.
    
    Args:
        results: Lista de items desde la API (ya convertidos via _item_to_manga)
        filters: Diccionario con filtros aplicados:
            - tipo: str (manhwa, manga, manhua, doujinshi, novela, one_shot)
            - estado: str (publicandose, pausado, finalizado)
            - demografia: str (seinen, shonen, josei, shojo)
            - erotico: str (si, no)
            - genero: int (ID del genero)
    
    Returns:
        Lista filtrada de items
    
    Nota: Los campos en 'results' fueron extendidos por _item_to_manga():
        - '_tipo' -> 'type'
        - '_status' -> 'status'
        - '_demografi', '_erotico', '_categoris' se preservan para filtrado
    """
    if not results or not filters:
        return results
    
    filtered = []
    
    for item in results:
        # Filter by tipo (campo convertido a 'type')
        item_tipo = (item.get("type") or "").lower()
        filter_tipo = filters.get("tipo", "")
        if filter_tipo and item_tipo != filter_tipo.lower():
            continue
        
        # Filter by estado (campo se mantiene como 'status')
        item_status = (item.get("status") or "").lower()
        filter_estado = filters.get("estado", "")
        if filter_estado and item_status != filter_estado.lower():
            continue
        
        # Filter by demografia (_demografi preservado por _item_to_manga)
        item_demo = (item.get("_demografi") or "").lower()
        filter_demografia = filters.get("demografia", "")
        if filter_demografia and item_demo != filter_demografia.lower():
            continue
        
        # Filter by erotico (_erotico preservado por _item_to_manga)
        item_erotic = (item.get("_erotico") or "").lower()
        filter_erotico = filters.get("erotico", "")
        if filter_erotico and item_erotic != filter_erotico.lower():
            continue
        
        # Filter by genero (genre ID) - _categoris preservado por _item_to_manga
        filter_genero = filters.get("genero")
        if filter_genero is not None:
            item_genres = item.get("_categoris", []) or []
            if isinstance(item_genres, str):
                try:
                    item_genres = json.loads(item_genres)
                except (json.JSONDecodeError, TypeError):
                    item_genres = []
            if filter_genero not in item_genres:
                continue
        
        filtered.append(item)
    
    return filtered


def _sort_results(results: List[dict], order_item: str) -> List[dict]:
    """Aplica ordenamiento del lado del cliente.
    
    La API de Manhwaweb ignora el parametro order_item, asi que aqui
    reordenamos los resultados segun el criterio solicitado usando
    los campos disponibles (_status, the_real_name, _numero_cap, etc).
    """
    if not results:
        return results
    
    if order_item == "alfabetico":
        # Orden alfabetico por titulo
        return sorted(
            results,
            key=lambda x: (x.get("title") or "").lower(),
        )
    
    elif order_item in ("view_count", "popular"):
        # La API no proporciona view_count. Fallback: priorizar lo que esta
        # "publicandose" y luego ordenar alfabeticamente para variedad.
        status_priority = {"publicandose": 0, "pausado": 1, "finalizado": 2, "desconocido": 3}
        return sorted(
            results,
            key=lambda x: (status_priority.get(x.get("status") or "desconocido", 4), (x.get("title") or "").lower()),
        )
    
    elif order_item in ("rate_avg", "rated"):
        # La API no proporciona rate_avg. Fallback diferente: priorizar los que
        # tienen mas capitulos (suelen ser mas populares/bien valorados) y luego
        # por estado de publicacion.
        def rating_key(x):
            status = x.get("status") or "desconocido"
            chapters = x.get("chapters_count") or 0
            try:
                chap_num = float(chapters) if chapters else 0
            except (ValueError, TypeError):
                chap_num = 0
            # Priorizar: mas capitulos > estado publicacion > titulo
            return (-chap_num, {"publicandose": 0, "pausado": 1, "finalizado": 2, "desconocido": 3}.get(status, 4), (x.get("title") or "").lower())
        
        return sorted(results, key=rating_key)
    
    elif order_item in ("timestamp", "newest"):
        # Orden por estado de publicacion: publicandose > pausado > finalizado
        status_priority = {"publicandose": 0, "pausado": 1, "finalizado": 2, "desconocido": 3}
        return sorted(
            results,
            key=lambda x: (status_priority.get(x.get("status") or "desconocido", 4), (x.get("title") or "").lower()),
        )
    
    # Si no reconoce el order_item, retorna sin ordenar
    return results


def _library_request(query: str = "", manga_type: str = "", order_item: str = "alfabetico", 
                     limit: int = 20, filters: dict = None) -> List[dict]:
    """Solicita items de la biblioteca Manhwaweb.
    
    Nota: La API ignora la mayoria de parametros de filtro, por lo que se aplica
    filtrado y ordenamiento del lado del cliente.
    
    Args:
        query: Texto de busqueda (vacio = lista completa)
        manga_type: Filtro de tipo (manhwa, manga, manhua, doujinshi, novela) - OBSOLETO, usar filters
        order_item: Criterio de orden (alfabetico, view_count, rate_avg, timestamp)
        limit: Maximo de resultados a devolver
        filters: Filtros adicionales del lado del cliente:
            - tipo, estado, demografia, erotico, genero
    
    Returns:
        Lista de diccionarios con informacion de mangas
    """
    results = []
    
    if query:
        # Busqueda especifica: la API filtra por texto, solo necesitamos page 0
        params = {
            "buscar": query,
            "tipo": manga_type or "",
            "order_dir": "desc",
            "page": 0,
        }
        
        try:
            response = requests.get(LIBRARY_URL, params=params, headers=base._get_headers(), timeout=20)
            logger.info(f"_library_request (search): Status {response.status_code}, query='{query}', type='{manga_type}'")
            
            data = response.json()
            manga_list = data.get("data") or []
            logger.info(f"_library_request: Found {len(manga_list)} items in API response (search)")
            
            for item in manga_list:
                manga = base._item_to_manga(item, manga_type)
                if manga:
                    slug_id = item.get("_id") or item.get("real_id")
                    if slug_id:
                        manga["url"] = _manga_url(str(slug_id))
                    manga_status = item.get("_status", "")
                    if manga_status and not manga.get("status"):
                        manga["status"] = manga_status
                    
                    # Parse genre names from IDs (handle both int and dict formats)
                    raw_ids = item.get("_categoris", []) or []
                    if isinstance(raw_ids, str):
                        try:
                            raw_ids = json.loads(raw_ids)
                        except (json.JSONDecodeError, TypeError):
                            raw_ids = []
                    genre_ids = _normalize_genre_ids(raw_ids)
                    manga["categories"] = [GENRE_MAP.get(gid, f"Genero {gid}") for gid in genre_ids if gid in GENRE_MAP]
                    
                    results.append(manga)
            
        except Exception as exc:
            logger.error(f"_library_request error (search): {exc}")
            raise
    
    else:
        # Sin query: fetchear multiples paginas para tener un pool grande
        # y aplicar filtrado/ordenamiento del lado del cliente con variedad real.
        max_pages = 5  # Maximo de paginas a fetchear cuando no hay busqueda (150 items)
        
        for page in range(max_pages):
            params = {
                "buscar": "",
                "tipo": manga_type or "",
                "order_dir": "desc",
                "page": page,
            }
            
            try:
                response = requests.get(LIBRARY_URL, params=params, headers=base._get_headers(), timeout=20)
                
                data = response.json()
                manga_list = data.get("data") or []
                
                if not manga_list:
                    break
                
                for item in manga_list:
                    manga = base._item_to_manga(item, manga_type)
                    if manga:
                        slug_id = item.get("_id") or item.get("real_id")
                        if slug_id:
                            manga["url"] = _manga_url(str(slug_id))
                        manga_status = item.get("_status", "")
                        if manga_status and not manga.get("status"):
                            manga["status"] = manga_status
                        
                        # Parse genre names from IDs (handle both int and dict formats)
                        raw_ids = item.get("_categoris", []) or []
                        if isinstance(raw_ids, str):
                            try:
                                raw_ids = json.loads(raw_ids)
                            except (json.JSONDecodeError, TypeError):
                                raw_ids = []
                        genre_ids = _normalize_genre_ids(raw_ids)
                        manga["categories"] = [GENRE_MAP.get(gid, f"Genero {gid}") for gid in genre_ids if gid in GENRE_MAP]

                        results.append(manga)
                
                # Si esta pagina tiene menos de 30 items, es la ultima
                if len(manga_list) < 30:
                    break
                    
            except Exception as exc:
                logger.error(f"_library_request error (page {page}): {exc}")
                break
        
        logger.info(f"_library_request (catalog): Fetched {len(results)} total items from API")
        
        # Aplicar filtros del lado del cliente si existen
        if filters:
            results = _filter_results(results, filters)
            logger.info(f"_library_request: After filtering: {len(results)} items")
        
        # Aplicar ordenamiento del lado del cliente sobre el pool completo
        results = _sort_results(results, order_item)
        
        # Limitar resultados finales
        results = results[:limit]
    
    return results


def get_available_filters() -> dict:
    """Retorna los filtros disponibles segun la pagina web."""
    return {
        "tipos": ["", "manhwa", "manga", "manhua", "doujinshi", "novela", "one_shot"],
        "estados": ["", "publicandose", "pausado", "finalizado"],
        "demografias": ["", "seinen", "shonen", "josei", "shojo"],
        "eroticos": ["", "si", "no"],
        "generos": GENRE_MAP,
    }


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
    
    # Parse categories - _categoris puede contener ints o dicts con campo "id"
    raw_ids = data.get("_categoris", []) or []
    if isinstance(raw_ids, str):
        try:
            raw_ids = json.loads(raw_ids)
        except (json.JSONDecodeError, TypeError):
            raw_ids = []
    
    genre_ids = _normalize_genre_ids(raw_ids)
    categories = [GENRE_MAP.get(gid, f"Genero {gid}") for gid in genre_ids if gid in GENRE_MAP]

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
    """Extrae las URLs de imágenes de un capítulo haciendo scraping de la página.
    
    La API no proporciona las imágenes reales en los capítulos, asi que
    hacemos scraping directo de la pagina del capitulo para extraerlas.
    Si el scraping falla (SPA), fallback a thumbnails via API + weserv proxy.
    """
    # Try scraping the chapter page first
    try:
        response = requests.get(chapter_url, headers=base._get_headers(), timeout=20)
        response.raise_for_status()
        
        # Extract image URLs from multiple sources (lazy loading, srcset, etc.)
        img_urls = re.findall(
            r'<img[^>]*(?:src|data-src|data-lazy-src|data-original)=["\']([^"\']+)',
            response.text
        )
        
        # Also try to find image URLs in script tags (common for lazy-loaded manga sites)
        script_urls = re.findall(
            r'(https?://[^"\'>\s]+\.(?:jpg|jpeg|png|webp|gif))(?=["\'\s<])',
            response.text
        )
        img_urls.extend(script_urls)
        
        # Deduplicate while preserving order
        seen = set()
        unique_urls = []
        for url in img_urls:
            url = url.strip().rstrip('.')
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Filter for actual manga images (jpg, png, webp) - exclude icons, buttons, etc.
        chapter_images = [
            u for u in unique_urls 
            if any(ext in u.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp'])
            and not any(skip in u.lower() for skip in ['icon', 'button', 'ad', 'banner', 'logo', 'avatar'])
        ]
        
        # Convert relative URLs to absolute
        base_domain = "https://www.manhwaweb.com"
        chapter_images = [
            u if u.startswith('http') else f"{base_domain}{u}" 
            for u in chapter_images
        ]
        
        if chapter_images:
            logger.info(f"_get_chapter_images: Found {len(chapter_images)} images via scraping for {chapter_url}")
            return chapter_images
        
    except Exception as exc:
        logger.debug(f"Scraping failed for {chapter_url}: {exc}")
    
    # Fallback: use API thumbnails via weserv proxy (SPA limitation)
    slug_id = _slug_from_url(chapter_url)
    if not slug_id:
        return []
    
    try:
        response = requests.get(
            f"{API_BASE}/manhwa/see/{slug_id}",
            headers=base._get_headers(),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        
        chapters = data.get("chapters") or data.get("chapters_esp") or []
        wanted = _chapter_from_url(chapter_url)
        
        for chapter in chapters:
            if str(chapter.get("number")) == str(wanted):
                img_field = chapter.get("img", []) or []
                
                # Convert thumbnail URLs to weserv proxy URLs
                images = []
                for thumb_url in img_field:
                    if thumb_url and ("http" in thumb_url or "https" in thumb_url):
                        # Use weserv.nl proxy (without https:// as the SPA does)
                        weserv_url = f"https://images.weserv.nl/?url={thumb_url.replace('https://', '')}"
                        images.append(weserv_url)
                
                if images:
                    logger.info(f"_get_chapter_images: Fallback to {len(images)} API thumbnails for chapter {wanted}")
                    return images
        
    except Exception as exc:
        logger.error(f"API fallback error for {chapter_url}: {exc}")
    
    return []
