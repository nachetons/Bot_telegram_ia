import requests
from bs4 import BeautifulSoup
from app.config import HEADERS


def search_web(query):
    r = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers=HEADERS,
        timeout=10
    )

    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for res in soup.select(".result"):
        a = res.select_one(".result__a")
        if a:
            links.append(a["href"])

    return links[:5]