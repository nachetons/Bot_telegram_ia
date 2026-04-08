import requests
import logging
from rapidfuzz import fuzz
import unicodedata
import re


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jellyfin")


# -----------------------
# NORMALIZE
# -----------------------
def normalize(text: str) -> str:
    text = (text or "").lower()

    # quitar acentos
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")

    # quitar símbolos
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # espacios limpios
    text = re.sub(r"\s+", " ", text).strip()

    return text


# -----------------------
# JELLYFIN TOOL
# -----------------------
class JellyfinTool:
    name = "jellyfin"

    def __init__(self, base_url: str, api_key: str, user_id: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.user_id = user_id.strip()

    # -----------------------
    # HEADERS
    # -----------------------
    def _headers(self):
        return {
            "X-Emby-Token": self.api_key
        }

    # -----------------------
    # GET MOVIES
    # -----------------------
    def get_all_movies(self):
        url = f"{self.base_url}/Users/{self.user_id}/Items"

        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Limit": 200
        }

        r = requests.get(url, headers=self._headers(), params=params)

        logger.info(f"STATUS: {r.status_code}")

        try:
            data = r.json()
        except Exception:
            return []

        items = data.get("Items", [])
        logger.info(f"🎬 TOTAL MOVIES: {len(items)}")

        return items
    

    # -----------------------
    # GET SERIES
    # -----------------------
    def get_all_series(self):
        url = f"{self.base_url}/Users/{self.user_id}/Items"

        params = {
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Limit": 200
        }

        r = requests.get(url, headers=self._headers(), params=params)

        try:
            data = r.json()
        except Exception:
            return []

        return data.get("Items", [])


    # -----------------------
    # GET LIBRARY (FIX)
    # -----------------------
    def get_library(self, limit=20):
        movies = self.get_all_movies()
        series = self.get_all_series()

        return {
            "movies": [
                {
                    "id": m["Id"],
                    "title": m.get("Name"),
                    "type": "movie",
                    "image": self.get_image_url(m)
                }
                for m in movies[:limit]
            ],
            "series": [
                {
                    "id": s["Id"],
                    "title": s.get("Name"),
                    "type": "series",
                    "image": self.get_image_url(s)
                }
                for s in series[:limit]
            ]
        }

    # -----------------------
    # CLEAN QUERY (FIXED)
    # -----------------------
    def clean_query(self, query: str):
        q = query.lower()

        stopwords = [
            "quiero ver",
            "ponme",
            "pon",
            "reproduce",
            "reproducir",
            "ver",
            "peli de",
            "pelicula de",
            "la peli de",
            "la",
            "el",
            "los",
            "las"
        ]

        for w in stopwords:
            q = q.replace(w, " ")

        q = re.sub(r"\s+", " ", q).strip()

        return q

    # -----------------------
    # SEARCH MOVIE (FIXED CORE)
    # -----------------------
    def search_movie(self, query: str):
        items = self.get_all_movies()

        q = normalize(self.clean_query(query))

        best_matches = []

        for m in items:
            name = normalize(m.get("Name"))
            original = normalize(m.get("OriginalTitle"))

            score = max(
                fuzz.token_set_ratio(q, name),
                fuzz.token_set_ratio(q, original)
            )

            m["_score"] = score
            best_matches.append(m)

        # ordenar por score
        best_matches.sort(key=lambda x: x["_score"], reverse=True)

        # DEBUG IMPORTANTE
        logger.info(f"🔎 QUERY FINAL: {q}")
        logger.info("📊 TOP MATCHES:")

        for m in best_matches[:10]:
            logger.info(f"🎬 {m.get('Name')} -> {m['_score']}")

        best = best_matches[0] if best_matches else None
        best_score = best["_score"] if best else 0

        # -----------------------
        # THRESHOLDS
        # -----------------------
        if not best or best_score < 55:
            return {
                "type": "uncertain",
                "message": "No estoy seguro de la película",
                "results": best_matches[:5]
            }

        if best_score < 75:
            return {
                "type": "suggestion",
                "message": f"¿Te refieres a '{best.get('Name')}'?",
                "result": best,
                "score": best_score
            }

        return {
            "type": "match",
            "result": best,
            "score": best_score
        }

    # -----------------------
    # RUN (FIXED BUG HERE)
    # -----------------------
    def run(self, query: str):
        result = self.search_movie(query)

        # no match claro
        if result.get("type") == "uncertain":
            return {"error": "No se encontraron películas"}

        movie = result.get("result")

        if not movie:
            return {"error": "No se encontraron películas"}

        item_id = movie["Id"]

        return {
            "type": "video",
            "title": movie.get("Name"),
            "image": self.get_image_url(movie),
            "item_id": item_id,
            "score": result.get("score")
        }

    # -----------------------
    # ITEM INFO
    # -----------------------
    def get_item_info(self, item_id):
        url = f"{self.base_url}/Users/{self.user_id}/Items/{item_id}"
        r = requests.get(url, headers=self._headers())
        return r.json()

    # -----------------------
    # AUDIO TRACKS
    # -----------------------
    def get_audio_tracks(self, item_id):
        data = self.get_item_info(item_id)

        media = data.get("MediaSources", [])
        if not media:
            return []

        streams = media[0].get("MediaStreams", [])

        audio_tracks = []

        for s in streams:
            if s.get("Type") == "Audio":
                audio_tracks.append({
                    "index": s.get("Index"),
                    "language": s.get("Language") or "unknown"
                })

        return audio_tracks

    # -----------------------
    # IMAGE
    # -----------------------
    def get_image_url(self, item):
        return f"{self.base_url}/Items/{item['Id']}/Images/Primary?api_key={self.api_key}"

    # -----------------------
    # STREAM URL
    # -----------------------
    def get_stream_url(self, item_id, audio_index=0):
        return (
            f"{self.base_url}/Videos/{item_id}/master.m3u8"
            f"?api_key={self.api_key}"
            f"&MediaSourceId={item_id}"
            f"&AudioStreamIndex={audio_index}"
            f"&VideoCodec=h264"
            f"&AudioCodec=aac"
            f"&AllowVideoStreamCopy=true"
            f"&AllowAudioStreamCopy=false"
        )
    
    def get_audio_stream_by_language(self, item_id, lang_code="spa"):
        data = self.get_item_info(item_id)

        media = data.get("MediaSources", [])
        if not media:
            return None

        streams = media[0].get("MediaStreams", [])

        for s in streams:
            if s.get("Type") == "Audio":
                if (s.get("Language") or "").lower().startswith(lang_code):
                    return s.get("Index")

        return None
    

    # -----------------------
    # IMAGE
    # -----------------------
    def get_image_url(self, item):
        return f"{self.base_url}/Items/{item['Id']}/Images/Primary?api_key={self.api_key}"

    # -----------------------
    # MAIN
    # -----------------------
    def run(self, query: str):
        result = self.search_movie(query)

        if result.get("type") == "uncertain":
            return {"error": "No se encontraron películas"}

        movie = result.get("result")

        if not movie:
            return {"error": "No se encontraron películas"}

        item_id = movie["Id"]

        return {
            "type": "video",
            "title": movie.get("Name"),
            "image": self.get_image_url(movie),
            "item_id": item_id,
            "score": result.get("score")
        }
    

    def run_by_id(self, item_id):
        data = self.get_item_info(item_id)

        return {
            "type": "video",
            "title": data.get("Name"),
            "image": self.get_image_url(data),
            "item_id": item_id,
            "audio_tracks": self.get_audio_tracks(item_id)
        }


# INIT
from app.config import JELLYFIN_URL, JELLYFIN_API_KEY, JELLYFIN_USER_ID

jellyfin = JellyfinTool(
    base_url=JELLYFIN_URL,
    api_key=JELLYFIN_API_KEY,
    user_id=JELLYFIN_USER_ID
)
