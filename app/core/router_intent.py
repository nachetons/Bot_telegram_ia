import json
import logging
import re

from app.services.llm_client import call_llm
from app.services.llm_client_cloud import call_llm_cloud


logger = logging.getLogger("router_intent")

ALLOWED_INTENTS = {"movies", "images", "weather", "wiki", "search", "library"}
MOVIE_HINTS = (
    "ver",
    "pelicula",
    "película",
    "movie",
    "film",
    "reproduce",
    "reproducir",
    "pon",
    "ponme",
)
MOVIE_INFO_HINTS = (
    "ultimas peliculas",
    "últimas películas",
    "lista de peliculas",
    "lista de películas",
    "filmografia",
    "filmografía",
    "en las que participo",
    "en las que participó",
    "peliculas de",
    "películas de",
    "en que peliculas sale",
    "en qué películas sale",
    "en que peliculas participo",
    "en qué películas participó",
)
WIKI_HINTS = (
    "quien es",
    "quién es",
    "que es",
    "qué es",
    "como se llama",
    "cómo se llama",
    "cual es el nombre de",
    "cuál es el nombre de",
    "que nombre tiene",
    "qué nombre tiene",
    "cuando nacio",
    "cuándo nació",
    "cuando murio",
    "cuándo murió",
    "cuando fallecio",
    "cuándo falleció",
    "when was",
    "when did",
    "who is",
    "what is",
)
TITLE_PREFIXES = [
    "quiero ver",
    "ponme",
    "pon",
    "reproduce",
    "reproducir",
    "ver",
    "la peli de",
    "peli de",
    "pelicula de",
    "película de",
    "la pelicula",
    "la película",
    "el film",
    "la movie",
]


def clean_intent(text: str):
    if not text:
        return None

    cleaned = text.strip().lower()
    cleaned = cleaned.replace(".", " ").replace("\n", " ")
    cleaned = re.sub(r"[^a-z\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if cleaned in ALLOWED_INTENTS:
        return cleaned

    return None


def _safe_query(query: str) -> str:
    return (query or "").strip()


def detect_intent_fast(query: str):
    q = _safe_query(query).lower()
    if not q:
        return None

    if q.startswith("/video"):
        return "movies"

    if q.startswith("/img") or q.startswith("/image"):
        return "images"

    if q.startswith("/wiki"):
        return "wiki"

    if q.startswith("/tiempo") or q.startswith("/weather"):
        return "weather"

    if q.startswith("/library") or q.startswith("/catalog") or q.startswith("/menu"):
        return "library"

    if any(hint in q for hint in WIKI_HINTS):
        return "wiki"

    if any(hint in q for hint in MOVIE_INFO_HINTS):
        return "search"

    if any(hint in q for hint in MOVIE_HINTS):
        return "movies"

    return None


def _intent_messages(query: str):
    return [
        {
            "role": "system",
            "content": (
                "Eres un sistema de clasificación de intención.\n\n"
                "Responde SOLO con UNA palabra EXACTA de esta lista:\n"
                "movies, images, weather, wiki, search, library\n\n"
                "No expliques nada."
            ),
        },
        {"role": "user", "content": query},
    ]


def detect_intent_llm(query: str):
    response = call_llm(_intent_messages(query))
    return clean_intent(response)


def detect_intent_llm_cloud(query: str):
    response = call_llm_cloud(_intent_messages(query))
    return clean_intent(response)


def _extract_json_object(text: str):
    if not text:
        return None

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    return cleaned[start : end + 1]


def _normalize_parsed_intent(value):
    return clean_intent(value)


def _normalize_title(value):
    if value is None:
        return None

    title = str(value).strip()
    if not title or title.lower() == "null":
        return None

    title = re.sub(r"\s+", " ", title)
    return title.lower()


def _heuristic_movie_title(query: str):
    title = _safe_query(query).lower()

    if not title:
        return None

    title = re.sub(r"^/video\b", "", title).strip()

    for prefix in TITLE_PREFIXES:
        title = re.sub(rf"\b{re.escape(prefix)}\b", " ", title)

    title = re.sub(r"\s+", " ", title).strip(" ?!.,")
    return title or None


def extract_movie_title(query: str):
    heuristic_title = _heuristic_movie_title(query)

    messages = [
        {
            "role": "system",
            "content": (
                "Extrae SOLO el nombre de la película.\n\n"
                "Reglas:\n"
                "- Responde SOLO el título\n"
                "- Sin explicaciones\n"
                "- Sin frases adicionales\n"
                "- Si no hay título claro, responde null"
            ),
        },
        {"role": "user", "content": query},
    ]

    try:
        response = call_llm_cloud(messages)
        title = _normalize_title(response)
        if title:
            return title
    except Exception as exc:
        logger.warning("extract_movie_title failed: %s", exc)

    return heuristic_title or ""


def parse_query(query: str):
    messages = [
        {
            "role": "system",
            "content": (
                "Eres un sistema de análisis de intención.\n\n"
                "Devuelve SOLO JSON válido.\n\n"
                "Formato:\n"
                "{\n"
                '  "intent": "movies | images | weather | wiki | search | library",\n'
                '  "title": "string o null"\n'
                "}\n\n"
                "Reglas:\n"
                "- intent = movies solo si el usuario quiere reproducir o ver una película concreta\n"
                "- intent = search si pregunta por listas, filmografías, últimas películas o información sobre actores/directores\n"
                "- intent = library si pide abrir menú, biblioteca o catálogo\n"
                "- extrae SOLO el título de la película si aplica\n"
                '- elimina frases como "quiero ver", "pon", "reproduce", "la peli de"\n'
                "- si no hay película, title = null\n"
                "- NO expliques nada"
            ),
        },
        {"role": "user", "content": query},
    ]

    try:
        response = call_llm_cloud(messages)
        payload = _extract_json_object(response)
        parsed = json.loads(payload) if payload else {}
    except Exception as exc:
        logger.warning("parse_query failed: %s", exc)
        parsed = {}

    intent = _normalize_parsed_intent(parsed.get("intent"))
    title = _normalize_title(parsed.get("title"))

    if not title and intent == "movies":
        title = _heuristic_movie_title(query)

    return {
        "intent": intent,
        "title": title,
    }


def get_movie_title(query: str):
    parsed = parse_query(query)
    return parsed.get("title") or _heuristic_movie_title(query) or _safe_query(query)


def detect_intent(query: str):
    intent = detect_intent_fast(query)
    if intent:
        return intent

    parsed = parse_query(query)
    if parsed.get("intent"):
        return parsed["intent"]

    try:
        intent = detect_intent_llm(query)
        if intent:
            return intent
    except Exception as exc:
        logger.warning("Local LLM intent detection failed: %s", exc)

    try:
        intent = detect_intent_llm_cloud(query)
        if intent:
            return intent
    except Exception as exc:
        logger.warning("Cloud LLM intent detection failed: %s", exc)

    return "search"
