"""Manga intent handler following the strategy pattern."""

from typing import Any, Dict, List, Tuple

from app.core.intent_dispatcher import BaseIntentHandler, intent_dispatcher


class MangaHandler(BaseIntentHandler):
    """Handler para el intent manga."""

    def get_intent_name(self) -> str:
        return "manga"

    def handle(self, query: str, chat_id: int) -> Tuple[bool, Any, List[str]]:
        from app.tools.manga import manga_search
        
        if not query.strip():
            return True, {"type": "text", "text": "¿Qué manga quieres buscar?"}, ["manga_tool"]
        
        result = manga_search(query)
        return True, result, ["manga_tool"]


# Registrar handler al importar
intent_dispatcher.register(MangaHandler())
