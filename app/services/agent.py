import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from app.core.router_intent import detect_intent, extract_movie_title
from app.tools.images import get_images
from app.tools.weather import get_weather
from app.tools.wiki import wikipedia
from app.tools.jellyfin import jellyfin
from app.tools.web import search_web_results
from app.core.context_builder import build_context
from app.core.refiner import refine_context
from app.services.llm_provider import smart_llm
from app.core.prompt import system_prompt

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _looks_like_numeric_query(query: str):
    lowered = (query or "").lower()
    numeric_markers = [
        "cuanto",
        "cuánta",
        "cuanto",
        "cuantos",
        "cuántos",
        "cuantas",
        "cuántas",
        "goles",
        "estadistica",
        "estadísticas",
        "numero",
        "número",
        "cantidad",
        "anos",
        "años",
    ]
    return any(marker in lowered for marker in numeric_markers)


def _looks_like_identity_query(query: str):
    lowered = (query or "").lower()
    return any(
        marker in lowered
        for marker in [
            "como se llama",
            "cómo se llama",
            "cual es el nombre de",
            "cuál es el nombre de",
            "que nombre tiene",
            "qué nombre tiene",
            "nombre real de",
        ]
    )


def _looks_like_filmography_query(query: str):
    lowered = (query or "").lower()
    return any(
        marker in lowered
        for marker in [
            "ultimas peliculas",
            "últimas películas",
            "lista de peliculas",
            "lista de películas",
            "filmografia",
            "filmografía",
            "peliculas en las que participo",
            "películas en las que participó",
            "peliculas en las que sale",
            "películas en las que sale",
        ]
    )


def _extract_person_from_filmography_query(query: str):
    cleaned = (query or "").lower()
    prefixes = [
        "cuales son las ultimas peliculas en las que participo",
        "cuáles son las últimas películas en las que participó",
        "lista de peliculas en las que participo",
        "lista de películas en las que participó",
        "peliculas en las que participo",
        "películas en las que participó",
        "peliculas en las que sale",
        "películas en las que sale",
        "filmografia de",
        "filmografía de",
    ]

    for prefix in prefixes:
        cleaned = cleaned.replace(prefix, " ")

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?!.,")
    return cleaned


def _extract_filmography_from_adictosalcine(url: str):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    films = []
    current_year = datetime.now().year

    for paragraph in soup.select("p"):
        title_node = paragraph.select_one("b")
        if not title_node:
            continue

        title = title_node.get_text(" ", strip=True)
        text = paragraph.get_text(" ", strip=True)
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        if not year_match:
            continue

        year = int(year_match.group(0))
        if year > current_year:
            continue

        films.append((year, title))

    deduped = []
    seen = set()
    for year, title in films:
        key = (year, title.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((year, title))

    deduped.sort(key=lambda item: item[0], reverse=True)
    return deduped[:5]


def _extract_filmography_answer(query: str):
    if not _looks_like_filmography_query(query):
        return None, []

    person = _extract_person_from_filmography_query(query)
    if not person:
        return None, []

    try:
        results = search_web_results(f"filmografia {person}")
    except Exception:
        return None, []

    for result in results:
        url = (result.get("url") or "").strip()
        if "adictosalcine.com/filmografias/peliculas/" not in url:
            continue

        try:
            films = _extract_filmography_from_adictosalcine(url)
        except Exception:
            continue

        if not films:
            continue

        lines = [f"Últimas películas de {person.title()}:"]
        for year, title in films:
            lines.append(f"- {year}: {title}")

        return "\n".join(lines), [url]

    return None, []


def _extract_aliases_from_query(query: str):
    lowered = (query or "").lower().strip(" ?!.,")
    patterns_to_remove = [
        "como se llama",
        "cómo se llama",
        "cual es el nombre de",
        "cuál es el nombre de",
        "que nombre tiene",
        "qué nombre tiene",
        "nombre real de",
        "el youtuber",
        "la youtuber",
        "youtuber",
        "streamer",
        "de",
    ]

    for pattern in patterns_to_remove:
        lowered = lowered.replace(pattern, " ")

    lowered = re.sub(r"\s+", " ", lowered).strip()
    parts = re.split(r"\s+y\s+|,", lowered)
    aliases = []

    for part in parts:
        alias = part.strip(" ?!.,")
        if alias and alias not in aliases:
            aliases.append(alias)

    return aliases


def _extract_identity_from_context(alias: str, context: str):
    if not context:
        return None

    lines = [line.strip() for line in context.splitlines() if line.strip()]
    normalized_alias = alias.lower()

    for line in lines:
        lowered = line.lower()

        direct_patterns = [
            r"nombre completo\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+){0,3})",
            r"nombre de nacimiento\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+){0,3})",
        ]

        for pattern in direct_patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(1).strip()

        if normalized_alias in lowered and any(token in lowered for token in ["conocido como", "conocida como", "más conocido como", "mas conocido como"]):
            leading_name = re.match(r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+){0,3})", line)
            if leading_name:
                return leading_name.group(1).strip()

    return None


