import logging
import re
import unicodedata
import base64
import hashlib
import hmac
import time
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

    def __init__(self, base_url: str, api_key: str, user_id: str, public_base_url: str = "", proxy_secret: str = ""):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.user_id = (user_id or "").strip()
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.proxy_secret = (proxy_secret or "").strip()

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

    def _request_binary(self, path: str, params=None):
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
            return response.content, response.headers.get("Content-Type", "application/octet-stream")
        except requests.RequestException as exc:
            logger.error("Error downloading binary from Jellyfin: %s", exc)
            return None, None

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

    def _sort_seasons(self, items):
        def season_key(item):
            season_number = item.get("IndexNumber")
            sort_name = item.get("SortName") or item.get("Name") or ""
            return (season_number if season_number is not None else 9999, sort_name.lower())

        return sorted(items or [], key=season_key)

    def _sort_episodes(self, items):
        def episode_key(item):
            parent_season = item.get("ParentIndexNumber")
            episode_number = item.get("IndexNumber")
            sort_name = item.get("SortName") or item.get("Name") or ""
            return (
                parent_season if parent_season is not None else 9999,
                episode_number if episode_number is not None else 9999,
                sort_name.lower(),
            )

        return sorted(items or [], key=episode_key)

    def get_seasons(self, series_id: str):
        data = self._request_json(
            f"/Shows/{series_id}/Seasons",
            params={
                "UserId": self.user_id,
            },
        )

        items = data.get("Items", [])
        if not items:
            data = self._request_json(
                f"/Users/{self.user_id}/Items",
                params={
                    "ParentId": series_id,
                    "IncludeItemTypes": "Season",
                    "Recursive": "false",
                    "Limit": PAGE_SIZE,
                },
            )
            items = data.get("Items", [])

        return self._sort_seasons(items)

    def get_series_episodes(self, series_id: str):
        data = self._request_json(
            f"/Shows/{series_id}/Episodes",
            params={
                "UserId": self.user_id,
                "Limit": PAGE_SIZE,
            },
        )
        return self._sort_episodes(data.get("Items", []))

    def get_episodes_by_season(self, season_id: str):
        data = self._request_json(
            f"/Users/{self.user_id}/Items",
            params={
                "ParentId": season_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Limit": PAGE_SIZE,
            },
        )
        return self._sort_episodes(data.get("Items", []))

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

    def _extract_audio_tracks_from_media_source(self, media_source):
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

    def get_audio_tracks(self, item_id):
        _, media_source = self._get_primary_media_source(item_id)
        return self._extract_audio_tracks_from_media_source(media_source)

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

        if self.public_base_url and self.proxy_secret:
            return self.build_proxy_url(f"/Items/{item_id}/Images/Primary", expires_in=86400)

        params = urlencode({"api_key": self.api_key})
        return f"{self.base_url}/Items/{item_id}/Images/Primary?{params}"

    def get_image_binary(self, item_id):
        if not item_id:
            return None, None
        return self._request_binary(f"/Items/{item_id}/Images/Primary")

    def get_stream_url(self, item_id, audio_index=0, media_source_id=None):
        media_source = None
        if not media_source_id:
            _, media_source = self._get_primary_media_source(item_id)

        params = {
            "api_key": self.api_key,
            "AudioStreamIndex": audio_index,
            "VideoCodec": "h264",
            "AudioCodec": "aac",
            "AllowVideoStreamCopy": "true",
            "AllowAudioStreamCopy": "false",
        }

        resolved_media_source_id = media_source_id or (media_source.get("Id") if media_source else None)
        if resolved_media_source_id:
            params["MediaSourceId"] = resolved_media_source_id

        relative_path = f"/Videos/{item_id}/master.m3u8?{urlencode(params)}"
        if self.public_base_url and self.proxy_secret:
            return self.build_proxy_url(relative_path, expires_in=7200)

        return f"{self.base_url}{relative_path}"

    def _encode_target(self, relative_path: str):
        raw = (relative_path or "").encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _decode_target(self, encoded_target: str):
        padding = "=" * (-len(encoded_target) % 4)
        decoded = base64.urlsafe_b64decode((encoded_target + padding).encode("ascii")).decode("utf-8")
        if not decoded.startswith("/"):
            raise ValueError("Invalid proxy target")
        return decoded

    def _sign_target(self, encoded_target: str, exp: int):
        payload = f"{encoded_target}:{exp}".encode("utf-8")
        return hmac.new(self.proxy_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def build_proxy_url(self, relative_path: str, expires_in: int = 3600):
        encoded_target = self._encode_target(relative_path)
        exp = int(time.time()) + max(60, int(expires_in))
        sig = self._sign_target(encoded_target, exp)
        return f"{self.public_base_url}/proxy/jellyfin/raw/{encoded_target}?exp={exp}&sig={sig}"

    def verify_proxy_request(self, encoded_target: str, exp: int, sig: str):
        if not self.proxy_secret:
            return False
        if int(exp) < int(time.time()):
            return False

        expected = self._sign_target(encoded_target, exp)
        return hmac.compare_digest(expected, sig or "")

    def decode_proxy_target(self, encoded_target: str):
        return self._decode_target(encoded_target)

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
        _, media_source = self._get_primary_media_source(item_id)

        return {
            "type": "video",
            "title": movie.get("Name"),
            "image": self.get_image_url(movie),
            "item_id": item_id,
            "audio_tracks": self._extract_audio_tracks_from_media_source(media_source),
            "media_source_id": media_source.get("Id") if media_source else None,
            "score": result.get("score"),
        }

    def run_by_id(self, item_id):
        data = self.get_item_info(item_id)
        if not data or not data.get("Id"):
            return {"error": "No pude cargar ese contenido desde Jellyfin."}
        media_sources = data.get("MediaSources", [])
        media_source = media_sources[0] if media_sources else None

        return {
            "type": "video",
            "title": data.get("Name"),
            "image": self.get_image_url(data),
            "item_id": item_id,
            "audio_tracks": self._extract_audio_tracks_from_media_source(media_source),
            "media_source_id": media_source.get("Id") if media_source else None,
        }


from app.config import APP_BASE_URL, JELLYFIN_API_KEY, JELLYFIN_URL, JELLYFIN_USER_ID, MEDIA_PROXY_SECRET


jellyfin = JellyfinTool(
    base_url=JELLYFIN_URL,
    api_key=JELLYFIN_API_KEY,
    user_id=JELLYFIN_USER_ID,
    public_base_url=APP_BASE_URL,
    proxy_secret=MEDIA_PROXY_SECRET,
)
