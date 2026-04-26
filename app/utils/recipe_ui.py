from typing import List


def recipe_menu() -> dict:
    return {
        "type": "menu",
        "text": "🍳 RECETAS\n¿Qué quieres hacer?",
        "buttons": [
            [{"text": "🔍 Buscar Receta", "callback_data": "recipe:search"}],
            [{"text": "📚 Mi Historial", "callback_data": "recipe:history"}],
            [{"text": "🗑️ Limpiar Historial", "callback_data": "recipe:clear"}],
        ],
    }


def recipe_list_menu(query: str, recipes: List[dict]) -> dict:
    buttons = []

    for i, recipe in enumerate(recipes[:5]):
        title = recipe.get("title", "Receta")[:40]

        buttons.append([
            {
                "text": f"🍽️ {title}",
                "callback_data": f"recipe:select:{i}"
            }
        ])

    buttons.append([{"text": "↩️ Volver", "callback_data": "recipe:back"}])

    return {
        "type": "menu",
        "text": f"🔎 Resultados para:\n{query}\n\nSelecciona una receta:",
        "buttons": buttons
    }


def recipe_detail_menu(details: dict) -> dict:
    ingredients_list = details.get("ingredients", [])
    steps_list = details.get("instructions", [])

    ingredients = "\n".join(f"• {i}" for i in ingredients_list[:10]) or "No encontrados"
    steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps_list[:5])) or "No encontrados"

    text = (
        f"🍽️ {details.get('title', 'Receta')}\n\n"
        f"🛒 INGREDIENTES:\n{ingredients}\n\n"
        f"📝 ELABORACIÓN:\n{steps}"
    )

    return {
        "type": "menu",
        "text": text,
        "buttons": [
            [{"text": "↩️ Volver", "callback_data": "recipe:back"}],
        ]
    }


def recipe_history_menu(recipes: list) -> dict:
    if not recipes:
        return {"type": "text", "text": "📭 No tienes recetas guardadas aún."}

    text = "📚 HISTORIAL DE RECETAS\n"

    for r in reversed(recipes):
        text += f"\n• {r.get('recipe_name', 'Receta')}"

    return {
        "type": "menu",
        "text": text,
        "buttons": [
            [{"text": "↩️ Volver", "callback_data": "recipe:back"}],
            [{"text": "🗑️ Limpiar Todo", "callback_data": "recipe:clear"}],
        ],
    }