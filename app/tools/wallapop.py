import logging
from typing import Any
from datetime import datetime
from difflib import SequenceMatcher
import re
import unicodedata
from urllib.parse import urlencode

import requests


logger = logging.getLogger("wallapop")

WALLAPOP_COMPONENTS_URL = "https://api.wallapop.com/api/v3/search/components"
WALLAPOP_RESULTS_URL = "https://api.wallapop.com/api/v3/search"
WALLAPOP_WEB_HOME = "https://es.wallapop.com/"
WALLAPOP_WEB_SEARCH_URL = "https://es.wallapop.com/search"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
REQUEST_TIMEOUT = 12

WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

API_HEADERS = {
    "User-Agent": WEB_HEADERS["User-Agent"],
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
    "Origin": "https://es.wallapop.com",
    "Referer": "https://es.wallapop.com/",
    "X-DeviceOS": "0",
}

GEOCODE_HEADERS = {
    "User-Agent": "AgentBotWallapop/1.0 (Telegram helper for personal use)",
    "Accept": "application/json",
}

ORDER_LABELS = {
    "newest": "Más recientes",
    "price_low_to_high": "Precio ascendente",
    "price_high_to_low": "Precio descendente",
    "closest": "Más cercanos",
    "most_relevance": "Más relevantes",
    "deal_score": "Gangas primero",
}

PUBLIC_ORDER_VALUES = {
    "newest": "newest",
    "price_low_to_high": "price_low_to_high",
    "price_high_to_low": "price_high_to_low",
    "closest": "closest",
    "most_relevance": "most_relevance",
    "deal_score": "most_relevance",
}

CONDITION_LABELS = {
    "any": "Cualquier estado",
    "new": "Nuevo",
    "as_good_as_new": "Como nuevo",
    "in_box": "En su caja",
    "good": "Buen estado / usado",
    "used": "Usado",
}

MIN_SIMILARITY_SCORE = 0.62


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_search_text(value: str):
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _tokenize_search_text(value: str):
    normalized = _normalize_search_text(value)
    if not normalized:
        return []
    return normalized.split()


def _is_significant_token(token: str):
    return len(token) >= 3 or any(ch.isdigit() for ch in token)


def _similarity_score(query: str, title: str):
    normalized_query = _normalize_search_text(query)
    normalized_title = _normalize_search_text(title)
    if not normalized_query or not normalized_title:
        return 0.0

    query_tokens = _tokenize_search_text(query)
    title_tokens = set(_tokenize_search_text(title))
    if not query_tokens:
        return 0.0

    compact_title = normalized_title.replace(" ", "")

    matched_tokens = sum(1 for token in query_tokens if token in title_tokens)
    token_ratio = matched_tokens / len(query_tokens)

    significant_tokens = [token for token in query_tokens if _is_significant_token(token)]
    if significant_tokens:
        matched_significant = sum(1 for token in significant_tokens if token in title_tokens)
        significant_ratio = matched_significant / len(significant_tokens)
    else:
        significant_ratio = token_ratio

    numeric_tokens = [token for token in query_tokens if any(ch.isdigit() for ch in token)]
    if numeric_tokens:
        matched_numeric = sum(1 for token in numeric_tokens if token in compact_title)
        numeric_ratio = matched_numeric / len(numeric_tokens)
    else:
        numeric_ratio = token_ratio

    sequence_ratio = SequenceMatcher(None, normalized_query, normalized_title).ratio()

    score = (
        (token_ratio * 0.35)
        + (significant_ratio * 0.25)
        + (numeric_ratio * 0.25)
        + (sequence_ratio * 0.15)
    )
    return round(score, 4)


def _extract_price(item: dict[str, Any]):
    price_fields = [
        item.get("sale_price"),
        item.get("price"),
        item.get("price_no_shipping"),
        item.get("modified_price"),
    ]

    for value in price_fields:
        if isinstance(value, dict):
            amount = value.get("amount") or value.get("cents")
            if amount is not None:
                parsed = _safe_float(amount)
                if parsed is not None:
                    if parsed > 10000:
                        parsed = parsed / 100
                    return parsed, value.get("currency") or "EUR"
        else:
            parsed = _safe_float(value)
            if parsed is not None:
                return parsed, item.get("currency") or "EUR"

    return None, item.get("currency") or "EUR"


