import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

logger = logging.getLogger("sports_prediction")

DATA_FILE = Path("data/predictions.json")
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}
_cache: Dict[str, tuple[Any, datetime]] = {}
_CACHE_DURATION_HOURS = 1
TEAM_SEARCH_VARIANTS = {
    "real madrid": ["madrid", "real madrid", "real"],
    "fc barcelona": ["barcelona", "barca"],
    "barcelona": ["barcelona", "barca"],
    "atletico madrid": ["atletico", "atleti", "madrid"],
    "atlético de madrid": ["atletico", "atleti", "madrid"],
    "real betis": ["betis", "real betis"],
    "real sociedad": ["real sociedad", "sociedad"],
    "athletic club": ["athletic", "bilbao"],
    "rcd espanyol de barcelona": ["espanyol", "español"],
    "espanyol": ["espanyol", "español"],
    "real valladolid": ["valladolid"],
    "sevilla": ["sevilla"],
    "valencia": ["valencia"],
    "villarreal": ["villarreal"],
}
STATIC_TEAM_NAME_MAP = {
    "real madrid": "Real Madrid",
    "fc barcelona": "Barcelona",
    "barcelona": "Barcelona",
    "atletico madrid": "Atletico Madrid",
    "atlético de madrid": "Atletico Madrid",
    "real betis": "Real Betis",
    "real sociedad": "Real Sociedad",
    "athletic club": "Athletic Club",
    "espanyol": "Espanyol",
    "rcd espanyol de barcelona": "Espanyol",
    "real valladolid": "Valladolid",
    "sevilla": "Sevilla",
    "valencia": "Valencia",
    "villarreal": "Villarreal",
}


def _get_from_cache(key: str) -> Optional[Any]:
    cached = _cache.get(key)
    if not cached:
        return None

    value, timestamp = cached
    if (datetime.now() - timestamp).total_seconds() < _CACHE_DURATION_HOURS * 3600:
        return value

    _cache.pop(key, None)
    return None


def _set_cache(key: str, value: Any) -> None:
    _cache[key] = (value, datetime.now())


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()


def _candidate_name_variants(team: dict) -> list[str]:
    raw_values = [
        team.get("strTeam"),
        team.get("strTeamAlternate"),
        team.get("strTeamShort"),
    ]
    variants = []
    seen = set()
    for raw in raw_values:
        if not raw:
            continue
        stripped = raw.strip()
        normalized = _normalize_text(stripped)
        if normalized and normalized not in seen:
            seen.add(normalized)
            variants.append(stripped)
    return variants


def _team_search_queries(team_name: str) -> list[str]:
    normalized = _normalize_text(team_name)
    queries = [team_name.strip()]

    alias_values = TEAM_SEARCH_VARIANTS.get(normalized, [])
    queries.extend(alias_values)

    words = normalized.split()
    if words:
        queries.append(words[0])
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))
        queries.append(words[-1])

    output = []
    seen = set()
    for query in queries:
        cleaned = (query or "").strip()
        normalized_query = _normalize_text(cleaned)
        if normalized_query and normalized_query not in seen:
            seen.add(normalized_query)
            output.append(cleaned)
    return output


def _load_predictions() -> dict:
    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict) and isinstance(data.get("predictions"), list):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"predictions": []}


