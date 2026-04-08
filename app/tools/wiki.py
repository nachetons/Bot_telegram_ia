import requests
import logging

logging.basicConfig(level=logging.INFO)


def wikipedia(query):
    query = query.replace("/wiki", "").strip()
    logging.info("🔍 Wikipedia search for: %s", query)

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    search_url = "https://es.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json"
    }

    r = requests.get(search_url, params=params, headers=headers, timeout=8)

    logging.info("📡 SEARCH RAW: %s", r.text[:300])

    if r.status_code != 200 or not r.text.strip():
        return "", []

    data = r.json()

    if not data.get("query", {}).get("search"):
        logging.error("❌ EMPTY SEARCH RESULTS")
        return "", []

    title = data["query"]["search"][0]["title"]

    summary_url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}"
    r2 = requests.get(summary_url, headers=headers, timeout=8)

    if r2.status_code != 200 or not r2.text.strip():
        return "", []

    data2 = r2.json()

    extract = data2.get("extract") or data2.get("extract_html")

    if not extract:
        logging.error("❌ EMPTY EXTRACT: %s", data2)
        return "", []

    return extract, ["wikipedia"]