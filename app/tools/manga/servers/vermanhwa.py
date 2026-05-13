import json
import logging
import re
from html import unescape
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from app.tools.manga import base

logger = logging.getLogger("manga_tool")

# Server-specific configuration
BASE_URL = "https://vermanhwa.com"
CDN_BASE = "https://cdn4.vermanhwa.com"
PLACEHOLDER_IMAGE_MARKERS = ("dflazy", "placeholder", "blank.", "loading", "logo")


def _absolute_url(url: str) -> str:
    if not url:
        return ""
    return urljoin(BASE_URL, unescape(url.strip()))


def _clean_text(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value or "", flags=re.DOTALL | re.IGNORECASE)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.DOTALL | re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _is_placeholder_image(url: str) -> bool:
    lowered = (url or "").lower()
    return not lowered or any(marker in lowered for marker in PLACEHOLDER_IMAGE_MARKERS)


def _image_candidates(html: str) -> List[str]:
    candidates = []

    for img_tag in re.findall(r"<img\b[^>]*>", html or "", re.DOTALL | re.IGNORECASE):
        srcset_match = re.search(r"(?:data-srcset|srcset)=['\"]([^'\"]+)['\"]", img_tag, re.IGNORECASE)
        if srcset_match:
            for src_part in srcset_match.group(1).split(","):
                candidates.append(src_part.strip().split(" ")[0])

        for attr in ("data-src", "data-lazy-src", "data-original", "data-cfsrc", "src"):
            match = re.search(rf"{attr}=['\"]([^'\"]+)['\"]", img_tag, re.IGNORECASE)
            if match:
                candidates.append(match.group(1))

    candidates.extend(
        re.findall(
            r'(?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)["\']',
            html or "",
            re.IGNORECASE,
        )
    )
    candidates.extend(
        re.findall(
            r'(https?://[^"\'>\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\'>\s]*)?)',
            html or "",
            re.IGNORECASE,
        )
    )

    seen = set()
    clean_urls = []
    for candidate in candidates:
        url = _absolute_url(candidate).strip()
        lowered = url.lower()
        if (
            url
            and url not in seen
            and not _is_placeholder_image(url)
            and any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".webp"))
        ):
            seen.add(url)
            clean_urls.append(url)

    return clean_urls


def _first_image(html: str) -> str:
    images = _image_candidates(html)
    return images[0] if images else ""


def _title_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("-", " ").split())


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
        ajax_response = requests.post(
            f"{BASE_URL}/wp-admin/admin-ajax.php",
            data={"action": "wp-manga-search-manga", "title": query},
            headers=base._get_headers(),
            timeout=20,
        )
        if "application/json" in (ajax_response.headers.get("content-type") or ""):
            payload = ajax_response.json()
            ajax_items = payload.get("data") if payload.get("success") else []
            for item in ajax_items or []:
                url = item.get("url") or ""
                slug = _slug_from_url(url)
                if not slug:
                    continue

                detail = _get_manga_by_url(_manga_url(slug))
                results.append({
                    "title": (detail or {}).get("title") or item.get("title") or _title_from_slug(slug),
                    "url": _manga_url(slug),
                    "image": (detail or {}).get("image") or "",
                    "type": (detail or {}).get("type") or item.get("type") or "manhwa",
                    "status": (detail or {}).get("status") or "",
                    "chapters_count": len((detail or {}).get("chapters") or []),
                })

                if len(results) >= limit:
                    return results

            if payload.get("success") is False:
                return results

        search_url = f"{BASE_URL}/?s={query}"
        response = requests.get(search_url, headers=base._get_headers(), timeout=20)
        response.raise_for_status()
        if response.url.rstrip("/") == BASE_URL:
            return results
        
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

                link_pos = response.text.find(link)
                chunk = response.text[max(0, link_pos - 2500): link_pos + 4500] if link_pos >= 0 else response.text
                
                # Extract title from the link text or alt attribute
                title_match = re.search(
                    rf'<a[^>]*href=["\']{re.escape(link)}["\'][^>]*>(.*?)</a>',
                    response.text,
                    re.DOTALL | re.IGNORECASE
                )
                title = "Sin titulo"
                if title_match:
                    title_text = title_match.group(1)
                    title = _clean_text(title_text) or "Sin titulo"

                if title == "Sin titulo":
                    attr_title = re.search(r'(?:alt|title)=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
                    if attr_title:
                        title = _clean_text(attr_title.group(1)) or title
                
                image = _first_image(chunk)

                if title == "Sin titulo":
                    title = _title_from_slug(slug)

                # The search page often ships lazy placeholders. For the first
                # visible results, visit the detail page to recover the real cover.
                if (not image or _is_placeholder_image(image)) and len(results) < min(limit, 8):
                    detail = _get_manga_by_url(_manga_url(slug))
                    if detail:
                        image = detail.get("image") or image
                        title = detail.get("title") or title
                
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
            json_data = json.loads(json_ld_match.group(1))
            if isinstance(json_data, dict) and '@graph' in json_data:
                for item in json_data['@graph']:
                    if item.get('@type') == 'Article':
                        title = item.get('headline', title)
                        break
        except Exception:
            pass
    
    # Fallback to page title
    if title == "Sin titulo":
        h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        if h1_match:
            title = _clean_text(h1_match.group(1)) or title

    if title == "Sin titulo":
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            title = title_match.group(1).split(' - ')[0].strip() or title
    
    # Extract description/sinopsis from JSON-LD
    description = ""
    if json_ld_match:
        try:
            json_data = json.loads(json_ld_match.group(1))
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
            json_data = json.loads(json_ld_match.group(1))
            if isinstance(json_data, dict) and '@graph' in json_data:
                for item in json_data['@graph']:
                    if item.get('@type') == 'ImageObject':
                        image = item.get('url', '') or item.get('contentUrl', '')
                        break
        except Exception:
            pass

    if not image or _is_placeholder_image(image):
        meta_match = re.search(
            r'(?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if meta_match:
            image = meta_match.group(1)

    if not image or _is_placeholder_image(image):
        image = _first_image(html)

    image = _absolute_url(image)
    
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
        
        # Extract image URLs from lazy-loaded readers and inline scripts.
        img_urls = _image_candidates(response.text)

        # Filter for actual reader pages, strip whitespace and deduplicate.
        chapter_images = []
        seen = set()
        for raw_url in img_urls:
            url = _absolute_url(raw_url).strip()
            lowered = url.lower()
            if (
                url
                and url not in seen
                and ("cdn" in lowered or "vermanhwa" in lowered)
                and any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".webp"))
                and not any(skip in lowered for skip in ("icon", "button", "ad", "banner", "logo", "avatar"))
            ):
                seen.add(url)
                chapter_images.append(url)
        
        logger.info(f"_get_chapter_images: Found {len(chapter_images)} images for {chapter_url}")
        
        return chapter_images
        
    except Exception as exc:
        logger.error(f"_get_chapter_images error for {chapter_url}: {exc}")
        return []
