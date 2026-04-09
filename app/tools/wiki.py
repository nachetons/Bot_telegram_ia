import html
import logging
import re
from urllib.parse import quote

import requests


logger = logging.getLogger("wiki")

HEADERS = {"User-Agent": "jellyfin-ai-agent-wiki/1.0"}
WIKIPEDIA_API_URL = "https://es.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://es.wikipedia.org/api/rest_v1/page/summary/{}"
WIKIPEDIA_PAGE_URL = "https://es.wikipedia.org/wiki/{}"


def _clean_query(query: str):
    cleaned = (query or "").replace("/wiki", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _strip_html(text: str):
    plain = re.sub(r"<[^>]+>", " ", text or "")
    plain = html.unescape(plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain


def _truncate_text(text: str, limit: int = 900):
    text = (text or "").strip()
    if len(text) <= limit:
        return text

    truncated = text[:limit].rsplit(" ", 1)[0].strip()
    return truncated + "..."


def _normalize_title(text: str):
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _search_candidates(query: str, limit: int = 5):
    response = requests.get(
        WIKIPEDIA_API_URL,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "utf8": 1,
            "format": "json",
        },
        headers=HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("query", {}).get("search", [])


def _summary_from_rest(title: str):
    response = requests.get(
        WIKIPEDIA_SUMMARY_URL.format(quote(title.replace(" ", "_"))),
        headers=HEADERS,
        timeout=10,
    )

    if response.status_code != 200 or not response.text.strip():
        return None

    data = response.json()
    extract = data.get("extract")
    if extract:
        return {
            "title": data.get("title", title),
            "text": _truncate_text(extract),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }

    return None


def _summary_from_extracts(title: str):
    response = requests.get(
        WIKIPEDIA_API_URL,
        params={
            "action": "query",
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "inprop": "url",
            "redirects": 1,
            "titles": title,
            "utf8": 1,
            "format": "json",
        },
        headers=HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None

    page = next(iter(pages.values()))
    extract = page.get("extract")
    if not extract:
        return None

    return {
        "title": page.get("title", title),
        "text": _truncate_text(extract),
        "url": page.get("fullurl") or WIKIPEDIA_PAGE_URL.format(quote(title.replace(" ", "_"))),
    }


def _get_best_summary(query: str):
    candidates = _search_candidates(query)
    if not candidates:
        return None

    query_norm = _normalize_title(query)
    candidates = sorted(
        candidates,
        key=lambda item: (
            _normalize_title(item.get("title")) == query_norm,
            _normalize_title(re.sub(r"\s*\(.+?\)$", "", item.get("title", ""))) == query_norm,
            -abs(len(_normalize_title(item.get("title"))) - len(query_norm)),
        ),
        reverse=True,
    )

    for candidate in candidates:
        title = candidate.get("title")
        if not title:
            continue

        try:
            summary = _summary_from_rest(title)
            if not summary:
                summary = _summary_from_extracts(title)
        except requests.RequestException as exc:
            logger.warning("Wikipedia summary failed for '%s': %s", title, exc)
            continue

        if not summary or not summary.get("text"):
            continue

        text = summary["text"]
        lower_text = text.lower()
        if "puede referirse a" in lower_text or "puede hacer referencia a" in lower_text:
            continue

        return summary

    return None


def wikipedia(query):
    cleaned_query = _clean_query(query)
    logger.info("Wikipedia search for: %s", cleaned_query)

    if not cleaned_query:
        return "", []

    try:
        summary = _get_best_summary(cleaned_query)
        if not summary:
            logger.info("No Wikipedia summary found for: %s", cleaned_query)
            return "", []

        title = summary.get("title")
        text = _strip_html(summary.get("text"))
        url = summary.get("url")

        if title and not text.lower().startswith(title.lower()):
            text = f"{title}\n\n{text}"

        if url:
            text = f"{text}\n\nMás info: {url}"

        return text.strip(), ["wikipedia"]

    except requests.RequestException as exc:
        logger.warning("Wikipedia request failed: %s", exc)
        return "", []
    except Exception as exc:
        logger.warning("Unexpected wiki error: %s", exc)
        return "", []
