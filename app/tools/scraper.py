import logging
import re

import ftfy
import requests
from bs4 import BeautifulSoup


logger = logging.getLogger("scraper")

HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_TEXT_LENGTH = 4000
MAX_EVIDENCE_LENGTH = 2200


def scrape(url: str):
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        response.raise_for_status()

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "html" not in content_type:
            logger.info("Skipping non-HTML content from %s (%s)", url, content_type)
            return ""

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "noscript",
                "form",
                "svg",
            ]
        ):
            tag.extract()

        for element in soup.select(
            '[class*="cookie"], [class*="banner"], [class*="advert"], [id*="cookie"], [id*="banner"]'
        ):
            element.extract()

        text = soup.get_text(" ")
        text = ftfy.fix_text(text)
        text = re.sub(r"\s+", " ", text).strip()

        return text[:MAX_TEXT_LENGTH]

    except requests.RequestException as exc:
        logger.info("Scrape request failed for %s: %s", url, exc)
        return ""
    except Exception as exc:
        logger.warning("Unexpected scrape error for %s: %s", url, exc)
        return ""


def _looks_like_numeric_query(query: str):
    lowered = (query or "").lower()
    return any(token in lowered for token in ["cuanto", "cuánto", "cuantos", "cuántos", "goles", "estadistica", "estadísticas", "cuifra", "numero", "número"])


def _is_low_quality_sentence(sentence: str):
    lowered = sentence.lower()
    bad_markers = [
        "saltar al contenido",
        "politica de privacidad",
        "política de privacidad",
        "condiciones de uso",
        "preferencias de privacidad",
        "destacado",
        "ediciones",
        "sobre nosotros",
        "carreras",
    ]
    if any(marker in lowered for marker in bad_markers):
        return True

    separator_count = sentence.count("|") + sentence.count("•")
    if separator_count >= 4:
        return True

    return False


def extract_evidence(text, query):
    if not text:
        return ""

    normalized_query = (query or "").lower()
    query_terms = [term for term in re.findall(r"\w+", normalized_query) if len(term) > 2]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    numeric_query = _looks_like_numeric_query(query)

    scored = []

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 50:
            continue

        if _is_low_quality_sentence(sentence):
            continue

        sentence_lower = sentence.lower()
        score = 0

        for term in query_terms:
            if term in sentence_lower:
                score += 3

        if numeric_query and re.search(r"\b\d[\d.,]*\b", sentence):
            score += 5

        if numeric_query and any(token in sentence_lower for token in ["goles", "tantos", "anoto", "anotó", "marca", "suma", "total"]):
            score += 4

        if any(keyword in sentence_lower for keyword in ["fecha", "murio", "murió", "confirmo", "confirmó"]):
            score += 2

        if score > 0:
            scored.append((score, sentence))

    if not scored:
        return ""

    scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)

    selected = []
    total_length = 0
    seen = set()

    for _, sentence in scored:
        normalized_sentence = sentence.lower()
        if normalized_sentence in seen:
            continue

        projected = total_length + len(sentence) + (1 if selected else 0)
        if projected > MAX_EVIDENCE_LENGTH:
            continue

        selected.append(sentence)
        seen.add(normalized_sentence)
        total_length = projected

        if len(selected) >= 5:
            break

    return " ".join(selected).strip()
