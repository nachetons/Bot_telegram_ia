import logging
import re
import unicodedata

import requests


logger = logging.getLogger("weather")

USER_AGENT = "jellyfin-ai-agent-weather/1.0"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_PATTERNS = [
    r"\bque tiempo hace en\b",
    r"\bque tiempo hace\b",
    r"\bque clima hace en\b",
    r"\bque clima hace\b",
    r"\bque tal el tiempo en\b",
    r"\bque tal el tiempo\b",
    r"\bel tiempo en\b",
    r"\bclima en\b",
    r"\bclima de\b",
    r"\btiempo en\b",
    r"\bweather in\b",
    r"\bweather at\b",
    r"\bforecast for\b",
    r"\bforecast in\b",
    r"\bprevision en\b",
    r"\btemperatura en\b",
]

TIME_PATTERNS = [
    r"\bhoy\b",
    r"\bmanana\b",
    r"\bmañana\b",
    r"\bahora\b",
    r"\besta semana\b",
    r"\beste fin de semana\b",
]


def _strip_accents(text: str):
    text = unicodedata.normalize("NFD", text or "")
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def _normalize_for_matching(text: str):
    text = _strip_accents((text or "").lower())
    text = re.sub(r"[^\w\s,.-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_location(query: str):
    original = (query or "").strip()
    original = re.sub(r"^/(tiempo|weather)\b", " ", original, flags=re.IGNORECASE)

    cleaned = _normalize_for_matching(original)

    for pattern in WEATHER_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned)

    for pattern in TIME_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned)

    cleaned = re.sub(r"^(en|de|del|para)\b\s+", "", cleaned)
    cleaned = re.sub(r"\b(de|del|en|para)\b\s*$", " ", cleaned)
    cleaned = re.sub(r"^[,.\-\s]+|[,.\-\s]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def _build_geocode_queries(query: str):
    cleaned = clean_location(query)
    queries = []

    for candidate in [cleaned, _normalize_for_matching(query), (query or "").strip()]:
        candidate = (candidate or "").strip(" ,.-")
        if candidate and candidate not in queries:
            queries.append(candidate)

    return queries


def _score_geocode_result(candidate_query: str, item: dict):
    query_norm = _normalize_for_matching(candidate_query)
    display_name = item.get("display_name", "")
    display_norm = _normalize_for_matching(display_name)
    importance = float(item.get("importance") or 0)

    score = importance * 100

    if display_norm.startswith(query_norm):
        score += 80
    elif f"{query_norm}," in display_norm or f" {query_norm}," in display_norm:
        score += 50
    elif query_norm and query_norm in display_norm:
        score += 25

    query_tokens = [token for token in query_norm.split() if len(token) > 1]
    token_hits = sum(1 for token in query_tokens if token in display_norm)
    score += token_hits * 10

    place_rank = int(item.get("place_rank") or 0)
    if place_rank:
        score += max(0, 30 - abs(place_rank - 16))

    score -= max(0, len(display_norm) - len(query_norm)) * 0.1
    return score


def _geocode(candidate_query: str, countrycodes=None):
    params = {
        "q": candidate_query,
        "format": "jsonv2",
        "limit": 3,
        "addressdetails": 1,
    }

    if countrycodes:
        params["countrycodes"] = countrycodes

    response = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def geocode_city(query: str):
    candidates = _build_geocode_queries(query)

    if not candidates:
        return None

    search_strategies = [
        {"countrycodes": "es"},
        {"countrycodes": None},
    ]

    for candidate in candidates:
        for strategy in search_strategies:
            try:
                data = _geocode(candidate, strategy["countrycodes"])
            except requests.RequestException as exc:
                logger.warning("Geocoding failed for '%s': %s", candidate, exc)
                continue

            if not data:
                continue

            best = max(data, key=lambda item: _score_geocode_result(candidate, item))
            return {
                "name": best.get("display_name", candidate),
                "lat": float(best["lat"]),
                "lon": float(best["lon"]),
            }

    return None


def get_weather(query: str):
    try:
        geo = geocode_city(query)
        if not geo:
            return "No encontré esa ubicación. Prueba con una ciudad, provincia o comunidad autónoma.", []

        response = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": geo["lat"],
                "longitude": geo["lon"],
                "current": "temperature_2m,apparent_temperature,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        response.raise_for_status()

        payload = response.json()
        current = payload.get("current", {})
        daily = payload.get("daily", {})

        lines = [f"🌤 Clima en {geo['name']}", ""]

        if current:
            lines.extend(
                [
                    "Ahora:",
                    f"- Temp actual: {current.get('temperature_2m', '--')}°C",
                    f"- Sensación térmica: {current.get('apparent_temperature', '--')}°C",
                ]
            )

        lines.extend(
            [
                "",
                "Hoy:",
                f"- Temp max: {daily.get('temperature_2m_max', ['--'])[0]}°C",
                f"- Temp min: {daily.get('temperature_2m_min', ['--'])[0]}°C",
                f"- Prob. lluvia: {daily.get('precipitation_probability_max', ['--'])[0]}%",
            ]
        )

        text = "\n".join(lines).strip()
        return text, ["open-meteo", "nominatim"]

    except requests.RequestException as exc:
        logger.warning("Weather request failed: %s", exc)
        return "No se pudo obtener el clima ahora mismo.", []
    except Exception as exc:
        logger.warning("Unexpected weather error: %s", exc)
        return "No se pudo obtener el clima.", []
