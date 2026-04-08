from app.core.router_intent import detect_intent, extract_movie_title
from app.tools.images import get_images
from app.tools.weather import get_weather
from app.tools.wiki import wikipedia
from app.tools.jellyfin import jellyfin
from app.core.context_builder import build_context
from app.core.refiner import refine_context
from app.services.llm_provider import smart_llm
from app.core.prompt import system_prompt


def agent(query: str):
    intent = detect_intent(query)

    # -----------------------
    # IMAGES
    # -----------------------
    if intent == "images":
        images = get_images(query)

        return {
            "type": "images",
            "images": images
        }, ["images_tool"]

    # -----------------------
    # WEATHER
    # -----------------------
    elif intent == "weather":
        context, sources = get_weather(query)
        return context, sources

    # -----------------------
    # WIKI
    # -----------------------
    elif intent == "wiki":
        context, sources = wikipedia(query)

        # fallback a LLM si wiki falla
        if not context:
            context, sources = build_context(query)
            context = refine_context(context)

            messages = [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": f"{query}\n\n{context}"}
            ]

            response = smart_llm(messages)  # 🔥 CAMBIO CLAVE
            return response, sources

        return context, sources

    # -----------------------
    # MOVIES (JELLYFIN)
    # -----------------------
    elif intent == "movies":

        clean_query = extract_movie_title(query)

        # 🔒 PROTECCIÓN: LLM falló o no entendió
        if not clean_query:
            # intentar como wiki (por si era una pregunta tipo "quien es...")
            context, sources = wikipedia(query)
            if context:
                return context, sources

            return {
                "error": "No he entendido qué película buscas."
            }, ["jellyfin_tool"]

        # 🎬 Buscar en Jellyfin
        result = jellyfin.run(clean_query)

        # 🔒 Error interno de Jellyfin
        if isinstance(result, dict) and "error" in result:
            return result, ["jellyfin_tool"]

        # 🔍 No hay resultados → fallback inteligente
        if not result:
            context, sources = wikipedia(query)

            if context:
                return context, sources

            return {
                "error": f"No he encontrado la película: {clean_query}"
            }, ["jellyfin_tool"]

        return result, ["jellyfin_tool"]
    
    # -----------------------
    # LIBRARY (JELLYFIN)
    # -----------------------
    elif intent == "library":

        library = jellyfin.get_library()

        buttons = []

        # MOVIES
        for m in library["movies"]:
            buttons.append([
                {
                    "text": f"🎬 {m['title']}",
                    "callback_data": f"play_movie:{m['id']}"
                }
            ])

        # SERIES
        for s in library["series"]:
            buttons.append([
                {
                    "text": f"📺 {s['title']}",
                    "callback_data": f"open_series:{s['id']}"
                }
            ])

        return {
            "type": "menu",
            "text": "🎥 Biblioteca",
            "buttons": [
                [{"text": "🎬 Películas", "callback_data": "open_library:movies"}],
                [{"text": "📺 Series", "callback_data": "open_library:series"}]
            ]
            }, ["jellyfin_library"]

    # -----------------------
    # DEFAULT (LLM)
    # -----------------------
    else:
        context, sources = build_context(query)
        context = refine_context(context)

        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": f"{query}\n\n{context}"}
        ]

        response = smart_llm(messages)  # 🔥 CAMBIO CLAVE

        return response, sources