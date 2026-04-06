import requests
from bs4 import BeautifulSoup
import ftfy
import re


HEADERS = {"User-Agent": "Mozilla/5.0"}


def scrape(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()

        text = soup.get_text(" ")
        text = ftfy.fix_text(text)
        text = re.sub(r"\s+", " ", text)

        return text[:2000]

    except requests.exceptions.RequestException:
        return ""

    except Exception:
        return ""


def extract_evidence(text, query):
    sentences = re.split(r'(?<=[.!?]) +', text)
    q = set(query.lower().split())

    scored = []

    for s in sentences:
        score = sum(2 for w in q if w in s.lower())

        if any(x in s.lower() for x in ["fecha", "murió", "confirmó"]):
            score += 3

        if len(s) > 40:
            scored.append((score, s))

    scored.sort(reverse=True)
    return " ".join([s for _, s in scored[:5]])