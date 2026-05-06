import logging
import re
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import requests

from app.tools.manga import base

logger = logging.getLogger("manga_tool")

# Server-specific configuration
BASE_URL = "https://vermanhwa.com"
CDN_BASE = "https://cdn4.vermanhwa.com"


def _slug_from_url(manga_url: str) -> str:
    """Extrae el slug del manga desde la URL."""
    parsed = urlparse(manga_url)
    path = parsed.path
    
    # Pattern: /manga/{slug}/
    if "/manga/" in path:
        slug = path.split("/manga/", 1)[1].strip("/")
        # Remove chapter part if present (e.g., capitulo-6/)
        slug = re.sub(r"/capitulo-\d+/?$", "", slug)
        return slug.strip("/")
    
    return manga_url.strip().split("/")[-1]


def _chapter_from_url(chapter_url: str) -> Optional[str]:
    """Extrae el numero de capitulo desde la URL."""
    parsed = urlparse(chapter_url)
    path = parsed.path
    
    # Pattern: /manga/{slug}/capitulo-{number}/
    match = re.search(r"/capitulo-(\d+)[/\s]*$", path)
    if match:
        return match.group(1)
    
    return None


def _manga_url(slug_id: str) -> str:
    """Construye la URL del manga."""
    return f"{BASE_URL}/manga/{slug_id}/"


def _chapter_url(slug_id: str, chapter_number: str) -> str:
    """Construye la URL del capitulo."""
    return f"{BASE_URL}/manga/{slug_id}/capitulo-{chapter_number}/"


def _search_manga(query: str, limit: int = 20) -> List[dict]:
    """Busca mangas en VerManhwa usando el buscador de WordPress."""
    results = []
    
    try:
        search_url = f"{BASE_URL}/?s={query}"
        response = requests.get(search_url, headers=base._get_headers(), timeout=20)
        response.raise_for_status()
        
        # Extract manga links from search results
        manga_links = re.findall(
            r'<a[^>]*href=["\']([^"\']*?/manga/[^"\']*)["\'][^>]*>',
            response.text,
            re.IGNORECASE
        )
        
        logger.info(f"_search_manga: Found {len(manga_links)} links for '{query}'")
        
        # Extract unique manga slugs (remove chapter parts)
        seen_slugs = set()
        for link in manga_links:
            slug = _slug_from_url(link)
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                
                # Extract title from the link text or alt attribute
                title_match = re.search(
                    rf'<a[^>]*href=["\']{re.escape(link)}["\'][^>]*>(.*?)</a>',
                    response.text,
                    re.DOTALL | re.IGNORECASE
                )
                title = "Sin titulo"
                if title_match:
                    title_text = title_match.group(1)
                    title = re.sub(r'<[^>]+>', '', title_text).strip() or "Sin titulo"
                
                # Extract image from thumbnail or data-src
                img_match = re.search(
                    rf'<a[^>]*href=["\']{re.escape(link)}["\'][^>]*>.*?<img[^>]*src=["\']([^"\']+)["\']',
                    response.text,
                    re.DOTALL | re.IGNORECASE
                )
                image = ""
                if img_match:
                    image = img_match.group(1)
                
                results.append({
                    "title": title,
                    "url": _manga_url(slug),
                    "image": image,
                    "type": "manhwa",
                    "status": "",
                    "chapters_count": 0,
                })
                
                if len(results) >= limit:
                    break
        
        return results
        
    except Exception as exc:
        logger.error(f"_search_manga error for '{query}': {exc}")
        raise


def _get_manga_by_url(manga_url: str) -> Optional[dict]:
    """Obtiene detalles de un manga desde su URL."""
    slug = _slug_from_url(manga_url)
    if not slug:
        return None
    
    # Check cache first
    cache_key = f"vermanhwa:manga:{slug}"
    cached = base._cache_get(cache_key)
    if cached:
        logger.debug(f"Cache hit for manga: {slug}")
        return cached
    
    try:
        response = requests.get(manga_url, headers=base._get_headers(), timeout=20)
        response.raise_for_status()
        
        result = _parse_manga_details(response.text, slug)
        
        # Store in cache
        if result:
            base._cache_set(cache_key, result)
            logger.debug(f"Cached manga: {slug}")
        
        return result
        
    except Exception as exc:
        logger.error("Error fetching manga %s: %s", manga_url, exc)
        return None


