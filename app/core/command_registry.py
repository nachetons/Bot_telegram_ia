"""Command registry pattern for slash commands."""

import threading
from typing import Callable, Dict, Optional, Tuple


class CommandHandler:
    """Handler para un comando específico."""

    def __init__(self, name: str, handler: Callable):
        self.name = name
        self.handler = handler


class CommandRegistry:
    """Registro centralizado de comandos slash (/)."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._commands: Dict[str, CommandHandler] = {}
        return cls._instance

    def __init__(self):
        """Inicializa el registry solo la primera vez."""
        if not hasattr(self, "_initialized"):
            self._commands = {}
            self._initialized = True

    def register(self, name: str, handler: Callable):
        """Registra un nuevo comando."""
        self._commands[name] = CommandHandler(name, handler)

    def get_handler(self, command_name: str) -> Optional[Callable]:
        """Obtiene el handler para un comando."""
        return self._commands.get(command_name)

    def has_command(self, command_name: str) -> bool:
        """Verifica si existe un comando."""
        return command_name in self._commands

    def list_commands(self) -> Dict[str, CommandHandler]:
        """Lista todos los comandos registrados."""
        return self._commands.copy()


# Instancia global
command_registry = CommandRegistry()
