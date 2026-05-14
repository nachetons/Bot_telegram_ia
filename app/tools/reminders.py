"""Sistema persistente de recordatorios para el bot de Telegram."""

import json
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import APP_TIMEZONE

_reminders_lock = threading.Lock()
_reminders_path = Path("data") / "reminders.json"
_timezone = ZoneInfo(APP_TIMEZONE)


def _ensure_store():
    """Crear el archivo de recordatorios si no existe."""
    _reminders_path.parent.mkdir(parents=True, exist_ok=True)
    if not _reminders_path.exists():
        _reminders_path.write_text("[]", encoding="utf-8")


def _load_reminders():
    """Cargar recordatorios desde JSON."""
    _ensure_store()
    try:
        data = json.loads(_reminders_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_reminders(data):
    """Guardar recordatorios de forma atomica."""
    _ensure_store()
    tmp = _reminders_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_reminders_path)


def _now():
    """Fecha y hora actual en la zona horaria configurada."""
    return datetime.now(_timezone)


def _parse_target_date(value: str):
    """Aceptar fechas comunes en español y devolver date."""
    raw = (value or "").strip().lower()
    today = _now().date()

    if not raw:
        return None

    if raw in {"mañana", "manana"}:
        return today + timedelta(days=1)

    match = re.fullmatch(r"en\s+(\d{1,3})\s+d[ií]as?", raw)
    if match:
        return today + timedelta(days=int(match.group(1)))

    formats = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def add_reminder(chat_id: int, task: str, target_date_str: str) -> dict:
    """Crear un recordatorio."""
    task = (task or "").strip()
    if not task:
        return {
            "ok": False,
            "error": "tarea_vacia",
            "message": "Necesito una descripcion para crear el recordatorio.",
        }

    target_date = _parse_target_date(target_date_str)
    if not target_date:
        return {
            "ok": False,
            "error": "formato_fecha",
            "message": "Formato de fecha no valido. Usa 2026-06-15, 15/06/2026, mañana o en 3 dias.",
        }

    today = _now().date()
    if target_date <= today:
        return {
            "ok": False,
            "error": "fecha_pasada",
            "message": f"La fecha debe ser futura. Hoy es {today.isoformat()}.",
        }

    target_iso = target_date.isoformat()
    notify_date = (target_date - timedelta(days=1)).isoformat()
    reminder_id = f"rem_{uuid.uuid4().hex[:12]}"

    with _reminders_lock:
        reminders = _load_reminders()
        reminder = {
            "id": reminder_id,
            "chat_id": chat_id,
            "task": task,
            "target_date": target_iso,
            "notify_date": notify_date,
            "notified": False,
            "completed": False,
            "created_at": _now().isoformat(),
        }
        reminders.append(reminder)
        _save_reminders(reminders)

    return {
        "ok": True,
        "id": reminder_id,
        "task": task,
        "target_date": target_iso,
        "notify_date": notify_date,
        "message": "Recordatorio creado correctamente.",
    }


def list_reminders(chat_id: int = None) -> list:
    """Listar recordatorios, opcionalmente filtrados por chat."""
    with _reminders_lock:
        reminders = _load_reminders()

    if chat_id is not None:
        reminders = [r for r in reminders if r.get("chat_id") == chat_id]

    reminders.sort(
        key=lambda r: (
            bool(r.get("completed")),
            r.get("target_date", ""),
            r.get("created_at", ""),
        )
    )
    return reminders


def delete_reminder(chat_id: int, reminder_id: str) -> dict:
    """Eliminar un recordatorio concreto."""
    with _reminders_lock:
        reminders = _load_reminders()
        before = len(reminders)
        reminders = [
            r
            for r in reminders
            if not (r.get("id") == reminder_id and r.get("chat_id") == chat_id)
        ]

        if len(reminders) == before:
            return {"ok": False, "error": "not_found", "message": "No he encontrado ese recordatorio."}

        _save_reminders(reminders)

    return {"ok": True, "message": "Recordatorio eliminado."}


def complete_reminder(chat_id: int, reminder_id: str) -> dict:
    """Marcar un recordatorio como completado."""
    found = False
    with _reminders_lock:
        reminders = _load_reminders()
        for reminder in reminders:
            if reminder.get("id") == reminder_id and reminder.get("chat_id") == chat_id:
                reminder["completed"] = True
                reminder["completed_at"] = _now().isoformat()
                found = True
                break

        if found:
            _save_reminders(reminders)

    if not found:
        return {"ok": False, "error": "not_found", "message": "No he encontrado ese recordatorio."}
    return {"ok": True, "message": "Recordatorio marcado como completado."}


def check_daily_reminders():
    """Buscar recordatorios que deben notificarse hoy."""
    today = _now().date()
    tomorrow = today + timedelta(days=1)

    with _reminders_lock:
        reminders = _load_reminders()

    notifications = []
    for reminder in reminders:
        if reminder.get("notified") or reminder.get("completed"):
            continue

        try:
            target = datetime.strptime(reminder["target_date"], "%Y-%m-%d").date()
        except (ValueError, KeyError, TypeError):
            continue

        notification = None
        if target == tomorrow:
            notification = {
                "chat_id": reminder["chat_id"],
                "reminder_id": reminder["id"],
                "task": reminder["task"],
                "target_date": reminder["target_date"],
            }
        elif target == today:
            notification = {
                "chat_id": reminder["chat_id"],
                "reminder_id": reminder["id"],
                "task": reminder["task"],
                "target_date": reminder["target_date"],
                "due_today": True,
            }
        elif target < today:
            notification = {
                "chat_id": reminder["chat_id"],
                "reminder_id": reminder["id"],
                "task": reminder["task"],
                "target_date": reminder["target_date"],
                "overdue": True,
            }

        if notification:
            notifications.append(notification)

    return notifications


def mark_reminder_notified(chat_id: int, reminder_id: str) -> bool:
    """Marcar un recordatorio como notificado tras enviar el mensaje."""
    with _reminders_lock:
        reminders = _load_reminders()
        for reminder in reminders:
            if reminder.get("id") == reminder_id and reminder.get("chat_id") == chat_id:
                reminder["notified"] = True
                reminder["notified_at"] = _now().isoformat()
                _save_reminders(reminders)
                return True
    return False


def cleanup_old_reminders(days=30):
    """Eliminar recordatorios antiguos completados para mantener el JSON pequeño."""
    cutoff = _now().date() - timedelta(days=days)
    with _reminders_lock:
        reminders = _load_reminders()
        before = len(reminders)
        kept = []
        for reminder in reminders:
            try:
                target = datetime.strptime(reminder["target_date"], "%Y-%m-%d").date()
            except (ValueError, KeyError, TypeError):
                kept.append(reminder)
                continue

            if not reminder.get("completed") or target >= cutoff:
                kept.append(reminder)

        _save_reminders(kept)

    return {"removed": before - len(kept), "remaining": len(kept)}
