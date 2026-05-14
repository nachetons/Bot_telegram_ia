"""Helpers de UI para el sistema de recordatorios."""

from datetime import date, datetime, timedelta


WEEKDAYS_ES = {
    0: "lun",
    1: "mar",
    2: "mie",
    3: "jue",
    4: "vie",
    5: "sab",
    6: "dom",
}


def _format_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return value or "sin fecha"
    return f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year}"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def reminder_main_menu():
    """Menu principal de /recordatorios."""
    return {
        "type": "menu",
        "text": (
            "*Recordatorios*\n\n"
            "Crea avisos personales y el bot te avisará el día anterior. "
            "También verás avisos pendientes de hoy si alguno se quedó sin notificar.\n\n"
            "¿Qué quieres hacer?"
        ),
        "buttons": [
            [{"text": "Nuevo recordatorio", "callback_data": "reminder:create"}],
            [{"text": "Mis recordatorios", "callback_data": "reminder:list"}],
            [{"text": "Eliminar recordatorio", "callback_data": "reminder:delete_menu"}],
        ],
    }


def reminder_create_step1():
    """Paso 1: pedir la descripcion del recordatorio."""
    return {
        "type": "menu",
        "text": (
            "*Nuevo recordatorio*\n\n"
            "Escribe qué quieres recordar.\n\n"
            "Ejemplos:\n"
            "- Pagar el alquiler\n"
            "- Cita del médico\n"
            "- Cumpleaños de Ana"
        ),
        "buttons": [
            [{"text": "Volver", "callback_data": "reminder:back"}],
        ],
    }


def reminder_create_step2(task):
    """Paso 2: mostrar selector rapido de fecha."""
    today = date.today()

    rows = []
    quick_dates = [
        ("Mañana", today + timedelta(days=1)),
        ("En 2 días", today + timedelta(days=2)),
        ("En 3 días", today + timedelta(days=3)),
        ("En 1 semana", today + timedelta(days=7)),
        ("En 2 semanas", today + timedelta(days=14)),
        ("En 1 mes", today + timedelta(days=30)),
    ]

    for prefix, target in quick_dates:
        weekday = WEEKDAYS_ES[target.weekday()]
        label = f"{prefix}: {target.day:02d}/{target.month:02d} ({weekday})"
        rows.append([{"text": label, "callback_data": f"reminder:date:{target.isoformat()}"}])

    rows.append([{"text": "Otra fecha", "callback_data": "reminder:date_manual"}])
    rows.append([{"text": "Volver", "callback_data": "reminder:back"}])

    return {
        "type": "menu",
        "text": (
            "*Nuevo recordatorio*\n\n"
            f"Tarea: {_truncate(task, 120)}\n\n"
            "Ahora elige la fecha del evento. Te avisaré el día anterior."
        ),
        "buttons": rows,
        "_edit": True,
    }


def reminder_create_manual_date():
    """Pedir fecha manual."""
    return {
        "type": "menu",
        "text": (
            "*Fecha personalizada*\n\n"
            "Escribe la fecha del evento.\n\n"
            "Formatos válidos:\n"
            "- 2026-06-15\n"
            "- 15/06/2026\n"
            "- mañana\n"
            "- en 3 días"
        ),
        "buttons": [
            [{"text": "Cancelar", "callback_data": "reminder:back"}],
        ],
    }


def reminder_created_menu(result: dict):
    """Confirmacion tras crear un recordatorio."""
    task = result.get("task") or result.get("message") or "Recordatorio"
    target_date = _format_date(result.get("target_date", ""))
    notify_date = _format_date(result.get("notify_date", ""))

    return {
        "type": "menu",
        "text": (
            "*Recordatorio creado*\n\n"
            f"{_truncate(task, 300)}\n\n"
            f"Fecha del evento: {target_date}\n"
            f"Te avisaré: {notify_date}"
        ),
        "buttons": [
            [{"text": "Crear otro", "callback_data": "reminder:create"}],
            [{"text": "Ver mis recordatorios", "callback_data": "reminder:list"}],
            [{"text": "Volver", "callback_data": "reminder:back"}],
        ],
        "_edit": True,
    }


