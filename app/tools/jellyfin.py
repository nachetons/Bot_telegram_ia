import logging
import re
import unicodedata
from urllib.parse import urlencode

import requests
from rapidfuzz import fuzz


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jellyfin")

REQUEST_TIMEOUT = 10
PAGE_SIZE = 200


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class JellyfinTool:
    name = "jellyfin"

    def __init__(self, base_url: str, api_key: str, user_id: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.user_id = (user_id or "").strip()

    def _headers(self):
        return {"X-Emby-Token": self.api_key}

    def _request_json(self, path: str, params=None):
        url = f"{self.base_url}{path}"

        try:
            response = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            logger.info("Jellyfin GET %s -> %s", response.url, response.status_code)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.error("Error contacting Jellyfin: %s", exc)
        except ValueError as exc:
            logger.error("Invalid JSON from Jellyfin: %s", exc)

        return {}

    def _get_all_items(self, item_type: str):
        items = []
        start_index = 0

        while True:
            data = self._request_json(
                f"/Users/{self.user_id}/Items",
                params={
                    "IncludeItemTypes": item_type,
                    "Recursive": "true",
                    "Limit": PAGE_SIZE,
                    "StartIndex": start_index,
                },
            )

            batch = data.get("Items", [])
            items.extend(batch)

            total = data.get("TotalRecordCount", len(items))
            if not batch or len(items) >= total:
                break

            start_index += len(batch)

        logger.info("Loaded %s %s from Jellyfin", len(items), item_type.lower())
        return items

    def get_all_movies(self):
        return self._get_all_items("Movie")

    def get_all_series(self):
        return self._get_all_items("Series")

    def get_library(self, limit=20):
        movies = self.get_all_movies()
        series = self.get_all_series()

        return {
            "movies": [
                {
                    "id": movie["Id"],
                    "title": movie.get("Name"),
                    "type": "movie",
                    "image": self.get_image_url(movie),
                }
                for movie in movies[:limit]
            ],
            "series": [
                {
                    "id": show["Id"],
                    "title": show.get("Name"),
                    "type": "series",
                    "image": self.get_image_url(show),
                }
                for show in series[:limit]
            ],
        }

    def clean_query(self, query: str):
        q = (query or "").lower()

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
            "las",
        ]

        for word in stopwords:
            pattern = rf"\b{re.escape(word)}\b"
            q = re.sub(pattern, " ", q)

        q = re.sub(r"\s+", " ", q).strip()
        return q

    def search_movie(self, query: str):
        items = self.get_all_movies()
        cleaned_query = self.clean_query(query)
        q = normalize(cleaned_query)

        if not q:
            return {
                "type": "uncertain",
                "message": "Dime el nombre de una película para buscarla.",
                "results": [],
            }

        best_matches = []

        for item in items:
            name = normalize(item.get("Name"))
            original = normalize(item.get("OriginalTitle"))
            score = max(
                fuzz.token_set_ratio(q, name),
                fuzz.token_set_ratio(q, original),
            )

            candidate = dict(item)
            candidate["_score"] = score
            best_matches.append(candidate)

        best_matches.sort(key=lambda value: value["_score"], reverse=True)

        logger.info("Query final: %s", q)
        for match in best_matches[:10]:
            logger.info("Match %s -> %s", match.get("Name"), match["_score"])

        best = best_matches[0] if best_matches else None
        best_score = best["_score"] if best else 0

        if not best or best_score < 55:
            return {
                "type": "uncertain",
                "message": "No estoy seguro de la película",
                "results": best_matches[:5],
            }

        if best_score < 75:
            return {
                "type": "suggestion",
                "message": f"¿Te refieres a '{best.get('Name')}'?",
                "result": best,
                "results": best_matches[:5],
                "score": best_score,
            }

        return {
            "type": "match",
            "result": best,
            "score": best_score,
        }

    def get_item_info(self, item_id):
        return self._request_json(f"/Users/{self.user_id}/Items/{item_id}")

    def _get_primary_media_source(self, item_id):
        data = self.get_item_info(item_id)
        media_sources = data.get("MediaSources", [])
        return data, media_sources[0] if media_sources else None

    def get_audio_tracks(self, item_id):
        _, media_source = self._get_primary_media_source(item_id)
        if not media_source:
            return []

        audio_tracks = []
        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") == "Audio":
                audio_tracks.append(
                    {
                        "index": stream.get("Index"),
                        "language": stream.get("Language") or "unknown",
                    }
                )

        return audio_tracks

    def get_audio_stream_by_language(self, item_id, lang_code="spa"):
        _, media_source = self._get_primary_media_source(item_id)
        if not media_source:
            return None

        normalized_lang = (lang_code or "").lower()

        for stream in media_source.get("MediaStreams", []):
            if stream.get("Type") != "Audio":
                continue

            language = (stream.get("Language") or "").lower()
            if language.startswith(normalized_lang):
                return stream.get("Index")

        return None

    def get_image_url(self, item):
        item_id = item.get("Id") if isinstance(item, dict) else None
        if not item_id:
            return None

        params = urlencode({"api_key": self.api_key})
        return f"{self.base_url}/Items/{item_id}/Images/Primary?{params}"

    def get_stream_url(self, item_id, audio_index=0):
        _, media_source = self._get_primary_media_source(item_id)

        params = {
            "api_key": self.api_key,
            "AudioStreamIndex": audio_index,
            "VideoCodec": "h264",
            "AudioCodec": "aac",
            "AllowVideoStreamCopy": "true",
            "AllowAudioStreamCopy": "false",
        }

        if media_source and media_source.get("Id"):
            params["MediaSourceId"] = media_source["Id"]

        return f"{self.base_url}/Videos/{item_id}/master.m3u8?{urlencode(params)}"

    def run(self, query: str):
        result = self.search_movie(query)
        result_type = result.get("type")

        if result_type == "uncertain":
            return {"error": result.get("message", "No se encontraron películas")}

        if result_type == "suggestion":
            return {"error": result.get("message", "No estoy seguro de la película")}

        movie = result.get("result")
        if not movie:
            return {"error": "No se encontraron películas"}

        item_id = movie["Id"]

        return {
            "type": "video",
            "title": movie.get("Name"),
            "image": self.get_image_url(movie),
            "item_id": item_id,
            "audio_tracks": self.get_audio_tracks(item_id),
            "score": result.get("score"),
        }

    def run_by_id(self, item_id):
        data = self.get_item_info(item_id)
        if not data or not data.get("Id"):
            return {"error": "No pude cargar ese contenido desde Jellyfin."}

        return {
            "type": "video",
            "title": data.get("Name"),
            "image": self.get_image_url(data),
            "item_id": item_id,
            "audio_tracks": self.get_audio_tracks(item_id),
        }


from app.config import JELLYFIN_API_KEY, JELLYFIN_URL, JELLYFIN_USER_ID


jellyfin = JellyfinTool(
    base_url=JELLYFIN_URL,
    api_key=JELLYFIN_API_KEY,
    user_id=JELLYFIN_USER_ID,
)