def _extract_identity_answer(query: str):
    if not _looks_like_identity_query(query):
        return None, []

    aliases = _extract_aliases_from_query(query)
    if not aliases:
        return None, []

    answers = []
    sources = []

    for alias in aliases[:3]:
        context, alias_sources = wikipedia(alias)
        identity = _extract_identity_from_context(alias, context)

        if not identity:
            web_context, web_sources = build_context(alias)
            web_context = refine_context(web_context)
            identity = _extract_identity_from_context(alias, web_context)
            alias_sources = alias_sources or web_sources

        if identity:
            answers.append(f"{alias.title()}: {identity}")
            sources.extend(alias_sources)

    if not answers:
        return None, []

    return "\n".join(answers), list(dict.fromkeys(sources))


def _extract_bio_answer(query: str, context: str, allow_unknown_message: bool = True):
    if not context:
        return None

    lowered_query = (query or "").lower()
    lowered_context = (context or "").lower()

    death_query = any(token in lowered_query for token in ["fallecio", "falleció", "murio", "murió", "de que murio", "de qué murió"])
    birth_query = any(token in lowered_query for token in ["nacio", "nació"])

    if not death_query and not birth_query:
        return None

    date_pattern = (
        r"\b("
        r"\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}"
        r"|[a-záéíóúñ]+\s+\d{1,2},\s+\d{4}"
        r"|\d{1,2}[./-]\d{1,2}[./-]\d{4}"
        r"|\d{4}"
        r")\b"
    )

    if death_query:
        death_patterns = [
            rf"(falleci[oó]|muri[oó]).{{0,80}}?{date_pattern}",
            rf"{date_pattern}.{{0,80}}?(falleci[oó]|muri[oó])",
        ]

        for pattern in death_patterns:
            death_match = re.search(pattern, lowered_context, re.IGNORECASE)
            if death_match:
                date_groups = [group for group in death_match.groups() if group and re.search(date_pattern, group, re.IGNORECASE)]
                if date_groups:
                    return f"Según la información encontrada, falleció el {date_groups[0]}."

        # fallback por bloques: si un bloque menciona muerte y contiene una fecha clara, úsala
        for block in re.split(r"\n\s*\n", context):
            lowered_block = block.lower()
            if not any(token in lowered_block for token in ["falleci", "muri"]):
                continue

            block_dates = re.findall(date_pattern, block, re.IGNORECASE)
            if block_dates:
                # prioriza fechas completas frente a años sueltos
                block_dates.sort(key=lambda value: (len(value), value), reverse=True)
                return f"Según la información encontrada, falleció el {block_dates[0]}."

        if allow_unknown_message and "falleci" not in lowered_context and "muri" not in lowered_context:
            return "No encontré una fecha de fallecimiento para esa persona en la información consultada."

    if birth_query:
        birth_match = re.search(rf"(naci[oó]).{{0,60}}?{date_pattern}", lowered_context, re.IGNORECASE)
        if birth_match:
            return f"Según la información encontrada, nació el {birth_match.group(2)}."

        if allow_unknown_message:
            return "No encontré una fecha de nacimiento para esa persona en la información consultada."

    return None


def _extract_bio_answer_from_search(query: str):
    lowered_query = (query or "").lower()
    death_query = any(token in lowered_query for token in ["fallecio", "falleció", "murio", "murió", "de que murio", "de qué murió"])
    birth_query = any(token in lowered_query for token in ["nacio", "nació"])

    if not death_query and not birth_query:
        return None, []

    try:
        results = search_web_results(query)
    except Exception:
        return None, []

    snippets = []
    sources = []

    for result in results[:5]:
        snippet = (result.get("snippet") or "").strip()
        url = (result.get("url") or "").strip()
        if snippet:
            snippets.append(snippet)
        if url:
            sources.append(url)

    combined = "\n\n".join(snippets)
    return _extract_bio_answer(query, combined), sources


