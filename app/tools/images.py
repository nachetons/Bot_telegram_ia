import logging
import re
from urllib.parse import quote, urlparse

import requests


logger = logging.getLogger("images")

HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 8


def _extract_vqd(html: str):
    patterns = [
        r'vqd="([^"]+)"',
        r"vqd=([0-9-]+)&",
        r"'vqd':'([^']+)'",
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)

    return None


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_text(value: str):
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def _image_signature(url: str):
    parsed = urlparse(url or "")
    path = parsed.path.lower()
    path = re.sub(r"\.(jpg|jpeg|png|webp|gif)$", "", path)
    path = re.sub(r"[-_]+", " ", path)
    path = re.sub(r"\d+", "", path)
    return _normalize_text(path)


def _normalize_result(item):
    image_url = item.get("image") or item.get("thumbnail")
    if not image_url or not image_url.startswith(("http://", "https://")):
        return None

    source_url = item.get("url") or item.get("source") or item.get("origin")
    title = (item.get("title") or item.get("caption") or "").strip()
    width = _safe_int(item.get("width"))
    height = _safe_int(item.get("height"))
    domain = urlparse(source_url).netloc if source_url else ""

    return {
        "image_url": image_url,
        "thumbnail_url": item.get("thumbnail") or image_url,
        "source_url": source_url,
        "source_domain": domain.replace("www.", ""),
        "title": title,
        "width": width,
        "height": height,
    }


def _score_result(result):
    area = result["width"] * result["height"]

    return (
        result["image_url"].startswith("https://"),
        area >= 1280 * 720,
        area,
        bool(result["title"]),
        bool(result["source_url"]),
        len(result["image_url"]),
    )


def _is_duplicate_result(result, seen_keys):
    exact_key = (result["image_url"], result["source_url"])
    if exact_key in seen_keys:
        return True

    title_key = _normalize_text(result["title"])
    title_domain_key = (title_key, result["source_domain"])
    if title_key and title_domain_key in seen_keys:
        return True

    image_key = _image_signature(result["image_url"])
    image_domain_key = (image_key, result["source_domain"])
    if image_key and image_domain_key in seen_keys:
        return True

    return False


def _remember_result_keys(result, seen_keys):
    seen_keys.add((result["image_url"], result["source_url"]))

    title_key = _normalize_text(result["title"])
    if title_key:
        seen_keys.add((title_key, result["source_domain"]))

    image_key = _image_signature(result["image_url"])
    if image_key:
        seen_keys.add((image_key, result["source_domain"]))


def get_images(query: str, limit: int = 5):
    query = (query or "").strip()
    if not query:
        return []

    try:
        encoded_query = quote(query)
        search_url = f"https://duckduckgo.com/?q={encoded_query}&iax=images&ia=images"

        response = requests.get(search_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        vqd = _extract_vqd(response.text)
        if not vqd:
            logger.warning("DuckDuckGo did not return vqd token for query: %s", query)
            return []

        ajax_url = (
            "https://duckduckgo.com/i.js"
            f"?l=us-en&o=json&q={encoded_query}&vqd={vqd}&f=,,,&p=1&s=0"
        )

        ajax_response = requests.get(ajax_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        ajax_response.raise_for_status()
        data = ajax_response.json()

        seen_keys = set()
        results = []

        for raw_item in data.get("results", []):
            result = _normalize_result(raw_item)
            if not result:
                continue

            if _is_duplicate_result(result, seen_keys):
                continue

            _remember_result_keys(result, seen_keys)
            results.append(result)

        results.sort(key=_score_result, reverse=True)
        return results[:limit]

    except Exception as exc:
        logger.warning("Image search failed for query '%s': %s", query, exc)
        return []
