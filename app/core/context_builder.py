from concurrent.futures import ThreadPoolExecutor
from app.tools.scraper import scrape
from app.tools.web import search_web  


def clean_links(links):
    bad_keywords = [
        "facebook", "instagram", "youtube",
        "login", "signup", "ads", "tracker",
        "policies", "privacy"
    ]

    clean = []
    for url in links:
        if not any(b in url.lower() for b in bad_keywords):
            clean.append(url)

    return clean[:5]


def worker(args):
    url, query = args
    try:
        text = scrape(url)
        if not text:
            return url, ""

        return url, text

    except Exception:
        return url, ""


def build_context(query: str):
    links = search_web(query)
    links = clean_links(links)

    if not links:
        return "", []

    results = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(worker, [(url, query) for url in links]))

    context_parts = []
    sources = []

    for url, text in results:
        if text:
            context_parts.append(text)
            sources.append(url)

    context = "\n\n".join(context_parts)

    return context, sources