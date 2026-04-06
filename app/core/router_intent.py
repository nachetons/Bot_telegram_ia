from app.services.llm_client import call_llm
from app.services.llm_client_cloud import call_llm_cloud


ALLOWED_INTENTS = ["movies", "images", "weather", "wiki", "search"]


# -----------------------
# CLEAN RESPONSE
# -----------------------
def clean_intent(text: str):
    if not text:
        return None

    text = text.strip().lower()

    # quitar cosas raras
    text = text.replace(".", "").replace("\n", "")

    if text in ALLOWED_INTENTS:
        return text

    return None


# -----------------------
# 1. FAST ROUTER (COMANDOS)
# -----------------------
def detect_intent_fast(query: str):
    q = query.lower().strip()

    # -----------------------
    # MOVIES / VIDEO
    # -----------------------
    if q.startswith("/video"):
        return "movies"

    # -----------------------
    # IMAGES
    # -----------------------
    if q.startswith("/img") or q.startswith("/image"):
        return "images"

    # -----------------------
    # WIKI
    # -----------------------
    if q.startswith("/wiki"):
        return "wiki"

    # -----------------------
    # WEATHER
    # -----------------------
    if q.startswith("/tiempo") or q.startswith("/weather"):
        return "weather"

    # -----------------------
    # LIBRARY (🔥 NUEVO)
    # -----------------------
    if q.startswith("/library") or q.startswith("/catalog") or q.startswith("/menu"):
        return "library"

    # -----------------------
    # SERIES (opcional futuro)
    # -----------------------
    if q.startswith("/series"):
        return "series"

    return None



# -----------------------
# 2. LOCAL LLM
# -----------------------
def detect_intent_llm(query: str):
    messages = [
        {
            "role": "system",
            "content": """
Eres un sistema de clasificación de intención.

Responde SOLO con UNA palabra EXACTA de esta lista:
movies, images, weather, wiki, search

No expliques nada.
"""
        },
        {"role": "user", "content": query}
    ]

    response = call_llm(messages)

    return clean_intent(response)


# -----------------------
# 3. CLOUD LLM (OpenRouter)
# -----------------------
def detect_intent_llm_cloud(query: str):
    messages = [
        {
            "role": "system",
            "content": """
Clasifica la intención del usuario.

Responde SOLO con una palabra EXACTA:
movies, images, weather, wiki, search
"""
        },
        {"role": "user", "content": query}
    ]

    response = call_llm_cloud(messages)

    return clean_intent(response)

from app.services.llm_client_cloud import call_llm_cloud


def extract_movie_title(query: str):
    messages = [
        {
            "role": "system",
            "content": """
Extrae SOLO el nombre de la película.

Reglas:
- Responde SOLO el título
- Sin explicaciones
- Sin frases
- Sin puntuación extra

Ejemplos:
Input: "puedes buscar la pelicula los aristogatos"
Output: "los aristogatos"

Input: "quiero ver iron man 2"
Output: "iron man 2"
"""
        },
        {"role": "user", "content": query}
    ]

    return call_llm_cloud(messages).strip().lower()


# -----------------------
# 4. MAIN ROUTER (HÍBRIDO)
# -----------------------
def detect_intent(query: str):

    # 1️⃣ comandos (máxima prioridad)
    intent = detect_intent_fast(query)
    if intent:
        return intent

    # 2️⃣ LLM local
    try:
        intent = detect_intent_llm(query)
        if intent:
            return intent
    except Exception as e:
        print("⚠️ LOCAL LLM FAILED:", e)

    # 3️⃣ LLM cloud
    try:
        intent = detect_intent_llm_cloud(query)
        if intent:
            return intent
    except Exception as e:
        print("⚠️ CLOUD LLM FAILED:", e)

    # 4️⃣ fallback final
    return "search"