import requests
import re

def clean_location(query: str):
    query = query.lower()

    # quitar frases comunes
    remove_phrases = [
        "que tiempo hace",
        "hoy",
        "mañana",
        "en",
        "el clima de",
        "clima en"
    ]

    for phrase in remove_phrases:
        query = query.replace(phrase, "")

    # limpiar espacios
    query = re.sub(r"\s+", " ", query).strip()

    return query



def geocode_city(query: str):
    try:
        clean = clean_location(query)

        url = "https://nominatim.openstreetmap.org/search"

        params = {
            "q": clean,
            "format": "json",
            "limit": 1
        }

        headers = {
            "User-Agent": "weather-bot/1.0"
        }

        r = requests.get(url, params=params, headers=headers, timeout=8)
        data = r.json()

        if not data:
            return None

        return {
            "name": data[0]["display_name"],
            "lat": float(data[0]["lat"]),
            "lon": float(data[0]["lon"])
        }

    except Exception as e:
        print("GEOCODE ERROR:", e)
        return None



def get_weather(query: str):
    try:
        geo = geocode_city(query)

        if not geo:
            return "No encontré esa ciudad.", []

        lat = geo["lat"]
        lon = geo["lon"]
        name = geo["name"]

        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&timezone=auto"
        )

        r = requests.get(url, timeout=8)
        r.raise_for_status()

        d = r.json()["daily"]

        text = f"""
🌤 Clima en {name}

Hoy:
- Temp max: {d['temperature_2m_max'][0]}°C
- Temp min: {d['temperature_2m_min'][0]}°C
- Lluvia: {d['precipitation_probability_max'][0]}%
""".strip()

        return text, ["open-meteo", "nominatim"]

    except Exception as e:
        print("WEATHER ERROR:", e)
        return "No se pudo obtener clima.", []