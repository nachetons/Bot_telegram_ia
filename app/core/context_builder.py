import re
from concurrent.futures import ThreadPoolExecutor

from app.tools.scraper import extract_evidence, scrape
from app.tools.web import search_web_results


def clean_links(links):
    bad_keywords = [
        "facebook",
        "instagram",
        "youtube",
        "login",
        "signup",
        "ads",
        "tracker",
        "policies",
        "privacy",
    ]

    clean = []
    seen = set()

    for url in links:
        normalized_url = (url or "").strip()
        if not normalized_url:
            continue

        lowered_url = normalized_url.lower()
        if any(keyword in lowered_url for keyword in bad_keywords):
            continue

        if normalized_url in seen:
            continue

        seen.add(normalized_url)
        clean.append(normalized_url)

    return clean[:5]


def _normalize_title(text: str):
    text = (text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _score_result_for_query(result, query: str):
    title = (result.get("title") or "").lower()
    snippet = (result.get("snippet") or "").lower()
    combined = f"{title} {snippet}"
    score = 0

    terms = [term for term in re.findall(r"\w+", (query or "").lower()) if len(term) > 2]
    score += sum(2 for term in terms if term in combined)

    if _looks_like_numeric_query(query):
        if _snippet_is_useful_for_numeric_query(snippet):
            score += 10
        if re.search(r"\b\d{3,4}\b", snippet):
            score += 6
        if any(token in combined for token in ["goles", "oficial", "carrera", "estadisticas", "estadísticas"]):
            score += 4
        if any(token in title for token in ["cuantos goles", "cuántos goles", "todos los goles"]):
            score += 4

    if any(bad in combined for bad in ["media de", "por 90 minutos", "partidos"]):
        score -= 3

    return score


def clean_results(results, query: str):
    links = [result.get("url") for result in results]
    clean_urls = set(clean_links(links))

    cleaned = []
    seen_titles = set()
    for result in results:
        url = (result.get("url") or "").strip()
        if url not in clean_urls:
            continue

        normalized_title = _normalize_title(result.get("title"))
        if normalized_title and normalized_title in seen_titles:
            continue

        if normalized_title:
            seen_titles.add(normalized_title)

        cleaned.append(result)

    cleaned.sort(key=lambda result: _score_result_for_query(result, query), reverse=True)
    return cleaned[:5]


def _looks_like_numeric_query(query: str):
    lowered = (query or "").lower()
    markers = [
        "cuanto",
        "cuánto",
        "cuantos",
        "cuántos",
        "goles",
        "estadistica",
        "estadísticas",
        "numero",
        "número",
        "cantidad",
        "años",
        "anos",
    ]
    return any(marker in lowered for marker in markers)


def _snippet_is_useful_for_numeric_query(snippet: str):
    lowered = (snippet or "").lower()
    if not snippet:
        return False

    if not any(token in lowered for token in ["goles", "total", "oficial", "carrera", "temporada"]):
        return False

    # Solo usamos el snippet como fuente principal si trae una cifra fuerte.
    strong_numeric_patterns = [
        r"\b\d{3,4}\s+goles\b",
        r"\b\d{3,4}\s+tantos\b",
        r"\balcanz[oó]\s+los\s+\d{3,4}\b",
        r"\bsuma\s+\d{3,4}\b",
        r"\btotal\s+de\s+\d{3,4}\b",
    ]

    return any(re.search(pattern, lowered) for pattern in strong_numeric_patterns)


def worker(args):
    result, query = args
    try:
        url = result.get("url")
        title = (result.get("title") or "").strip()
        snippet = (result.get("snippet") or "").strip()
        numeric_query = _looks_like_numeric_query(query)

        if numeric_query and _snippet_is_useful_for_numeric_query(snippet):
            content = snippet
        else:
            text = scrape(url)
            evidence = extract_evidence(text, query) if text else ""
            content = evidence or snippet

        if not content:
            return url, ""

        parts = []
        if title:
            parts.append(f"Fuente: {title}")
        parts.append(f"URL: {url}")
        parts.append(content.strip())

        return url, "\n".join(parts)

    except Exception:
        return result.get("url"), ""


def build_context(query: str):
    results = search_web_results(query)
    results = clean_results(results, query)

    if not results:
        return "", []

    if _looks_like_numeric_query(query):
        results = results[:4]

    with ThreadPoolExecutor(max_workers=min(4, len(results))) as executor:
        scraped_results = list(executor.map(worker, [(result, query) for result in results]))

    context_parts = []
    sources = []

    for url, text in scraped_results:
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            continue

        context_parts.append(cleaned_text)
        sources.append(url)

    context = "\n\n".join(context_parts)
    return context, sources