def reminder_list_menu(reminders):
    """Listar recordatorios del chat actual."""
    if not reminders:
        return {
            "type": "menu",
            "text": "*Mis recordatorios*\n\nNo tienes recordatorios guardados.",
            "buttons": [
                [{"text": "Crear uno nuevo", "callback_data": "reminder:create"}],
                [{"text": "Volver", "callback_data": "reminder:back"}],
            ],
            "_edit": True,
        }

    lines = ["*Mis recordatorios*", ""]
    buttons = []

    for idx, reminder in enumerate(reminders, start=1):
        if reminder.get("completed"):
            status = "Completado"
        elif reminder.get("notified"):
            status = "Avisado"
        else:
            status = "Pendiente"

        task = _truncate(reminder.get("task", "Sin descripcion"), 55)
        date_str = _format_date(reminder.get("target_date", ""))
        lines.append(f"{idx}. [{status}] {task} - {date_str}")

        if not reminder.get("completed"):
            buttons.append([{"text": f"Marcar completado {idx}", "callback_data": f"reminder:complete:{reminder['id']}"}])

    buttons.append([{"text": "Eliminar recordatorio", "callback_data": "reminder:delete_menu"}])
    buttons.append([{"text": "Volver", "callback_data": "reminder:back"}])

    return {"type": "menu", "text": "\n".join(lines), "buttons": buttons, "_edit": True}


def reminder_delete_menu(reminders):
    """Menu para elegir un recordatorio y eliminarlo."""
    if not reminders:
        return {
            "type": "menu",
            "text": "*Eliminar recordatorio*\n\nNo tienes recordatorios pendientes para eliminar.",
            "buttons": [
                [{"text": "Volver", "callback_data": "reminder:back"}],
            ],
            "_edit": True,
        }

    buttons = []
    for idx, reminder in enumerate(reminders, start=1):
        task = _truncate(reminder.get("task", "Sin descripcion"), 32)
        date_str = _format_date(reminder.get("target_date", ""))
        buttons.append([{"text": f"{idx}. {task} ({date_str})", "callback_data": f"reminder:delete:{reminder['id']}"}])

    buttons.append([{"text": "Volver", "callback_data": "reminder:back"}])

    return {
        "type": "menu",
        "text": "*Eliminar recordatorio*\n\nSelecciona el recordatorio que quieres borrar:",
        "buttons": buttons,
        "_edit": True,
    }


def reminder_action_result_menu(message: str, *, list_after: bool = True):
    """Respuesta corta para acciones como completar o borrar."""
    buttons = []
    if list_after:
        buttons.append([{"text": "Ver mis recordatorios", "callback_data": "reminder:list"}])
    buttons.append([{"text": "Volver", "callback_data": "reminder:back"}])

    return {
        "type": "menu",
        "text": message,
        "buttons": buttons,
        "_edit": True,
    }


def build_notification_text(task, target_date, overdue=False, due_today=False):
    """Construir el mensaje de aviso del recordatorio."""
    formatted_date = _format_date(target_date)
    task = _truncate(task, 500)

    if overdue:
        return (
            "*Recordatorio pendiente*\n\n"
            f"{task}\n\n"
            f"La fecha era: {formatted_date}\n"
            "Puedes marcarlo como completado desde /recordatorios."
        )

    if due_today:
        return (
            "*Recordatorio para hoy*\n\n"
            f"{task}\n\n"
            f"Fecha: {formatted_date}\n"
            "Puedes marcarlo como completado desde /recordatorios."
        )

    return (
        "*Recordatorio para mañana*\n\n"
        f"{task}\n\n"
        f"Fecha del evento: {formatted_date}"
    )
