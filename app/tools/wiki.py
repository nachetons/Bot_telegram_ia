import requests

def wikipedia(query):
    url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
    r = requests.get(url, timeout=8)

    if r.status_code != 200:
        return "", []

    data = r.json()
    return data.get("extract", ""), ["wikipedia"]