def _parse_manga_details(html: str, slug: str) -> dict:
    """Parsea los detalles del manga desde el HTML."""
    # Extract title from JSON-LD or page title
    title = "Sin titulo"
    
    # Try JSON-LD first
    json_ld_match = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL
    )
    if json_ld_match:
        try:
            json_data = __import__('json').loads(json_ld_match.group(1))
            if isinstance(json_data, dict) and '@graph' in json_data:
                for item in json_data['@graph']:
                    if item.get('@type') == 'Article':
                        title = item.get('headline', title)
                        break
        except Exception:
            pass
    
    # Fallback to page title
    if title == "Sin titulo":
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            title = title_match.group(1).split(' - ')[0].strip() or title
    
    # Extract description/sinopsis from JSON-LD
    description = ""
    if json_ld_match:
        try:
            json_data = __import__('json').loads(json_ld_match.group(1))
            if isinstance(json_data, dict) and '@graph' in json_data:
                for item in json_data['@graph']:
                    if item.get('@type') == 'Article':
                        description = item.get('description', '')[:500]
                        break
        except Exception:
            pass
    
    # Extract cover image from JSON-LD or meta tags
    image = ""
    if json_ld_match:
        try:
            json_data = __import__('json').loads(json_ld_match.group(1))
            if isinstance(json_data, dict) and '@graph' in json_data:
                for item in json_data['@graph']:
                    if item.get('@type') == 'ImageObject':
                        image = item.get('url', '') or item.get('contentUrl', '')
                        break
        except Exception:
            pass
    
    # Extract chapters from the chapter list
    chapters = []
    
    # Look for wp-manga-chapter list items
    chapter_items = re.findall(
        r'<li[^>]*class=["\']([^"\']*wp-manga-chapter[^"\']*)["\'][^>]*>(.*?)</li>',
        html,
        re.DOTALL | re.IGNORECASE
    )
    
    for _, content in chapter_items:
        # Extract link and text from each chapter item
        link_match = re.search(r'<a[^>]*href=["\']([^"\']+)[^>]*>(.*?)</a>', content, re.DOTALL)
        if link_match:
            chapter_url = link_match.group(1)
            chapter_text = re.sub(r'<[^>]+>', '', link_match.group(2)).strip()
            
            # Extract chapter number from URL or text
            chap_num = _chapter_from_url(chapter_url)
            if not chap_num:
                num_match = re.search(r'(\d+)', chapter_text)
                if num_match:
                    chap_num = num_match.group(1)
            
            if chap_num:
                chapters.append({
                    "title": f"Capitulo {chap_num}",
                    "number": chap_num,
                    "url": chapter_url,
                })
    
    # Sort chapters by number (descending - newest first)
    chapters.sort(key=lambda item: float(item.get("number") or 0), reverse=True)
    
    return {
        "title": title,
        "description": description,
        "image": image,
        "type": "manhwa",
        "status": "",
        "authors": [],
        "categories": [],
        "chapters": chapters,
        "url": _manga_url(slug),
    }


def _get_chapter_images(chapter_url: str) -> List[str]:
    """Extrae las URLs de imágenes de un capítulo."""
    try:
        response = requests.get(chapter_url, headers=base._get_headers(), timeout=20)
        response.raise_for_status()
        
        # Extract image URLs from the chapter page
        img_urls = re.findall(
            r'<img[^>]*src=["\']([^"\']+)',
            response.text
        )
        
        # Filter for CDN images (vermanhwa chapter images), strip whitespace
        chapter_images = [u.strip() for u in img_urls if 'cdn' in u and ('.jpg' in u or '.png' in u or '.webp' in u)]
        
        logger.info(f"_get_chapter_images: Found {len(chapter_images)} images for {chapter_url}")
        
        return chapter_images
        
    except Exception as exc:
        logger.error(f"_get_chapter_images error for {chapter_url}: {exc}")
        return []
