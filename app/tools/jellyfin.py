import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jellyfin")


class JellyfinTool:
    name = "jellyfin"

    def __init__(self, base_url: str, api_key: str, user_id: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.user_id = user_id.strip()

    def _headers(self):
        return {
            "X-Emby-Token": self.api_key
        }

    # -----------------------
    # MOVIES
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
    # CLEAN QUERY
    # -----------------------
    def clean_query(self, query: str):
        q = query.lower()

        stopwords = [
            "ponme", "pon", "reproduce", "reproducir",
            "quiero ver", "ver", "la", "el", "los", "las"
        ]

        for w in stopwords:
            q = q.replace(w, "")

        return q.strip()
    
    def get_all_series(self):
        url = f"{self.base_url}/Users/{self.user_id}/Items"

        params = {
            "IncludeItemTypes": "Series",
            "Recursive": "true",
            "Limit": 200
        }

        r = requests.get(url, headers=self._headers(), params=params)
        data = r.json()

        return data.get("Items", [])


    def get_all_tv(self):
        url = f"{self.base_url}/Users/{self.user_id}/Items"

        params = {
            "IncludeItemTypes": "Episode",
            "Recursive": "true",
            "Limit": 200
        }

        r = requests.get(url, headers=self._headers(), params=params)
        data = r.json()

        return data.get("Items", [])
    

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
    # SEARCH
    # -----------------------
    def search_movie(self, query: str):
        items = self.get_all_movies()

        q = self.clean_query(query)

        results = []

        for m in items:
            name = (m.get("Name") or "").lower()
            original = (m.get("OriginalTitle") or "").lower()

            if q in name or q in original:
                results.append(m)

        logger.info(f"🔎 QUERY: {query}")
        logger.info(f"🧹 CLEAN: {q}")
        logger.info(f"🎯 MATCHED: {[m.get('Name') for m in results]}")

        return results

    # -----------------------
    # ITEM INFO (IMPORTANT)
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
    # STREAM URL
    # -----------------------
    def get_stream_url(self, item_id, audio_index=0):
        # Añadimos MediaSourceId para evitar el error 400
        return (
            f"{self.base_url}/Videos/{item_id}/master.m3u8"
            f"?api_key={self.api_key}"
            f"&MediaSourceId={item_id}"  # <--- ESTO ES LO QUE FALTA
            f"&AudioStreamIndex={audio_index}"
            f"&VideoCodec=h264"
            f"&AudioCodec=aac"
            f"&AllowVideoStreamCopy=true"
            f"&AllowAudioStreamCopy=false"
            f"&BreakOnNonKeyFrames=true"
            f"&Tag=bot_stream_v3"
        )
    
    def get_audio_stream_by_language(self, item_id, lang_code="spa"):
        data = self.get_item_info(item_id)

        media = data.get("MediaSources", [])
        streams = media[0].get("MediaStreams", [])

        for s in streams:
            if s.get("Type") == "Audio":
                if (s.get("Language") or "").lower().startswith(lang_code):
                    return s.get("Index")

        return 0
    

    # -----------------------
    # IMAGE
    # -----------------------
    def get_image_url(self, item):
        return f"{self.base_url}/Items/{item['Id']}/Images/Primary?api_key={self.api_key}"

    # -----------------------
    # MAIN
    # -----------------------
    def run(self, query: str):
        movies = self.search_movie(query)

        if not movies:
            return {"error": "No se encontraron películas"}

        movie = movies[0]
        item_id = movie["Id"]

        audio_tracks = self.get_audio_tracks(item_id)

        logger.info(f"🎧 AUDIO TRACKS: {audio_tracks}")

        return {
            "type": "video",
            "title": movie.get("Name"),
            "image": self.get_image_url(movie),
            "item_id": item_id,
            "audio_tracks": audio_tracks
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