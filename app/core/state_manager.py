"""Centralized state management for chat sessions."""

import threading
from typing import Any, Dict, Optional


class ChatStateManager:
    """Gestor centralizado de estado por chat_id con TTL automático."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Inicializa los diccionarios de estado."""
        self.sessions: Dict[int, Dict[str, Any]] = {}
        self.locks: Dict[int, threading.Lock] = {}

    # ========== PENDING FOLLOWUPS ==========
    def set_pending_followup(self, chat_id: int, intent: str) -> None:
        """Establece un intent pendiente para el chat."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            if "pending_followups" not in self.sessions[chat_id]:
                self.sessions[chat_id]["pending_followups"] = {}
            self.sessions[chat_id]["pending_followups"][intent] = True

    def get_pending_followup(self, chat_id: int) -> Optional[str]:
        """Obtiene el intent pendiente actual."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                return None
            return list(self.sessions[chat_id].get("pending_followups", {}).keys())

    def pop_pending_followup(self, chat_id: int) -> Optional[str]:
        """Obtiene y elimina el intent pendiente."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                return None
            followups = self.sessions[chat_id].get("pending_followups", {})
            if followups:
                return followups.popitem()[0]
            return None

    def clear_pending_followup(self, chat_id: int) -> None:
        """Limpia todos los pending followups."""
        lock = self._get_lock(chat_id)
        with lock:
            if "pending_followups" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["pending_followups"]

    # ========== PLAYLIST SESSIONS ==========
    def set_playlist_session(
        self, chat_id: int, action: str, playlist_name: str
    ) -> None:
        """Establece sesión de playlist."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["playlist"] = {
                "action": action,
                "playlist": playlist_name,
            }

    def get_playlist_session(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene sesión de playlist."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("playlist")

    def clear_playlist_session(self, chat_id: int) -> None:
        """Limpia sesión de playlist."""
        lock = self._get_lock(chat_id)
        with lock:
            if "playlist" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["playlist"]

    # ========== TRANSLATE SESSIONS ==========
    def set_translate_session(
        self, chat_id: int, step: str, text_value: Optional[str] = None
    ) -> None:
        """Establece sesión de traducción."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["translate"] = {
                "step": step,
                "text": text_value or "",
            }

    def get_translate_session(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene sesión de traducción."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("translate")

    def clear_translate_session(self, chat_id: int) -> None:
        """Limpia sesión de traducción."""
        lock = self._get_lock(chat_id)
        with lock:
            if "translate" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["translate"]

    # ========== TRANSLATE RESULTS ==========
    def set_translate_result(self, chat_id: int, payload: Any) -> None:
        """Guarda resultado de traducción."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["translate_result"] = payload

    def get_translate_result(self, chat_id: int) -> Optional[Any]:
        """Obtiene resultado de traducción."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("translate_result")

    def clear_translate_result(self, chat_id: int) -> None:
        """Limpia resultado de traducción."""
        lock = self._get_lock(chat_id)
        with lock:
            if "translate_result" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["translate_result"]

    # ========== WALLAPOP SESSIONS ==========
    def set_wallapop_session(self, chat_id: int, payload: Any) -> None:
        """Establece sesión de Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["wallapop"] = payload

    def get_wallapop_session(self, chat_id: int) -> Optional[Any]:
        """Obtiene sesión de Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("wallapop")

    def clear_wallapop_session(self, chat_id: int) -> None:
        """Limpia sesión de Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if "wallapop" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["wallapop"]

    # ========== WALLAPOP RESULT SESSIONS ==========
    def set_wallapop_result_session(self, chat_id: int, payload: Any) -> None:
        """Establece sesión de resultado Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["wallapop_result"] = payload

    def get_wallapop_result_session(self, chat_id: int) -> Optional[Any]:
        """Obtiene sesión de resultado Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("wallapop_result")

    def clear_wallapop_result_session(self, chat_id: int) -> None:
        """Limpia sesión de resultado Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if "wallapop_result" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["wallapop_result"]

    # ========== WALLAPOP ITEM MESSAGES ==========
    def set_wallapop_item_message(
        self, chat_id: int, payload: Any
    ) -> None:
        """Establece mensaje de item Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["wallapop_item"] = payload

    def get_wallapop_item_message(self, chat_id: int) -> Optional[Any]:
        """Obtiene mensaje de item Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("wallapop_item")

    def clear_wallapop_item_message(self, chat_id: int) -> None:
        """Limpia mensaje de item Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if "wallapop_item" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["wallapop_item"]

    # ========== WALLAPOP ALERT SESSIONS ==========
    def set_wallapop_alert_session(self, chat_id: int, payload: Any) -> None:
        """Establece sesión de alerta Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["wallapop_alert"] = payload

    def get_wallapop_alert_session(self, chat_id: int) -> Optional[Any]:
        """Obtiene sesión de alerta Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("wallapop_alert")

    def clear_wallapop_alert_session(self, chat_id: int) -> None:
        """Limpia sesión de alerta Wallapop."""
        lock = self._get_lock(chat_id)
        with lock:
            if "wallapop_alert" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["wallapop_alert"]

    # ========== JELLYFIN ITEM MESSAGES ==========
    def set_jellyfin_item_message(self, chat_id: int, payload: Any) -> None:
        """Establece mensaje de item Jellyfin."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["jellyfin_item"] = payload

    def get_jellyfin_item_message(self, chat_id: int) -> Optional[Any]:
        """Obtiene mensaje de item Jellyfin."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("jellyfin_item")

    def clear_jellyfin_item_message(self, chat_id: int) -> None:
        """Limpia mensaje de item Jellyfin."""
        lock = self._get_lock(chat_id)
        with lock:
            if "jellyfin_item" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["jellyfin_item"]

    # ========== PREDICTION SESSIONS ==========
    def set_prediction_session(self, chat_id: int, payload: Any) -> None:
        """Establece sesión de predicción."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["prediction"] = payload

    def get_prediction_session(self, chat_id: int) -> Optional[Any]:
        """Obtiene sesión de predicción."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("prediction")

    def clear_prediction_session(self, chat_id: int) -> None:
        """Limpia sesión de predicción."""
        lock = self._get_lock(chat_id)
        with lock:
            if "prediction" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["prediction"]

    # ========== RECIPE SESSIONS ==========
    def set_recipe_session(self, chat_id: int, payload: Any) -> None:
        """Establece sesión de receta."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["recipe"] = payload

    def get_recipe_session(self, chat_id: int) -> Optional[Any]:
        """Obtiene sesión de receta."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("recipe")

    def clear_recipe_session(self, chat_id: int) -> None:
        """Limpia sesión de receta."""
        lock = self._get_lock(chat_id)
        with lock:
            if "recipe" in self.sessions.get(chat_id, {}):
                del self.sessions[chat_id]["recipe"]

    # ========== UTILITIES ==========
    def _get_lock(self, chat_id: int) -> threading.Lock:
        """Obtiene o crea un lock para el chat_id."""
        if chat_id not in self.locks:
            with self._lock:
                if chat_id not in self.locks:
                    self.locks[chat_id] = threading.Lock()
        return self.locks[chat_id]

    def clear_base_chat_state(self, chat_id: int) -> None:
        """Limpia estado base del chat."""
        self.clear_pending_followup(chat_id)
        self.clear_playlist_session(chat_id)
        self.clear_translate_session(chat_id)

    def clear_all_chat_state(self, chat_id: int) -> None:
        """Limpia TODO el estado del chat."""
        self.clear_base_chat_state(chat_id)
        self.clear_translate_result(chat_id)
        self.clear_wallapop_session(chat_id)
        self.clear_wallapop_result_session(chat_id)
        self.clear_wallapop_item_message(chat_id)
        self.clear_wallapop_alert_session(chat_id)
        self.clear_jellyfin_item_message(chat_id)
        self.clear_prediction_session(chat_id)
        self.clear_recipe_session(chat_id)

    def set_last_message_id(self, chat_id: int, message_id: int) -> None:
        """Guarda el ID del último mensaje enviado."""
        lock = self._get_lock(chat_id)
        with lock:
            if chat_id not in self.sessions:
                self.sessions[chat_id] = {}
            self.sessions[chat_id]["last_message_id"] = message_id

    def get_last_message_id(self, chat_id: int) -> Optional[int]:
        """Obtiene el ID del último mensaje enviado."""
        lock = self._get_lock(chat_id)
        with lock:
            return self.sessions.get(chat_id, {}).get("last_message_id")


# Instancia global para compatibilidad con código existente
state_manager = ChatStateManager()