def _extract_numeric_answer(query: str, context: str):
    if not context or not _looks_like_numeric_query(query):
        return None

    lowered_query = (query or "").lower()
    normalized_context = " ".join((context or "").split())
    query_terms = [
        term
        for term in re.findall(r"\w+", lowered_query)
        if len(term) > 2 and term not in {"puedes", "buscarme", "actualidad", "actualmente", "lleva"}
    ]

    if "goles" in lowered_query:
        blocks = re.split(r"\n\s*\n", context)
        candidates = []
        strong_patterns = [
            r"alcanz[oó]\s+los\s+(\d{3,4})\s+goles\s+oficiales",
            r"(\d{3,4})\s+goles\s+oficiales",
            r"suma\s+(\d{3,4})\s+(?:gritos|goles)",
            r"total\s+de\s+(\d{3,4})\s+goles",
            r"lleva\s+(\d{3,4})\s+goles",
            r"tiene\s+(\d{3,4})\s+goles",
        ]
        recency_tokens = ["hoy", "actualidad", "actualizadas", "actualizado", "actualmente", "en vivo", "alcanzó", "continúa", "sigue"]
        vague_tokens = ["cerca de", "casi", "mas de", "más de", "aproximad"]
        preferred_sources = ["sportingnews", "clarosports", "espn", "transfermarkt"]
        weaker_sources = ["neogol", "footystats"]

        for block in blocks:
            block_text = " ".join(block.split())
            if not block_text:
                continue

            lowered_block = block_text.lower()
            source_line = ""
            url_line = ""
            for line in block.splitlines():
                if line.strip().startswith("Fuente:"):
                    source_line = line.strip().lower()
                if line.strip().startswith("URL:"):
                    url_line = line.strip().lower()

            for pattern in strong_patterns:
                for match in re.finditer(pattern, lowered_block):
                    number = int(match.group(1))
                    if not (100 <= number <= 1500):
                        continue

                    around = lowered_block[max(0, match.start() - 40): min(len(lowered_block), match.end() + 60)]
                    if any(token in around for token in vague_tokens):
                        continue

                    score = 0
                    score += sum(4 for term in query_terms if term in lowered_block)
                    if "cristiano" in lowered_query and "cristiano" in lowered_block:
                        score += 5
                    if "ronaldo" in lowered_query and "ronaldo" in lowered_block:
                        score += 5
                    if any(token in around for token in ["oficial", "oficiales", "carrera", "suma", "alcanz", "lleva", "tiene"]):
                        score += 8
                    if any(token in lowered_block for token in recency_tokens):
                        score += 8
                    if any(token in source_line for token in ["hoy", "estadísticas", "estadisticas", "todos los goles"]):
                        score += 4
                    if re.search(r"\b2026\b", lowered_block):
                        score += 6
                    if re.search(r"\b2025\b", lowered_block):
                        score += 2
                    if any(source in url_line for source in preferred_sources):
                        score += 5
                    if any(source in url_line for source in weaker_sources):
                        score -= 4
                    if "temporada" in lowered_block and "temporada" not in lowered_query:
                        score -= 6
                    if number >= 900:
                        score += 3

                    candidates.append((score, number, block_text, url_line))

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            best_score, best_number, _, _ = candidates[0]

            if best_score >= 10:
                if "cristiano" in lowered_query and "ronaldo" in lowered_query:
                    return f"Cristiano Ronaldo lleva {best_number} goles oficiales en su carrera."

    best_sentence = None
    best_score = 0

    sentences = re.split(r"(?<=[.!?])\s+|\n+", context)

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 25 or sentence.startswith(("Fuente:", "URL:")):
            continue

        numbers = re.findall(r"\b\d{2,4}\b", sentence)
        if not numbers:
            continue

        lowered = sentence.lower()
        score = sum(4 for term in query_terms if term in lowered)
        score += 2

        if "goles" in lowered:
            score += 5
        if any(token in lowered for token in ["total", "oficial", "oficiales", "carrera", "temporada"]):
            score += 2
        if any(token in lowered for token in ["cerca de", "casi", "mas de", "más de", "aproximad"]):
            score -= 6

        if score > best_score:
            best_score = score
            best_sentence = sentence

    if not best_sentence or best_score < 12:
        return None

    return best_sentence


def _fallback_answer_from_context(query: str, context: str):
    if not context:
        return None

    lines = [line.strip() for line in context.splitlines() if line.strip()]
    candidates = []

    for line in lines:
        if line.startswith(("Fuente:", "URL:")):
            continue

        lowered = line.lower()
        if len(line) < 40:
            continue

        score = 0
        if any(term in lowered for term in re.findall(r"\w+", (query or "").lower()) if len(term) > 2):
            score += 3
        if any(char.isdigit() for char in line):
            score += 2
        if any(token in lowered for token in ["goles", "oficial", "total", "carrera", "estadistica", "estadísticas"]):
            score += 3
        if any(token in lowered for token in ["cerca de", "casi", "aproximad"]):
            score -= 2

        candidates.append((score, line))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    best_score, best_line = candidates[0]
    if best_score <= 0:
        return None

    return best_line