def _extract_image(item: dict[str, Any]):
    image_candidates = []

    for field in ["images", "photos", "pictures"]:
        values = item.get(field)
        if isinstance(values, list):
            image_candidates.extend(values[:3])

    for candidate in image_candidates:
        if isinstance(candidate, str) and candidate.startswith("http"):
            return candidate
        if isinstance(candidate, dict):
            urls = candidate.get("urls")
            if isinstance(urls, dict):
                for key in ["big", "medium", "small", "original"]:
                    value = urls.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return value
            for key in ["original", "big", "medium", "small", "url"]:
                value = candidate.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return value

    for key in ["image", "thumbnail", "picture"]:
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value

    return None


def _extract_location(item: dict[str, Any]):
    location = item.get("location")
    if isinstance(location, dict):
        for key in ["city", "locality", "address", "name"]:
            value = location.get(key)
            if value:
                return str(value)

    user = item.get("user")
    if isinstance(user, dict):
        user_location = user.get("location")
        if isinstance(user_location, dict):
            for key in ["city", "locality", "address", "name"]:
                value = user_location.get(key)
                if value:
                    return str(value)

    return ""


def _extract_region(item: dict[str, Any]):
    location = item.get("location")
    if isinstance(location, dict):
        value = location.get("region") or location.get("region2")
        if value:
            return str(value)
    return ""


def _extract_condition(item: dict[str, Any]):
    candidates = [
        item.get("condition"),
        item.get("item_condition"),
        item.get("status"),
    ]

    for candidate in candidates:
        if candidate:
            lowered = str(candidate).lower()
            if "as_good_as_new" in lowered:
                return "as_good_as_new"
            if "in_box" in lowered:
                return "in_box"
            if "good" in lowered:
                return "good"
            if "new" in lowered or "nuevo" in lowered:
                return "new"
            return "used"

    return "used"


def _extract_url(item: dict[str, Any]):
    direct_url = item.get("url") or item.get("share_url") or item.get("web_url")
    if isinstance(direct_url, str) and direct_url.startswith("http"):
        return direct_url

    slug = item.get("web_slug") or item.get("slug")
    if slug:
        return f"https://es.wallapop.com/item/{slug}"

    item_id = item.get("id") or item.get("item_id")
    if item_id:
        return f"https://es.wallapop.com/item/{item_id}"

    return None


def _extract_description(item: dict[str, Any]):
    description = item.get("description")
    if isinstance(description, str):
        return description.strip()
    return ""


def _extract_flag(item: dict[str, Any], field_name: str):
    value = item.get(field_name)
    if isinstance(value, dict):
        return bool(value.get("flag"))
    return bool(value)


def _extract_shipping(item: dict[str, Any]):
    shipping = item.get("shipping")
    if isinstance(shipping, dict):
        return bool(
            shipping.get("item_is_shippable")
            or shipping.get("user_allows_shipping")
            or shipping.get("allow_shipping")
        )
    return bool(shipping)


def _extract_title(item: dict[str, Any]):
    return item.get("title") or item.get("name") or item.get("description") or "Producto"


def _normalize_items(data: Any):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in ["search_objects", "items", "results", "data", "feed", "cards", "components"]:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _normalize_items(value)
            if nested:
                return nested

    for value in data.values():
        nested = _normalize_items(value)
        if nested:
            return nested

    return []


def _format_wallapop_datetime(timestamp_ms):
    parsed = _safe_float(timestamp_ms)
    if parsed is None:
        return ""

    try:
        return datetime.fromtimestamp(parsed / 1000).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _extract_query_params_from_components(data: dict[str, Any]):
    components = data.get("components", [])
    for component in components:
        if not isinstance(component, dict):
            continue
        if component.get("type") != "search_results":
            continue

        type_data = component.get("type_data") or {}
        query_params = type_data.get("query_params")
        if isinstance(query_params, dict):
            return query_params

    return {}


def geocode_location(location_text: str):
    if not location_text:
        return None

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": location_text, "format": "jsonv2", "limit": 1},
            headers=GEOCODE_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            return None

        best = data[0]
        return {
            "lat": best.get("lat"),
            "lon": best.get("lon"),
            "display_name": best.get("display_name") or location_text,
        }
    except Exception as exc:
        logger.info("Wallapop geocode failed for %s: %s", location_text, exc)
        return None


