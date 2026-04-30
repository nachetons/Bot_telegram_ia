"""Intent dispatcher with strategy pattern for scalable intent handling."""

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol


class IntentHandler(Protocol):
    """Protocolo para handlers de intents."""

    def __call__(self, query: str, chat_id: int) -> tuple[bool, Any, List[str]]:
        """Ejecuta el handler y retorna (handled, result, sources)."""
        ...


class BaseIntentHandler(ABC):
    """Clase base para todos los handlers de intents."""

    @abstractmethod
    def get_intent_name(self) -> str:
        """Retorna el nombre del intent que maneja este handler."""
        pass

    @abstractmethod
    def handle(self, query: str, chat_id: int) -> tuple[bool, Any, List[str]]:
        """Maneja la consulta y retorna resultado."""
        pass


class IntentDispatcher:
    """Dispatcher centralizado para intents con estrategia."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._handlers: Dict[str, BaseIntentHandler] = {}
        return cls._instance

    def register(self, handler: BaseIntentHandler):
        """Registra un nuevo handler de intent."""
        self._handlers[handler.get_intent_name()] = handler

    def get_handler(self, intent_name: str) -> Optional[BaseIntentHandler]:
        """Obtiene el handler para un intent específico."""
        return self._handlers.get(intent_name)

    def has_intent(self, intent_name: str) -> bool:
        """Verifica si existe un handler para el intent."""
        return intent_name in self._handlers

    def list_handlers(self) -> Dict[str, BaseIntentHandler]:
        """Lista todos los handlers registrados."""
        return self._handlers.copy()


# Instancia global
intent_dispatcher = IntentDispatcher()