def _save_predictions(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def _parse_espn_date(raw_date: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except Exception:
        return None


def _search_team_espn_id(team_name: str) -> Optional[str]:
    cache_key = f"espn_id:{team_name.lower().strip()}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    response = requests.get(
        "https://www.thesportsdb.com/api/v1/json/3/searchteams.php",
        params={"t": team_name},
        headers=HTTP_HEADERS,
        timeout=15,
    )
    response.raise_for_status()

    teams = response.json().get("teams") or []
    normalized_query = team_name.lower().strip()

    def team_score(team: dict) -> tuple[int, int]:
        team_name_value = (team.get("strTeam") or "").lower()
        league_value = (team.get("strLeague") or "").lower()
        score = 0
        if team.get("strSport") == "Soccer":
            score += 5
        if team.get("idESPN") and team.get("idESPN") != "0":
            score += 5
        if team_name_value == normalized_query:
            score += 6
        elif normalized_query in team_name_value:
            score += 3
        if any(token in league_value for token in ["liga", "champions", "cup", "premier", "serie", "bundes"]):
            score += 2
        return score, len(team_name_value)

    teams = sorted(teams, key=team_score, reverse=True)
    for team in teams:
        espn_id = team.get("idESPN")
        if espn_id and espn_id != "0":
            _set_cache(cache_key, espn_id)
            return espn_id

    return None


def _search_thesportsdb_candidates(team_name: str, limit: int = 12) -> list[dict]:
    cache_key = f"thesportsdb_candidates:{_normalize_text(team_name)}:{limit}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    candidates: list[dict] = []
    seen_ids = set()

    for query in _team_search_queries(team_name):
        try:
            response = requests.get(
                "https://www.thesportsdb.com/api/v1/json/3/searchteams.php",
                params={"t": query},
                headers=HTTP_HEADERS,
                timeout=8,
            )
            response.raise_for_status()
            teams = response.json().get("teams") or []
        except Exception:
            continue

        for team in teams:
            team_id = team.get("idTeam")
            if not team_id or team_id in seen_ids:
                continue
            if team.get("strSport") != "Soccer":
                continue
            seen_ids.add(team_id)
            candidates.append(team)

    _set_cache(cache_key, candidates[:limit])
    return candidates[:limit]


def resolve_team_name(team_name: str) -> dict:
    query = (team_name or "").strip()
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return {"status": "empty", "query": query, "resolved_name": None, "suggestions": []}

    candidates = _search_thesportsdb_candidates(query, limit=20)
    if not candidates:
        static_choices = list(STATIC_TEAM_NAME_MAP.values())
        static_match = process.extract(query, static_choices, scorer=fuzz.WRatio, limit=3)
        static_suggestions = []
        seen_static = set()
        for item in static_match:
            if item[1] < 70:
                continue
            name = item[0]
            if name.lower() in seen_static:
                continue
            seen_static.add(name.lower())
            static_suggestions.append(name)
        if static_suggestions:
            best_name, best_score, _ = static_match[0]
            if best_score >= 88:
                return {
                    "status": "resolved",
                    "query": query,
                    "resolved_name": best_name,
                    "suggestions": static_suggestions[:3],
                    "score": best_score,
                }
            return {
                "status": "suggest",
                "query": query,
                "resolved_name": None,
                "suggestions": static_suggestions[:3],
                "score": best_score,
            }
        return {"status": "not_found", "query": query, "resolved_name": None, "suggestions": []}

    choice_map: dict[str, dict] = {}
    for team in candidates:
        for variant in _candidate_name_variants(team):
            choice_map[variant] = team

    if not choice_map:
        return {"status": "not_found", "query": query, "resolved_name": None, "suggestions": []}

    scored = process.extract(
        query,
        list(choice_map.keys()),
        scorer=fuzz.WRatio,
        limit=5,
    )

    suggestions = []
    best_team = None
    best_score = 0
    seen_names = set()
    for variant, score, _ in scored:
        team = choice_map[variant]
        canonical_name = (team.get("strTeam") or variant).strip()
        if canonical_name.lower() in seen_names:
            continue
        seen_names.add(canonical_name.lower())
        suggestions.append(canonical_name)
        if score > best_score:
            best_score = score
            best_team = team

    if best_team and best_score >= 90:
        return {
            "status": "resolved",
            "query": query,
            "resolved_name": (best_team.get("strTeam") or query).strip(),
            "suggestions": suggestions[:3],
            "score": best_score,
        }

    if suggestions:
        return {
            "status": "suggest",
            "query": query,
            "resolved_name": None,
            "suggestions": suggestions[:3],
            "score": best_score,
        }

    return {"status": "not_found", "query": query, "resolved_name": None, "suggestions": []}


def _get_espn_team_payload(team_name: str) -> Optional[dict]:
    cache_key = f"espn_team_payload:{team_name.lower().strip()}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    espn_id = _search_team_espn_id(team_name)
    if not espn_id:
        return None

    response = requests.get(
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{espn_id}",
        headers=HTTP_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    _set_cache(cache_key, payload)
    return payload


def _search_thesportsdb_team(team_name: str) -> Optional[dict]:
    cache_key = f"thesportsdb_team:{team_name.lower().strip()}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    response = requests.get(
        "https://www.thesportsdb.com/api/v1/json/3/searchteams.php",
        params={"t": team_name},
        headers=HTTP_HEADERS,
        timeout=15,
    )
    response.raise_for_status()

    teams = response.json().get("teams") or []
    normalized_query = team_name.lower().strip()
    for team in teams:
        names = {
            (team.get("strTeam") or "").lower().strip(),
            (team.get("strTeamAlternate") or "").lower().strip(),
        }
        if normalized_query in names or any(normalized_query in value for value in names if value):
            _set_cache(cache_key, team)
            return team

    if teams:
        _set_cache(cache_key, teams[0])
        return teams[0]
    return None


def get_team_logo(team_name: str) -> Optional[str]:
    payload = _get_espn_team_payload(team_name)
    logos = (((payload or {}).get("team") or {}).get("logos")) or []
    if logos:
        return logos[0].get("href")
    return None


def get_team_colors(team_name: str) -> dict:
    payload = _get_espn_team_payload(team_name)
    team = (payload or {}).get("team") or {}
    return {
        "primary": team.get("color") or "1f3a8a",
        "secondary": team.get("alternateColor") or "ffffff",
    }


def _get_espn_team_schedule(team_name: str) -> list[dict]:
    cache_key = f"espn_team_schedule:{team_name.lower().strip()}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    espn_id = _search_team_espn_id(team_name)
    if not espn_id:
        return []

    response = requests.get(
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{espn_id}/schedule",
        headers=HTTP_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    events = response.json().get("events") or []
    _set_cache(cache_key, events)
    return events


def _get_espn_team_roster(team_name: str) -> list[dict]:
    cache_key = f"espn_team_roster:{team_name.lower().strip()}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    espn_id = _search_team_espn_id(team_name)
    if not espn_id:
        return []

    urls = [
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/teams/{espn_id}/roster",
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{espn_id}/roster",
    ]

    for url in urls:
        try:
            response = requests.get(
                url,
                headers=HTTP_HEADERS,
                timeout=15,
            )
            response.raise_for_status()
            athletes = response.json().get("athletes") or []
            _set_cache(cache_key, athletes)
            return athletes
        except Exception:
            continue

    return []


def _stats_map_from_record(item: dict) -> dict:
    return {
        stat.get("name"): stat.get("value")
        for stat in item.get("stats", [])
        if stat.get("name")
    }


def _find_total_record(team_payload: dict) -> dict:
    record_items = (((team_payload or {}).get("team") or {}).get("record") or {}).get("items") or []
    for item in record_items:
        if item.get("type") == "total":
            return _stats_map_from_record(item)
    return {}


def _find_record_by_type(team_payload: dict, record_type: str) -> dict:
    record_items = (((team_payload or {}).get("team") or {}).get("record") or {}).get("items") or []
    for item in record_items:
        if item.get("type") == record_type:
            return _stats_map_from_record(item)
    return {}


def _extract_recent_results(team_name: str, schedule_events: list[dict], limit: int) -> list[str]:
    normalized_team = team_name.lower().strip()
    completed: list[tuple[datetime, str]] = []

    for event in schedule_events:
        event_date = _parse_espn_date(event.get("date", ""))
        competition = (event.get("competitions") or [{}])[0]
        status_name = ((competition.get("status") or {}).get("type") or {}).get("name")
        if status_name != "STATUS_FULL_TIME":
            continue

        selected = None
        opponent = None
        for competitor in competition.get("competitors") or []:
            display_name = (competitor.get("team", {}).get("displayName") or "").lower().strip()
            if display_name == normalized_team:
                selected = competitor
            else:
                opponent = competitor

        if not selected or not event_date:
            continue

        if selected.get("winner") is True:
            result = "W"
        elif selected.get("winner") is False and opponent and opponent.get("winner") is True:
            result = "L"
        else:
            result = "D"
        completed.append((event_date, result))

    completed.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in completed[:limit]]


def _extract_completed_matches(team_name: str, schedule_events: list[dict], limit: int = 10) -> list[dict]:
    normalized_team = _normalize_text(team_name)
    completed = []

    for event in schedule_events:
        event_date = _parse_espn_date(event.get("date", ""))
        competition = (event.get("competitions") or [{}])[0]
        status_name = ((competition.get("status") or {}).get("type") or {}).get("name")
        if status_name != "STATUS_FULL_TIME":
            continue

        competitors = competition.get("competitors") or []
        selected = None
        opponent = None
        for competitor in competitors:
            display_name = _normalize_text(competitor.get("team", {}).get("displayName") or "")
            if display_name == normalized_team:
                selected = competitor
            else:
                opponent = competitor

        if not selected or not opponent or not event_date:
            continue

        selected_score = int(float((selected.get("score") or {}).get("value") or 0))
        opponent_score = int(float((opponent.get("score") or {}).get("value") or 0))
        if selected_score > opponent_score:
            result = "W"
        elif selected_score < opponent_score:
            result = "L"
        else:
            result = "D"

        completed.append(
            {
                "date": event_date,
                "result": result,
                "goals_for": selected_score,
                "goals_against": opponent_score,
                "venue": "casa" if selected.get("homeAway") == "home" else "fuera",
                "opponent": opponent.get("team", {}).get("displayName") or "Rival",
                "competition": competition.get("league", {}).get("name"),
            }
        )

    completed.sort(key=lambda item: item["date"], reverse=True)
    return completed[:limit]


def _points_from_results(results: list[str]) -> int:
    points = {"W": 3, "D": 1, "L": 0}
    return sum(points.get(item, 0) for item in results)


def _parse_record_summary(record_summary: str) -> tuple[int, int, int]:
    values = [int(item) for item in re.findall(r"\d+", record_summary or "")]
    if len(values) >= 3:
        return values[0], values[1], values[2]
    return 0, 0, 0


def _parse_standing_rank(standing_summary: str) -> Optional[int]:
    match = re.search(r"(\d+)", standing_summary or "")
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _clean_sheet_text(value: int) -> str:
    label = "portería a cero" if value == 1 else "porterías a cero"
    return f"{value} {label}"


def _extract_h2h_matches(team_a: str, team_b: str, schedule_events: list[dict], limit: int) -> list[dict]:
    normalized_a = team_a.lower().strip()
    normalized_b = team_b.lower().strip()
    h2h_matches = []

    for event in schedule_events:
        competition = (event.get("competitions") or [{}])[0]
        status_name = ((competition.get("status") or {}).get("type") or {}).get("name")
        if status_name != "STATUS_FULL_TIME":
            continue

        competitors = competition.get("competitors") or []
        names = [
            (competitor.get("team", {}).get("displayName") or "").lower().strip()
            for competitor in competitors
        ]
        if normalized_a not in names or normalized_b not in names:
            continue

        selected = None
        for competitor in competitors:
            display_name = (competitor.get("team", {}).get("displayName") or "").lower().strip()
            if display_name == normalized_a:
                selected = competitor
                break

        if not selected:
            continue

        selected_score = int(float((selected.get("score") or {}).get("value") or 0))
        opponent_score = next(
            (
                int(float((competitor.get("score") or {}).get("value") or 0))
                for competitor in competitors
                if competitor is not selected
            ),
            0,
        )

        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home_name = home.get("team", {}).get("displayName", "Local")
        away_name = away.get("team", {}).get("displayName", "Visitante")
        home_score = (home.get("score") or {}).get("displayValue", "0")
        away_score = (away.get("score") or {}).get("displayValue", "0")

        if selected.get("winner") is True:
            winner = team_a
        elif selected.get("winner") is False:
            winner = team_b
        else:
            winner = "draw"

        h2h_matches.append(
            {
                "date": event.get("date"),
                "result": f"{home_name} {home_score}-{away_score} {away_name}",
                "winner": winner,
                "venue": "casa" if selected.get("homeAway") == "home" else "fuera",
                "team_a_goals": selected_score if (selected.get("team", {}).get("displayName") or "").lower().strip() == normalized_a else opponent_score,
                "team_b_goals": opponent_score if (selected.get("team", {}).get("displayName") or "").lower().strip() == normalized_a else selected_score,
            }
        )

    h2h_matches.sort(key=lambda item: item.get("date", ""), reverse=True)
    return h2h_matches[:limit]


def _find_next_match_via_espn_api(team_name: str, league: str) -> Optional[dict]:
    espn_id = _search_team_espn_id(team_name)
    if not espn_id:
        return None

    response = requests.get(
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{espn_id}/schedule",
        headers=HTTP_HEADERS,
        timeout=15,
    )
    response.raise_for_status()

    events = response.json().get("events") or []
    now = datetime.now().astimezone()
    next_events: list[tuple[datetime, dict]] = []

    for event in events:
        event_date = _parse_espn_date(event.get("date", ""))
        if not event_date or event_date < now:
            continue
        next_events.append((event_date, event))

    if not next_events:
        return None

    _, event = min(next_events, key=lambda item: item[0])
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    normalized_team = team_name.lower().strip()

    selected_team = None
    opponent_team = None
    for competitor in competitors:
        display_name = (
            competitor.get("team", {}).get("displayName")
            or competitor.get("team", {}).get("shortDisplayName")
            or ""
        ).strip()
        if display_name.lower() == normalized_team:
            selected_team = competitor
        else:
            opponent_team = competitor

    if not selected_team and len(competitors) == 2:
        for competitor in competitors:
            display_name = (competitor.get("team", {}).get("displayName") or "").lower()
            if normalized_team in display_name or display_name in normalized_team:
                selected_team = competitor
            else:
                opponent_team = competitor

    if not selected_team or not opponent_team:
        return None

    return {
        "opponent": opponent_team.get("team", {}).get("displayName") or "Rival desconocido",
        "date": event.get("date"),
        "venue": "casa" if selected_team.get("homeAway") == "home" else "fuera",
        "competition": event.get("season", {}).get("displayName") or league,
        "api_source": "site.api.espn.com",
    }


def _find_next_match_realmadrid_official(team_name: str) -> Optional[dict]:
    normalized_team = team_name.lower().strip()
    if normalized_team not in {"real madrid", "real madrid cf"}:
        return None

    response = requests.get(
        "https://www.realmadrid.com/en-US/football",
        headers=HTTP_HEADERS,
        timeout=20,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    agenda_section = soup.find("section", id="agenda-section")
    if not agenda_section:
        return None

    first_card = agenda_section.find("article", class_=re.compile(r"event-card"))
    if not first_card:
        return None

    teams = [
        node.get_text(" ", strip=True)
        for node in first_card.select(".rm-game__name")
        if node.get_text(" ", strip=True)
    ]
    if len(teams) < 2:
        return None

    selected_index = 0 if teams[0].lower() == normalized_team else 1
    opponent_index = 1 - selected_index
    info_items = [node.get_text(" ", strip=True) for node in first_card.select(".event-card__info .event-card__text")]
    competition_node = first_card.select_one(".event-card__title")
    competition = competition_node.get_text(" ", strip=True) if competition_node else "Competición desconocida"
    match_date = info_items[0] if info_items else ""
    venue_name = info_items[1] if len(info_items) > 1 else ""
    venue = "casa" if selected_index == 0 else "fuera"
    if "bernab" in venue_name.lower():
        venue = "casa"

    return {
        "opponent": teams[opponent_index],
        "date": match_date,
        "venue": venue,
        "competition": competition,
        "venue_name": venue_name,
        "api_source": "realmadrid.com",
    }


def _find_next_match_thesportsdb(team_name: str) -> Optional[dict]:
    team = _search_thesportsdb_team(team_name)
    if not team:
        return None

    team_id = team.get("idTeam")
    team_display_name = team.get("strTeam") or team_name
    if not team_id:
        return None

    response = requests.get(
        f"https://www.thesportsdb.com/team/{team_id}?lan=ES",
        headers=HTTP_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    html = response.text

    match_line = re.search(
        r"Next Event</b>\s*\(([^)]+)\)\s*<br><img[^>]+>\s*<a[^>]*>([^<]+)</a>",
        html,
        re.IGNORECASE,
    )
    if not match_line:
        return None

    date_label = match_line.group(1).strip()
    event_name = match_line.group(2).strip()
    if " vs " in event_name:
        home_team, away_team = [part.strip() for part in event_name.split(" vs ", 1)]
    elif " @ " in event_name:
        away_team, home_team = [part.strip() for part in event_name.split(" @ ", 1)]
    else:
        return None

    normalized_display = team_display_name.lower().strip()
    normalized_input = team_name.lower().strip()
    if home_team.lower() in {normalized_display, normalized_input}:
        opponent = away_team
        venue = "casa"
    elif away_team.lower() in {normalized_display, normalized_input}:
        opponent = home_team
        venue = "fuera"
    else:
        return None

    league = team.get("strLeague") or "Competición desconocida"
    return {
        "opponent": opponent,
        "date": date_label,
        "venue": venue,
        "competition": league,
        "venue_name": team.get("strStadium"),
        "api_source": "thesportsdb.com",
    }


def find_next_match(team_name: str, league: str = "LaLiga") -> Optional[dict]:
    cache_key = f"next_match:{team_name}:{league}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    for strategy_name, strategy in [
        ("espn_api", lambda: _find_next_match_via_espn_api(team_name, league)),
        ("realmadrid_official", lambda: _find_next_match_realmadrid_official(team_name)),
        ("thesportsdb", lambda: _find_next_match_thesportsdb(team_name)),
    ]:
        try:
            match = strategy()
            if match:
                _set_cache(cache_key, match)
                return match
        except Exception as exc:
            logger.info("%s error for %s: %s", strategy_name, team_name, exc)

    return None


def get_team_stats(team_name: str, matches: int = 10) -> dict:
    cache_key = f"stats:{team_name}:{matches}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    team_payload = _get_espn_team_payload(team_name)
    schedule_events = _get_espn_team_schedule(team_name)
    completed_matches = _extract_completed_matches(team_name, schedule_events, limit=max(matches, 10))
    if not team_payload:
        return {
            "recent_form": [],
            "goals_avg_scored_home": 0.0,
            "goals_avg_conceded_home": 0.0,
            "goals_avg_scored_away": 0.0,
            "goals_avg_conceded_away": 0.0,
            "goals_avg_scored_total": 0.0,
            "goals_avg_conceded_total": 0.0,
            "attack_strength": 0.0,
            "defense_strength": 0.0,
            "last_10_results": [],
            "record_summary": "",
            "standing_summary": "",
            "games_played": 0,
            "recent_points_last5": 0,
            "recent_points_last10": 0,
            "recent_goals_scored_avg": 0.0,
            "recent_goals_conceded_avg": 0.0,
            "clean_sheets_last10": 0,
            "failed_to_score_last10": 0,
            "win_rate_last10": 0.0,
            "home_points_per_game": 0.0,
            "away_points_per_game": 0.0,
            "goal_balance_total": 0.0,
            "goal_balance_recent": 0.0,
            "standing_rank": None,
            "wins": 0,
            "draws": 0,
            "losses": 0,
        }

    total_stats = _find_total_record(team_payload)
    home_record = _find_record_by_type(team_payload, "home")
    away_record = _find_record_by_type(team_payload, "away")
    games_played = float(total_stats.get("gamesPlayed") or 0)
    home_games = float(total_stats.get("homeGamesPlayed") or 0)
    away_games = float(total_stats.get("awayGamesPlayed") or 0)
    points_for = float(total_stats.get("pointsFor") or 0)
    points_against = float(total_stats.get("pointsAgainst") or 0)
    home_points_for = float(total_stats.get("homePointsFor") or 0)
    home_points_against = float(total_stats.get("homePointsAgainst") or 0)
    away_points_for = float(total_stats.get("awayPointsFor") or 0)
    away_points_against = float(total_stats.get("awayPointsAgainst") or 0)

    goals_avg_scored_total = points_for / games_played if games_played else 0.0
    goals_avg_conceded_total = points_against / games_played if games_played else 0.0
    record_summary = (((team_payload.get("team") or {}).get("recordSummary")) or "")
    standing_summary = (((team_payload.get("team") or {}).get("standingSummary")) or "")
    recent_5_matches = completed_matches[:5]
    recent_10_matches = completed_matches[:10]
    recent_5_results = [item["result"] for item in recent_5_matches]
    recent_10_results = [item["result"] for item in recent_10_matches]
    recent_goals_for = sum(item["goals_for"] for item in recent_5_matches)
    recent_goals_against = sum(item["goals_against"] for item in recent_5_matches)
    wins, draws, losses = _parse_record_summary(record_summary)
    home_points = (float(home_record.get("wins") or 0) * 3) + float(home_record.get("ties") or 0)
    away_points = (float(away_record.get("wins") or 0) * 3) + float(away_record.get("ties") or 0)

    stats = {
        "recent_form": recent_5_results,
        "goals_avg_scored_home": home_points_for / home_games if home_games else goals_avg_scored_total,
        "goals_avg_conceded_home": home_points_against / home_games if home_games else goals_avg_conceded_total,
        "goals_avg_scored_away": away_points_for / away_games if away_games else goals_avg_scored_total,
        "goals_avg_conceded_away": away_points_against / away_games if away_games else goals_avg_conceded_total,
        "goals_avg_scored_total": goals_avg_scored_total,
        "goals_avg_conceded_total": goals_avg_conceded_total,
        "attack_strength": goals_avg_scored_total,
        "defense_strength": max(0.1, 2.5 - goals_avg_conceded_total),
        "last_10_results": recent_10_results,
        "record_summary": record_summary,
        "standing_summary": standing_summary,
        "games_played": int(games_played),
        "recent_points_last5": _points_from_results(recent_5_results),
        "recent_points_last10": _points_from_results(recent_10_results),
        "recent_goals_scored_avg": (recent_goals_for / len(recent_5_matches)) if recent_5_matches else goals_avg_scored_total,
        "recent_goals_conceded_avg": (recent_goals_against / len(recent_5_matches)) if recent_5_matches else goals_avg_conceded_total,
        "clean_sheets_last10": sum(1 for item in recent_10_matches if item["goals_against"] == 0),
        "failed_to_score_last10": sum(1 for item in recent_10_matches if item["goals_for"] == 0),
        "win_rate_last10": (sum(1 for item in recent_10_matches if item["result"] == "W") / len(recent_10_matches)) if recent_10_matches else 0.0,
        "home_points_per_game": (home_points / home_games) if home_games else 0.0,
        "away_points_per_game": (away_points / away_games) if away_games else 0.0,
        "goal_balance_total": goals_avg_scored_total - goals_avg_conceded_total,
        "goal_balance_recent": (
            ((recent_goals_for - recent_goals_against) / len(recent_5_matches))
            if recent_5_matches else (goals_avg_scored_total - goals_avg_conceded_total)
        ),
        "standing_rank": _parse_standing_rank(standing_summary),
        "wins": wins,
        "draws": draws,
        "losses": losses,
    }

    _set_cache(cache_key, stats)
    return stats


def get_h2h_stats(team_a: str, team_b: str, matches: int = 10) -> list:
    cache_key = f"h2h:{team_a}:{team_b}:{matches}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    schedule_events = _get_espn_team_schedule(team_a)
    h2h = _extract_h2h_matches(team_a, team_b, schedule_events, matches)

    _set_cache(cache_key, h2h)
    return h2h


def get_injuries(team_name: str) -> list:
    cache_key = f"injuries:{team_name}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    athletes = _get_espn_team_roster(team_name)
    injuries = []
    for athlete in athletes:
        status = athlete.get("status") or {}
        position = (athlete.get("position") or {}).get("displayName") or ""
        injury_items = athlete.get("injuries") or []
        if injury_items:
            for injury in injury_items:
                injuries.append(
                    {
                        "player": athlete.get("displayName", "Jugador"),
                        "position": position,
                        "status": injury.get("status") or injury.get("detail") or "lesionado",
                        "expected_return": injury.get("returnDate") or "incierto",
                    }
                )
        elif status.get("type") and status.get("type") != "active":
            injuries.append(
                {
                    "player": athlete.get("displayName", "Jugador"),
                    "position": position,
                    "status": status.get("name") or "no disponible",
                    "expected_return": "incierto",
                }
            )

    _set_cache(cache_key, injuries)
    return injuries


def calculate_form_difference(form_a: list, form_b: list) -> int:
    points = {"W": 3, "D": 1, "L": 0}
    points_a = sum(points.get(item, 0) for item in form_a)
    points_b = sum(points.get(item, 0) for item in form_b)
    return points_a - points_b


def calculate_h2h_advantage(h2h: list, team_name: str) -> int:
    wins = sum(1 for match in h2h if match.get("winner") == team_name)
    losses = sum(
        1
        for match in h2h
        if match.get("winner") not in {team_name, "draw", None}
    )
    return wins - losses


def calculate_probability(
    stats_a: dict,
    stats_b: dict,
    form_diff: int,
    quality_diff: float,
    h2h_advantage: int,
    injuries_a: list,
    injuries_b: list,
    venue: str = "casa",
) -> int:
    probability = 50.0
    probability += _clamp(form_diff * 3, -15, 15)
    probability += _clamp(quality_diff * 9, -18, 18)
    probability += _clamp((stats_a.get("goal_balance_recent", 0.0) - stats_b.get("goal_balance_recent", 0.0)) * 8, -12, 12)
    probability += _clamp((stats_a.get("home_points_per_game", 0.0) - stats_b.get("away_points_per_game", 0.0)) * 5, -8, 8)
    probability += _clamp((stats_a.get("clean_sheets_last10", 0) - stats_b.get("clean_sheets_last10", 0)) * 1.2, -5, 5)
    probability -= _clamp((stats_a.get("failed_to_score_last10", 0) - stats_b.get("failed_to_score_last10", 0)) * 1.5, -6, 6)
    probability += _clamp(h2h_advantage * 4, -8, 8)

    rank_a = stats_a.get("standing_rank")
    rank_b = stats_b.get("standing_rank")
    if rank_a and rank_b:
        probability += _clamp((rank_b - rank_a) * 0.9, -8, 8)

    if venue == "casa":
        probability += 7

    key_positions = {"portero", "defensa", "medio", "delantero"}
    probability -= 3 * sum(
        1
        for injury in injuries_a
        if injury.get("position", "").lower() in key_positions
    )
    probability += 3 * sum(
        1
        for injury in injuries_b
        if injury.get("position", "").lower() in key_positions
    )

    return int(round(_clamp(probability, 5, 95)))


def build_prediction_context(
    team_a: str,
    team_b: str,
    stats_a: dict,
    stats_b: dict,
    h2h: list,
    injuries_a: list,
    injuries_b: list,
    form_diff: int,
    quality_diff: float,
    h2h_advantage: int,
    venue: str,
) -> str:
    team_a_label = "CASA" if venue == "casa" else "FUERA"
    team_b_label = "FUERA" if venue == "casa" else "CASA"

    injuries_a_text = "\n".join(
        f"- {item['player']} ({item['status']})" for item in injuries_a
    ) or "- Sin bajas relevantes registradas"
    injuries_b_text = "\n".join(
        f"- {item['player']} ({item['status']})" for item in injuries_b
    ) or "- Sin bajas relevantes registradas"

    stronger_form = team_a if form_diff > 0 else team_b if form_diff < 0 else "igualados"
    stronger_attack = team_a if quality_diff > 0 else team_b if quality_diff < 0 else "igualados"
    stronger_h2h = team_a if h2h_advantage > 0 else team_b if h2h_advantage < 0 else "igualados"

    return f"""
DATOS OBJETIVOS - {team_a} vs {team_b}

{team_a.upper()} ({team_a_label}):
- Forma últimos 5: {" ".join(stats_a["recent_form"])}
- Goles promedio: {stats_a['goals_avg_scored_home']:.1f} GF / {stats_a['goals_avg_conceded_home']:.1f} GA
- Media global: {stats_a['goals_avg_scored_total']:.2f} GF / {stats_a['goals_avg_conceded_total']:.2f} GA
- Tendencia reciente: {stats_a['recent_goals_scored_avg']:.2f} GF / {stats_a['recent_goals_conceded_avg']:.2f} GA
- Puntos últimos 5: {stats_a['recent_points_last5']} | Porterías a cero últimos 10: {stats_a['clean_sheets_last10']}
- Clasificación: {stats_a['standing_summary'] or 'sin dato'}
- Últimos 10: {" ".join(stats_a["last_10_results"])}

{team_b.upper()} ({team_b_label}):
- Forma últimos 5: {" ".join(stats_b["recent_form"])}
- Goles promedio: {stats_b['goals_avg_scored_away']:.1f} GF / {stats_b['goals_avg_conceded_away']:.1f} GA
- Media global: {stats_b['goals_avg_scored_total']:.2f} GF / {stats_b['goals_avg_conceded_total']:.2f} GA
- Tendencia reciente: {stats_b['recent_goals_scored_avg']:.2f} GF / {stats_b['recent_goals_conceded_avg']:.2f} GA
- Puntos últimos 5: {stats_b['recent_points_last5']} | Porterías a cero últimos 10: {stats_b['clean_sheets_last10']}
- Clasificación: {stats_b['standing_summary'] or 'sin dato'}
- Últimos 10: {" ".join(stats_b["last_10_results"])}

H2H RECIENTE:
{chr(10).join(f"- {m['date']}: {m['result']} ({m['winner']})" for m in h2h[:5]) or "- Sin enfrentamientos recientes disponibles"}

MÉTRICAS COMPARATIVAS:
- Diferencia forma: {form_diff} puntos ({stronger_form})
- Diferencia de nivel ofensivo/defensivo: {quality_diff:.2f} ({stronger_attack})
- Ventaja H2H: {h2h_advantage} ({stronger_h2h})

LESIONES:
{team_a}: {chr(10)}{injuries_a_text}
{team_b}: {chr(10)}{injuries_b_text}
"""


def _extract_prediction_json(response: str) -> dict:
    if not response:
        raise ValueError("empty_response")

    fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    json_match = re.search(r"\{.*\}", response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))

    raise ValueError("json_not_found")


def _normalize_factor_text(value: str) -> str:
    text = (value or "").strip().strip(".")
    replacements = {
        "h2h result": "Historial reciente favorable",
        "xg difference": "Ventaja en generación ofensiva",
        "injury risk": "Impacto de las bajas",
        "xg discrepancy": "Diferencia entre ataque y solidez defensiva",
        "form inconsistency": "Rendimiento reciente irregular",
    }
    lowered = text.lower()
    if lowered in replacements:
        return replacements[lowered]
    return text[:120]


def _looks_generic_factor(value: str) -> bool:
    lowered = (value or "").strip().lower()
    generic_values = {
        "",
        "factor1",
        "factor2",
        "risk1",
        "h2h result",
        "xg difference",
        "injury risk",
        "xg discrepancy",
        "form inconsistency",
    }
    return lowered in generic_values


def _estimate_goals(team_attack: float, opponent_conceded: float, venue: str, form_diff_share: float) -> int:
    base_value = (team_attack * 0.6) + (opponent_conceded * 0.4) + form_diff_share
    if venue == "casa":
        base_value += 0.2
    return int(round(_clamp(base_value, 0, 4)))


def _build_stat_based_result(
    stats_a: dict,
    stats_b: dict,
    form_diff: int,
    h2h_advantage: int,
    venue: str,
) -> str:
    goals_a = _estimate_goals(
        stats_a["goals_avg_scored_total"],
        stats_b["goals_avg_conceded_total"],
        venue,
        _clamp(form_diff / 10, -0.5, 0.7),
    )
    goals_b = _estimate_goals(
        stats_b["goals_avg_scored_total"],
        stats_a["goals_avg_conceded_total"],
        "casa" if venue == "fuera" else "fuera",
        _clamp((-form_diff + (-h2h_advantage)) / 12, -0.5, 0.5),
    )

    if h2h_advantage >= 2 and goals_a <= goals_b:
        goals_a = min(4, goals_b + 1)
    if venue == "casa" and goals_a == goals_b:
        goals_a = min(4, goals_a + 1)

    return f"{goals_a}-{goals_b}"


def _generate_key_factors(
    team_a: str,
    team_b: str,
    stats_a: dict,
    stats_b: dict,
    form_diff: int,
    quality_diff: float,
    h2h_advantage: int,
    injuries_a: list,
    injuries_b: list,
    venue: str,
) -> list[str]:
    factors: list[str] = []

    if venue == "casa" and stats_a.get("home_points_per_game", 0) >= stats_b.get("away_points_per_game", 0) + 0.3:
        factors.append(
            f"Ventaja de local de {team_a} ({stats_a['home_points_per_game']:.2f} pts en casa vs {stats_b['away_points_per_game']:.2f} fuera de {team_b})"
        )

    if abs(form_diff) >= 2:
        better_team = team_a if form_diff > 0 else team_b
        better_stats = stats_a if form_diff > 0 else stats_b
        factors.append(f"Mejor dinámica reciente de {better_team} ({better_stats['recent_points_last5']} puntos en los últimos 5)")

    if abs(quality_diff) >= 0.15:
        better_team = team_a if quality_diff > 0 else team_b
        better_stats = stats_a if quality_diff > 0 else stats_b
        worse_stats = stats_b if quality_diff > 0 else stats_a
        factors.append(
            f"Mayor equilibrio ataque-defensa de {better_team} ({better_stats['goals_avg_scored_total']:.1f} GF y {better_stats['goals_avg_conceded_total']:.1f} GC frente a {worse_stats['goals_avg_scored_total']:.1f}/{worse_stats['goals_avg_conceded_total']:.1f})"
        )

    if abs(h2h_advantage) >= 1:
        better_team = team_a if h2h_advantage > 0 else team_b
        factors.append(f"Historial reciente más favorable para {better_team}")

    rank_a = stats_a.get("standing_rank")
    rank_b = stats_b.get("standing_rank")
    if rank_a and rank_b and (rank_b - rank_a) >= 4:
        factors.append(f"{team_a} llega mejor posicionado en la clasificación ({rank_a} vs {rank_b})")

    clean_sheet_gap = stats_a.get("clean_sheets_last10", 0) - stats_b.get("clean_sheets_last10", 0)
    if clean_sheet_gap >= 2:
        factors.append(f"{team_a} muestra más solidez defensiva reciente ({_clean_sheet_text(stats_a['clean_sheets_last10'])} en 10 partidos)")

    if len(injuries_b) > len(injuries_a):
        factors.append(f"{team_b} llega con más bajas relevantes")

    return _dedupe_texts(factors)[:3]


def _generate_risks(
    team_a: str,
    team_b: str,
    stats_a: dict,
    stats_b: dict,
    form_diff: int,
    quality_diff: float,
    injuries_a: list,
    injuries_b: list,
) -> list[str]:
    risks: list[str] = []

    if abs(form_diff) <= 2:
        risks.append("La forma reciente de ambos equipos es bastante pareja")

    if stats_a.get("failed_to_score_last10", 0) >= 2:
        risks.append(f"{team_a} ha tenido tramos de poca eficacia ofensiva ({stats_a['failed_to_score_last10']} partidos sin marcar en los últimos 10)")

    if stats_b.get("recent_goals_scored_avg", 0) >= 1.2:
        risks.append(f"{team_b} mantiene capacidad para marcar en transiciones ({stats_b['recent_goals_scored_avg']:.1f} goles recientes por partido)")

    if stats_a.get("clean_sheets_last10", 0) <= 1:
        risks.append(f"{team_a} no siempre consigue cerrar su portería ({_clean_sheet_text(stats_a['clean_sheets_last10'])} en los últimos 10)")

    if stats_a.get("goal_balance_recent", 0) < stats_a.get("goal_balance_total", 0):
        risks.append(f"El momento reciente de {team_a} está algo por debajo de su media global")

    if abs(quality_diff) <= 0.15:
        risks.append("El rendimiento global de ambos equipos está muy equilibrado")

    if injuries_a:
        risks.append(f"{team_a} tiene bajas o dudas que pueden alterar el plan")

    if injuries_b:
        risks.append(f"{team_b} también llega con incertidumbre en la plantilla")

    if not risks:
        risks.append("Un gol temprano puede cambiar por completo el guion del partido")
        risks.append(f"{team_b} puede competir si aprovecha sus primeras ocasiones")
        risks.append("Un partido cerrado puede reducir la fiabilidad del marcador exacto")

    while len(_dedupe_texts(risks)) < 3:
        fallback_pool = [
            f"{team_b} puede competir si convierte su primera ocasión clara",
            "Un partido muy táctico puede reducir la fiabilidad del marcador exacto",
            f"Cualquier ajuste de once o rotación puede alterar el guion previsto para {team_a}",
        ]
        risks.extend(fallback_pool)

    return _dedupe_texts(risks)[:3]


def _dedupe_texts(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value.strip())
    return output


def _format_match_metadata(match_info: Optional[dict]) -> dict:
    if not match_info:
        return {}
    return {
        "date": match_info.get("date"),
        "competition": match_info.get("competition"),
        "venue": match_info.get("venue"),
        "venue_name": match_info.get("venue_name"),
        "source": match_info.get("api_source"),
    }


def calculate_confidence(probability: int) -> str:
    if probability >= 75:
        return "alta"
    if probability >= 60:
        return "media"
    return "baja"


def save_prediction(
    team_a: str,
    team_b: str,
    prediction: dict,
    probability: int,
    stats_used: dict,
    chat_id: Optional[int] = None,
    match_info: Optional[dict] = None,
) -> dict:
    data = _load_predictions()

    new_prediction = {
        "id": f"pred_{int(datetime.now().timestamp())}",
        "chat_id": str(chat_id) if chat_id is not None else None,
        "team_a": team_a,
        "team_b": team_b,
        "prediction": prediction,
        "probability": probability,
        "stats_used": stats_used,
        "match_info": match_info or {},
        "created_at": datetime.now().isoformat(),
    }

    data["predictions"].append(new_prediction)
    _save_predictions(data)
    return new_prediction


def delete_prediction(chat_id: int, prediction_id: str) -> bool:
    data = _load_predictions()
    original_count = len(data.get("predictions", []))
    data["predictions"] = [
        item
        for item in data.get("predictions", [])
        if not (str(item.get("chat_id")) == str(chat_id) and item.get("id") == prediction_id)
    ]
    changed = len(data["predictions"]) != original_count
    if changed:
        _save_predictions(data)
    return changed


def get_user_predictions(chat_id: int, limit: int = 20) -> list:
    data = _load_predictions()
    predictions = [
        item
        for item in data.get("predictions", [])
        if str(item.get("chat_id")) == str(chat_id)
    ]
    return sorted(predictions, key=lambda item: item.get("created_at", ""), reverse=True)[:limit]


def predict_match(team_a: str, team_b: Optional[str] = None, chat_id: Optional[int] = None) -> dict:
    from app.services.llm_provider import smart_llm

    resolved_a = resolve_team_name(team_a)
    if resolved_a["status"] == "resolved":
        team_a = resolved_a["resolved_name"]
    elif resolved_a["status"] == "suggest":
        return {
            "error": f"No encontré una coincidencia exacta para '{team_a}'.",
            "suggestions": resolved_a["suggestions"],
            "field": "team_a",
            "original_query": team_a,
        }
    elif resolved_a["status"] == "not_found":
        return {"error": f"No encontré ningún equipo parecido a '{team_a}'."}

    venue = "casa"
    match_info = {}
    if not team_b:
        match = find_next_match(team_a)
        if not match:
            return {"error": f"No se encontró el próximo partido de {team_a}."}
        team_b = match["opponent"]
        venue = match.get("venue", "casa")
        match_info = _format_match_metadata(match)
    else:
        resolved_b = resolve_team_name(team_b)
        if resolved_b["status"] == "resolved":
            team_b = resolved_b["resolved_name"]
        elif resolved_b["status"] == "suggest":
            return {
                "error": f"No encontré una coincidencia exacta para '{team_b}'.",
                "suggestions": resolved_b["suggestions"],
                "field": "team_b",
                "original_query": team_b,
                "team_a": team_a,
            }
        elif resolved_b["status"] == "not_found":
            return {"error": f"No encontré ningún equipo parecido a '{team_b}'."}
        match_info = {"venue": venue}

    stats_a = get_team_stats(team_a, matches=10)
    stats_b = get_team_stats(team_b, matches=10)
    h2h = get_h2h_stats(team_a, team_b)
    injuries_a = get_injuries(team_a)
    injuries_b = get_injuries(team_b)

    form_diff = calculate_form_difference(stats_a["recent_form"], stats_b["recent_form"])
    quality_diff = (
        (stats_a["goals_avg_scored_total"] - stats_a["goals_avg_conceded_total"])
        - (stats_b["goals_avg_scored_total"] - stats_b["goals_avg_conceded_total"])
    )
    h2h_advantage = calculate_h2h_advantage(h2h, team_a)

    context = build_prediction_context(
        team_a=team_a,
        team_b=team_b,
        stats_a=stats_a,
        stats_b=stats_b,
        h2h=h2h,
        injuries_a=injuries_a,
        injuries_b=injuries_b,
        form_diff=form_diff,
        quality_diff=quality_diff,
        h2h_advantage=h2h_advantage,
        venue=venue,
    )

    prompt = f"""
Analiza estos datos objetivos de fútbol:

{context}

Devuelve SOLO JSON válido con:
- predicted_result: resultado exacto tipo "2-1"
- key_factors: máximo 3 factores en español
- risks: máximo 3 riesgos en español
"""

    fallback_result = _build_stat_based_result(stats_a, stats_b, form_diff, h2h_advantage, venue)
    fallback_factors = _generate_key_factors(
        team_a, team_b, stats_a, stats_b, form_diff, quality_diff, h2h_advantage, injuries_a, injuries_b, venue
    )
    fallback_risks = _generate_risks(team_a, team_b, stats_a, stats_b, form_diff, quality_diff, injuries_a, injuries_b)

    prediction_data = {
        "predicted_result": fallback_result,
        "key_factors": fallback_factors,
        "risks": fallback_risks,
    }

    try:
        response = smart_llm([{"role": "user", "content": prompt}])
        parsed = _extract_prediction_json(response)
        parsed_factors = [
            _normalize_factor_text(item)
            for item in (parsed.get("key_factors") or [])
            if not _looks_generic_factor(item)
        ]
        parsed_risks = [
            _normalize_factor_text(item)
            for item in (parsed.get("risks") or [])
            if not _looks_generic_factor(item)
        ]
        prediction_data.update(
            {
                "predicted_result": parsed.get("predicted_result", prediction_data["predicted_result"]),
                "key_factors": _dedupe_texts(parsed_factors or prediction_data["key_factors"])[:3],
                "risks": _dedupe_texts(parsed_risks or prediction_data["risks"])[:3],
            }
        )
    except Exception as exc:
        logger.warning("Prediction LLM fallback for %s vs %s: %s", team_a, team_b, exc)

    probability = calculate_probability(
        stats_a=stats_a,
        stats_b=stats_b,
        form_diff=form_diff,
        quality_diff=quality_diff,
        h2h_advantage=h2h_advantage,
        injuries_a=injuries_a,
        injuries_b=injuries_b,
        venue=venue,
    )
    prediction_data["probability"] = probability

    saved = save_prediction(
        team_a=team_a,
        team_b=team_b,
        prediction=prediction_data,
        probability=probability,
        stats_used={
            "team_a_goals_avg": stats_a["goals_avg_scored_total"],
            "team_b_goals_avg": stats_b["goals_avg_scored_total"],
            "team_a_goals_against_avg": stats_a["goals_avg_conceded_total"],
            "team_b_goals_against_avg": stats_b["goals_avg_conceded_total"],
            "h2h_wins_team_a": sum(1 for match in h2h if match.get("winner") == team_a),
            "form_diff": form_diff,
            "quality_diff": quality_diff,
            "venue": venue,
            "recent_points_last5_team_a": stats_a["recent_points_last5"],
            "recent_points_last5_team_b": stats_b["recent_points_last5"],
            "clean_sheets_team_a": stats_a["clean_sheets_last10"],
            "clean_sheets_team_b": stats_b["clean_sheets_last10"],
        },
        chat_id=chat_id,
        match_info=match_info,
    )

    return {
        "result": prediction_data.get("predicted_result", "1-1"),
        "probability": probability,
        "factors": prediction_data.get("key_factors", []),
        "risks": prediction_data.get("risks", []),
        "confidence": calculate_confidence(probability),
        "stats_used": saved["stats_used"],
        "match_info": saved.get("match_info", {}),
        "id": saved["id"],
        "team_a": team_a,
        "team_b": team_b,
        "team_a_logo": get_team_logo(team_a),
        "team_b_logo": get_team_logo(team_b),
        "team_a_colors": get_team_colors(team_a),
        "team_b_colors": get_team_colors(team_b),
        "type": "prediction_result",
    }