def agent(query: str):
    intent = detect_intent(query)

    filmography_answer, filmography_sources = _extract_filmography_answer(query)
    if filmography_answer:
        return filmography_answer, filmography_sources

    identity_answer, identity_sources = _extract_identity_answer(query)
    if identity_answer:
        return identity_answer, identity_sources

    # -----------------------
    # IMAGES
    # -----------------------
    if intent == "images":
        images = get_images(query)

        return {
            "type": "images",
            "images": images
        }, ["images_tool"]

    # -----------------------
    # WEATHER
    # -----------------------
    elif intent == "weather":
        context, sources = get_weather(query)
        return context, sources

    # -----------------------
    # WIKI
    # -----------------------
    elif intent == "wiki":
        context, sources = wikipedia(query)
        bio_answer = _extract_bio_answer(query, context, allow_unknown_message=False)
        if bio_answer:
            return bio_answer, sources

        search_bio_answer, search_sources = _extract_bio_answer_from_search(query)
        if search_bio_answer:
            return search_bio_answer, search_sources

        # Si la wiki no trae la fecha explícita, seguimos con búsqueda web.
        web_context, web_sources = build_context(query)
        web_context = refine_context(web_context)
        web_bio_answer = _extract_bio_answer(query, web_context, allow_unknown_message=False)
        if web_bio_answer:
            return web_bio_answer, web_sources

        final_bio_answer = _extract_bio_answer(query, context or web_context, allow_unknown_message=True)
        if final_bio_answer:
            return final_bio_answer, sources or web_sources

        # fallback a LLM si wiki falla
        if not context:
            context, sources = web_context, web_sources
            bio_answer = web_bio_answer or _extract_bio_answer(query, context)
            if bio_answer:
                return bio_answer, sources
            numeric_answer = _extract_numeric_answer(query, context)
            if numeric_answer:
                return numeric_answer, sources
            fallback_answer = _fallback_answer_from_context(query, context)

            messages = [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": f"{query}\n\n{context}"}
            ]

            response = smart_llm(messages)  # 🔥 CAMBIO CLAVE
            if response == "No puedo responder ahora mismo" and fallback_answer:
                return fallback_answer, sources
            return response, sources

        return context, sources

    # -----------------------
    # MOVIES (JELLYFIN)
    # -----------------------
    elif intent == "movies":

        clean_query = extract_movie_title(query)

        # 🔒 PROTECCIÓN: LLM falló o no entendió
        if not clean_query:
            # intentar como wiki (por si era una pregunta tipo "quien es...")
            context, sources = wikipedia(query)
            if context:
                return context, sources

            return {
                "error": "No he entendido qué película buscas."
            }, ["jellyfin_tool"]

        # 🎬 Buscar en Jellyfin
        result = jellyfin.run(clean_query)

        # 🔒 Error interno de Jellyfin
        if isinstance(result, dict) and "error" in result:
            return result, ["jellyfin_tool"]

        # 🔍 No hay resultados → fallback inteligente
        if not result:
            context, sources = wikipedia(query)

            if context:
                return context, sources

            return {
                "error": f"No he encontrado la película: {clean_query}"
            }, ["jellyfin_tool"]

        return result, ["jellyfin_tool"]
    
    # -----------------------
    # LIBRARY (JELLYFIN)
    # -----------------------
    elif intent == "library":

        library = jellyfin.get_library()

        buttons = []

        # MOVIES
        for m in library["movies"]:
            buttons.append([
                {
                    "text": f"🎬 {m['title']}",
                    "callback_data": f"play_movie:{m['id']}"
                }
            ])

        # SERIES
        for s in library["series"]:
            buttons.append([
                {
                    "text": f"📺 {s['title']}",
                    "callback_data": f"open_series:{s['id']}"
                }
            ])

        return {
            "type": "menu",
            "text": "🎥 Biblioteca",
            "buttons": [
                [{"text": "🎬 Películas", "callback_data": "open_library:movies"}],
                [{"text": "📺 Series", "callback_data": "open_library:series"}]
            ]
            }, ["jellyfin_library"]

    # -----------------------
    # DEFAULT (LLM)
    # -----------------------
    else:
        context, sources = build_context(query)
        context = refine_context(context)
        bio_answer = _extract_bio_answer(query, context)
        if bio_answer:
            return bio_answer, sources
        numeric_answer = _extract_numeric_answer(query, context)
        if numeric_answer:
            return numeric_answer, sources
        fallback_answer = _fallback_answer_from_context(query, context)

        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": f"{query}\n\n{context}"}
        ]

        response = smart_llm(messages)  # 🔥 CAMBIO CLAVE
        if response == "No puedo responder ahora mismo" and fallback_answer:
            return fallback_answer, sources

        return response, sources