def _filter_items(items, filters):
    condition = filters.get("condition", "any")
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    query = filters.get("query", "")

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = _extract_title(item)
        price, currency = _extract_price(item)
        url = _extract_url(item)
        if not title or not url:
            continue

        parsed = {
            "id": item.get("id") or item.get("item_id") or title,
            "title": str(title).strip(),
            "price": price,
            "currency": currency,
            "url": url,
            "image": _extract_image(item),
            "location": _extract_location(item),
            "region": _extract_region(item),
            "condition": _extract_condition(item),
            "description": _extract_description(item),
            "created_at": item.get("created_at"),
            "modified_at": item.get("modified_at"),
            "created_label": _format_wallapop_datetime(item.get("created_at")),
            "modified_label": _format_wallapop_datetime(item.get("modified_at")),
            "shipping": _extract_shipping(item),
            "reserved": _extract_flag(item, "reserved"),
            "has_warranty": _extract_flag(item, "has_warranty"),
            "is_refurbished": _extract_flag(item, "is_refurbished"),
            "is_top_profile": _extract_flag(item, "is_top_profile"),
            "views": item.get("views") or item.get("visits"),
            "similarity_score": _similarity_score(query, title),
        }

        if min_price is not None and parsed["price"] is not None and parsed["price"] < min_price:
            continue
        if max_price is not None and parsed["price"] is not None and parsed["price"] > max_price:
            continue
        if query and parsed["similarity_score"] < MIN_SIMILARITY_SCORE:
            continue

        # Wallapop ya aplica el filtro de estado en el endpoint de búsqueda.
        # Muchos resultados no devuelven el campo condition de forma explícita,
        # así que no debemos descartarlos aquí por falta de ese dato.
        if condition != "any" and parsed["condition"] == "used":
            parsed["condition"] = condition

        normalized.append(parsed)

    return normalized


def _price_label(item):
    if item.get("price") is None:
        return "Precio no disponible"
    currency = item.get("currency") or "EUR"
    symbol = "€" if currency.upper() == "EUR" else currency.upper()
    return f"{item['price']:.0f}{symbol}"


def _build_summary(filters, items):
    lines = [f"🛒 Wallapop: {filters.get('query', '')}"]

    active_filters = []
    if filters.get("condition") and filters.get("condition") != "any":
        active_filters.append(CONDITION_LABELS.get(filters["condition"], filters["condition"]))
    if filters.get("min_price") is not None or filters.get("max_price") is not None:
        active_filters.append(f"{filters.get('min_price', 0) or 0}€ - {filters.get('max_price', '∞')}€")
    if filters.get("location_label"):
        radius = filters.get("distance_km")
        if radius:
            active_filters.append(f"{filters['location_label']} ({radius} km)")
        else:
            active_filters.append(filters["location_label"])
    if filters.get("order"):
        active_filters.append(ORDER_LABELS.get(filters["order"], filters["order"]))

    if active_filters:
        lines.append("Filtros: " + " | ".join(active_filters))

    for index, item in enumerate(items[:5], start=1):
        location = f" - {item['location']}" if item.get("location") else ""
        lines.append(f"{index}. {item['title']} - {_price_label(item)}{location}")

    return "\n".join(lines)


def _build_filters_summary(filters):
    active_filters = []
    if filters.get("condition") and filters.get("condition") != "any":
        active_filters.append(CONDITION_LABELS.get(filters["condition"], filters["condition"]))
    if filters.get("min_price") is not None or filters.get("max_price") is not None:
        active_filters.append(f"{filters.get('min_price', 0) or 0}€ - {filters.get('max_price', '∞')}€")
    if filters.get("location_label"):
        radius = filters.get("distance_km")
        if radius:
            active_filters.append(f"{filters['location_label']} ({radius} km)")
        else:
            active_filters.append(filters["location_label"])
    if filters.get("order"):
        active_filters.append(ORDER_LABELS.get(filters["order"], filters["order"]))
    return " | ".join(active_filters)


def build_wallapop_search_url(filters):
    params = {
        "keywords": filters.get("query", ""),
        "order_by": PUBLIC_ORDER_VALUES.get(filters.get("order", "newest"), filters.get("order", "newest")),
    }

    if filters.get("min_price") is not None:
        params["min_sale_price"] = int(filters["min_price"])
    if filters.get("max_price") is not None:
        params["max_sale_price"] = int(filters["max_price"])
    if filters.get("condition") and filters.get("condition") != "any":
        params["condition"] = filters["condition"]
    if filters.get("distance_km"):
        params["distance_in_km"] = int(filters["distance_km"])
    if filters.get("category_id"):
        params["category_id"] = filters["category_id"]

    return f"{WALLAPOP_WEB_SEARCH_URL}?{urlencode(params)}"


