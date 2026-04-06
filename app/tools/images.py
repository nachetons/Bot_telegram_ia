def get_images(query: str, limit: int = 5):
    try:
        import requests, re, urllib.parse

        q = urllib.parse.quote(query)

        url = f"https://duckduckgo.com/?q={q}&iax=images&ia=images"

        headers = {"User-Agent": "Mozilla/5.0"}

        res = requests.get(url, headers=headers, timeout=8)

        match = re.search(r'vqd="([\d-]+)"', res.text)
        if not match:
            return []

        vqd = match.group(1)

        ajax_url = (
            "https://duckduckgo.com/i.js"
            f"?l=us-en&o=json&q={q}&vqd={vqd}&f=,,,&p=1&s=0"
        )

        r = requests.get(ajax_url, headers=headers, timeout=8)
        data = r.json()

        images = [i.get("image") for i in data.get("results", []) if i.get("image")]

        # ranking simple
        images = sorted(
            images,
            key=lambda x: (
                ".jpg" in x,
                "large" in x,
                len(x)
            ),
            reverse=True
        )

        return images[:limit]

    except Exception:
        return []