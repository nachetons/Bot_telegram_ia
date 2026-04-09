import logging
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.config import HEADERS


logger = logging.getLogger("web")

SEARCH_CACHE = {}
CACHE_TTL_SECONDS = 300
MAX_RESULTS = 5


def _cache_get(query: str):
    entry = SEARCH_CACHE.get(query)
    if not entry:
        return None

    if time.time() - entry["timestamp"] > CACHE_TTL_SECONDS:
        SEARCH_CACHE.pop(query, None)
        return None

    return entry["results"]


def _cache_set(query: str, results):
    SEARCH_CACHE[query] = {
        "timestamp": time.time(),
        "results": results,
    }


def _normalize_url(url: str):
    if not url:
        return ""

    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""

    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "duckduckgo.com" in host and path in {"/y.js", "/l/"}:
        return ""

    query_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if not key.lower().startswith(("utm_", "fbclid", "gclid"))
    ]

    cleaned = parsed._replace(
        fragment="",
        query=urlencode(query_params, doseq=True),
    )
    return urlunparse(cleaned)


def _dedupe_results(results):
    deduped = []
    seen = set()

    for result in results:
        url = _normalize_url(result.get("url"))
        if not url or url in seen:
            continue

        seen.add(url)
        deduped.append(
            {
                "title": (result.get("title") or "").strip(),
                "url": url,
                "snippet": (result.get("snippet") or "").strip(),
                "source": result.get("source") or "unknown",
            }
        )

    return deduped[:MAX_RESULTS]


def _request_with_retries(method: str, url: str, **kwargs):
    last_error = None

    for attempt in range(3):
        try:
            response = requests.request(method, url, timeout=10, **kwargs)
            if response.status_code == 429:
                logger.warning("Rate limited by %s on attempt %s", url, attempt + 1)
                time.sleep(0.5 * (attempt + 1))
                continue

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("Search request failed for %s on attempt %s: %s", url, attempt + 1, exc)
            time.sleep(0.5 * (attempt + 1))

    if last_error:
        raise last_error

    raise requests.RequestException(f"Request failed for {url}")


def _search_duckduckgo_html(query: str):
    response = _request_with_retries(
        "post",
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers=HEADERS,
    )

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for item in soup.select(".result"):
        link = item.select_one(".result__a")
        snippet = item.select_one(".result__snippet")
        if not link:
            continue

        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": link.get("href"),
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                "source": "duckduckgo_html",
            }
        )

    return _dedupe_results(results)


def _search_duckduckgo_lite(query: str):
    response = _request_with_retries(
        "get",
        "https://lite.duckduckgo.com/lite/",
        params={"q": query},
        headers=HEADERS,
    )

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for link in soup.select("a[href]"):
        href = link.get("href")
        title = link.get_text(" ", strip=True)
        if not href or not title or href.startswith("/"):
            continue

        results.append(
            {
                "title": title,
                "url": href,
                "snippet": "",
                "source": "duckduckgo_lite",
            }
        )

    return _dedupe_results(results)


def _search_wikipedia(query: str):
    response = _request_with_retries(
        "get",
        "https://es.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": MAX_RESULTS,
            "utf8": 1,
            "format": "json",
        },
        headers=HEADERS,
    )

    data = response.json()
    results = []

    for item in data.get("query", {}).get("search", []):
        title = item.get("title")
        if not title:
            continue

        results.append(
            {
                "title": title,
                "url": f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}",
                "snippet": BeautifulSoup(item.get("snippet", ""), "html.parser").get_text(" ", strip=True),
                "source": "wikipedia_search",
            }
        )

    return _dedupe_results(results)


def search_web_results(query):
    query = (query or "").strip()
    if not query:
        return []

    cached = _cache_get(query)
    if cached is not None:
        logger.info("Using cached search results for: %s", query)
        return cached

    providers = [
        ("duckduckgo_html", _search_duckduckgo_html),
        ("duckduckgo_lite", _search_duckduckgo_lite),
        ("wikipedia_search", _search_wikipedia),
    ]

    for provider_name, provider in providers:
        try:
            results = provider(query)
            if results:
                logger.info("Search provider %s returned %s results for: %s", provider_name, len(results), query)
                _cache_set(query, results)
                return results

            logger.warning("Search provider %s returned no useful results for: %s", provider_name, query)
        except Exception as exc:
            logger.warning("Search provider %s failed for '%s': %s", provider_name, query, exc)

    return []


def search_web(query):
    return [item["url"] for item in search_web_results(query)]
