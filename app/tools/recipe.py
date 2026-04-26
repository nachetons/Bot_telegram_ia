import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("recipe_tool")

DATA_FILE = Path("data/recipes.json")

# ⚠️ Headers más realistas (evita bloqueos)
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}

_cache: Dict[str, Tuple[Any, datetime]] = {}
_CACHE_DURATION_HOURS = 2


# ------------------ CACHE ------------------

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


# ------------------ STORAGE ------------------

def _load_recipes() -> List[Dict]:
    if not DATA_FILE.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        return []

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("recipes", [])
    except Exception:
        return []


def _save_recipes(recipes: List[Dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"recipes": recipes}, f, indent=2, ensure_ascii=False)


def _save_prediction(chat_id: str, recipe_name: str, url: str) -> None:
    recipes = _load_recipes()

    data = {
        "chat_id": chat_id,
        "recipe_name": recipe_name,
        "url": url,
        "created_at": datetime.now().isoformat(),
        "id": f"recipe_{int(datetime.now().timestamp())}",
    }

    recipes.append(data)
    _save_recipes(recipes)


def get_user_recipes(chat_id: str) -> List[Dict]:
    return [r for r in _load_recipes() if r.get("chat_id") == chat_id]


def clear_user_recipes(chat_id: str) -> None:
    _save_recipes([r for r in _load_recipes() if r.get("chat_id") != chat_id])


# ------------------ PREDICCIÓN SIMPLE ------------------

def predict_recipe_success(recipe_name: str) -> Dict:
    return {
        "predicted_success": True,
        "probability": 75,
        "factors": ["Receta estándar"],
        "risks": ["Depende de ejecución"],
    }


# ------------------ SEARCH ------------------

def search_recipes(query: str, max_results: int = 5) -> Dict:
    cache_key = f"recipes:{query}"
    cached = _get_from_cache(cache_key)
    if cached:
        return cached

    recipes = []
    seen = set()

    try:
        url = f"https://cookpad.com/es/buscar/{query.replace(' ', '-')}"
        response = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.select('a[href*="/recetas/"]'):
            href = link.get("href", "")
            title = link.get_text(strip=True)

            if not title or "nuevo" in href:
                continue

            full_url = f"https://cookpad.com{href}" if not href.startswith("http") else href

            if full_url in seen:
                continue

            seen.add(full_url)

            recipes.append({
                "title": title,
                "url": full_url,
            })

            if len(recipes) >= max_results:
                break

    except Exception as e:
        logger.error(f"Error searching recipes: {e}")

    if not recipes:
        recipes.append({
            "title": f"Recetas de {query}",
            "url": f"https://cookpad.com/es/buscar/{query.replace(' ', '-')}",
        })

    result = {"recipes": recipes}
    _set_cache(cache_key, result)
    return result


# ------------------ DETAILS (CLAVE) ------------------

def get_recipe_details(url: str) -> Dict:
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # -------- TITLE --------
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "Receta"

        # -------- INGREDIENTES --------
        ingredients = []

        for li in soup.select('li[id^="ingredient_"]'):
            qty = li.select_one("bdi")
            name = li.select_one("span")

            qty_text = qty.get_text(strip=True) if qty else ""
            name_text = name.get_text(strip=True) if name else ""

            full = f"{qty_text} {name_text}".strip()

            if full:
                ingredients.append(full)

        # -------- PASOS --------
        instructions = []

        for step in soup.select('li[id^="step_"]'):
            text_block = step.select_one("p")

            if text_block:
                text = text_block.get_text(strip=True)

                if text:
                    instructions.append(text)

        logger.info(
            f"📝 {title}: {len(ingredients)} ingredientes, {len(instructions)} pasos"
        )

        return {
            "title": title,
            "ingredients": ingredients,
            "instructions": instructions,
            "url": url,
        }

    except Exception as e:
        logger.error(f"Error fetching recipe details: {e}")
        return {
            "title": "Receta",
            "ingredients": ["Ver receta completa en la fuente"],
            "instructions": ["Seguir instrucciones de la fuente"],
            "url": url,
        }


# ------------------ MAIN ------------------

def predict_match(recipe_name: str, chat_id: str) -> Tuple[Dict, List[str]]:
    recipes_data = search_recipes(recipe_name)

    ingredients = []
    instructions = []
    url = ""

    if recipes_data.get("recipes"):
        url = recipes_data["recipes"][0].get("url")

        if url:
            details = get_recipe_details(url)
            ingredients = details.get("ingredients", [])
            instructions = details.get("instructions", [])

    _save_prediction(chat_id, recipe_name, url)

    return {
        "recipe_name": recipe_name,
        "ingredients": ingredients,
        "instructions": instructions,
    }, ["recipe_tool"]


# ------------------ HISTORY ------------------

def get_user_history(chat_id: str) -> Dict:
    recipes = get_user_recipes(chat_id)

    if not recipes:
        return {"type": "text", "text": "📭 No tienes recetas guardadas aún."}

    text = "📚 HISTORIAL DE RECETAS\n"

    for r in reversed(recipes):
        text += (
            f"\n• {r.get('recipe_name')}"
            f"\n  Probabilidad: {r.get('probability', 'N/A')}%\n"
        )

    return {"type": "text", "text": text}


def clear_history(chat_id: str) -> Dict:
    clear_user_recipes(chat_id)
    return {"type": "text", "text": "✅ Historial de recetas limpiado."}