def _fallback_result(filters, message=None):
    text_lines = [
        f"🛒 Wallapop: {filters.get('query', '')}",
        "No he podido leer resultados directamente desde Wallapop ahora mismo.",
    ]

    active_filters = []
    if filters.get("condition") and filters.get("condition") != "any":
        active_filters.append(CONDITION_LABELS.get(filters["condition"], filters["condition"]))
    if filters.get("min_price") is not None or filters.get("max_price") is not None:
        active_filters.append(f"{filters.get('min_price', 0) or 0}€ - {filters.get('max_price', '∞')}€")
    if filters.get("location_label"):
        radius = filters.get("distance_km")
        if radius:
            active_filters.append(f"{filters['location_label']} ({radius} km)")
        else:
            active_filters.append(filters["location_label"])
    if filters.get("order"):
        active_filters.append(ORDER_LABELS.get(filters["order"], filters["order"]))

    if active_filters:
        text_lines.append("Filtros preparados: " + " | ".join(active_filters))
    if message:
        text_lines.append(message)

    return {
        "type": "wallapop",
        "text": "\n".join(text_lines),
        "buttons": [[{"text": "🔗 Abrir búsqueda en Wallapop", "url": build_wallapop_search_url(filters)}]],
        "image": None,
        "items": [],
    }


def _bootstrap_wallapop_session():
    session = requests.Session()
    session.headers.update(WEB_HEADERS)

    home_response = session.get(WALLAPOP_WEB_HOME, timeout=REQUEST_TIMEOUT)
    home_response.raise_for_status()

    return session


def _build_api_params(filters):
    requested_order = filters.get("order", "newest")
    api_order = "most_relevance" if requested_order == "deal_score" else requested_order

    params = {
        "keywords": filters.get("query", ""),
        "order_by": api_order,
        "source": "deep_link",
    }

    if filters.get("min_price") is not None:
        params["min_sale_price"] = int(filters["min_price"])
    if filters.get("max_price") is not None:
        params["max_sale_price"] = int(filters["max_price"])
    if filters.get("condition") and filters.get("condition") != "any":
        params["condition"] = filters["condition"]
    if filters.get("distance_km"):
        params["distance_in_km"] = int(filters["distance_km"])
    if filters.get("latitude") and filters.get("longitude"):
        params["latitude"] = filters["latitude"]
        params["longitude"] = filters["longitude"]
    if filters.get("category_id"):
        params["category_id"] = filters["category_id"]

    return params


def search_wallapop(filters, next_page_token=None):
    query = (filters.get("query") or "").strip()
    if not query:
        return {"error": "Necesito un producto para buscar en Wallapop."}

    if filters.get("location_label"):
        geo = geocode_location(filters["location_label"])
        if geo:
            filters["latitude"] = geo["lat"]
            filters["longitude"] = geo["lon"]
            filters["location_label"] = geo.get("display_name") or filters["location_label"]

    params = _build_api_params(filters)

    try:
        session = _bootstrap_wallapop_session()
        api_headers = dict(API_HEADERS)
        api_headers["Referer"] = build_wallapop_search_url(filters)

        if next_page_token:
            result_params = {"next_page": next_page_token}
        else:
            components_response = session.get(
                WALLAPOP_COMPONENTS_URL,
                params=params,
                headers=api_headers,
                timeout=REQUEST_TIMEOUT,
            )
            logger.info("Wallapop GET %s -> %s", components_response.url, components_response.status_code)
            components_response.raise_for_status()
            components_data = components_response.json()
            result_params = _extract_query_params_from_components(components_data) or params

        results_response = session.get(
            WALLAPOP_RESULTS_URL,
            params=result_params,
            headers=api_headers,
            timeout=REQUEST_TIMEOUT,
        )
        logger.info("Wallapop GET %s -> %s", results_response.url, results_response.status_code)
        results_response.raise_for_status()
        data = results_response.json()
    except Exception as exc:
        logger.warning("Wallapop search failed for %s: %s", query, exc)
        return _fallback_result(filters, "He preparado la búsqueda para abrirla directamente en la web.")

    items = _filter_items(_normalize_items(data), filters)
    if not items:
        return _fallback_result(filters, "No he podido extraer listados válidos del resultado.")

    meta = data.get("meta") or {}
    next_page = meta.get("next_page")

    buttons = []
    for index, item in enumerate(items[:5], start=1):
        buttons.append([{"text": f"🔗 {index}. {_price_label(item)}", "url": item["url"]}])

    return {
        "type": "wallapop",
        "text": _build_summary(filters, items),
        "buttons": buttons,
        "image": items[0].get("image"),
        "items": items,
        "next_page": next_page,
        "summary": _build_filters_summary(filters),
        "search_url": build_wallapop_search_url(filters),
    }
