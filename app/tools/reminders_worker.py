"""Comprobador diario de recordatorios."""

import logging

from app.services.telegram_client import send_message
from app.tools.reminders import check_daily_reminders, mark_reminder_notified
from app.utils.reminder_ui import build_notification_text

logger = logging.getLogger("reminders_worker")


def run_daily_check():
    """Enviar las notificaciones de recordatorios pendientes."""
    logger.info("Ejecutando comprobacion diaria de recordatorios...")

    notifications = check_daily_reminders()
    if not notifications:
        logger.info("No hay recordatorios para notificar hoy.")
        return {"ok": True, "notified_count": 0, "message": "No hay recordatorios para notificar hoy."}

    notified_count = 0
    errors = []

    for notification in notifications:
        chat_id = notification["chat_id"]
        task = notification["task"]
        target_date = notification["target_date"]
        overdue = notification.get("overdue", False)
        due_today = notification.get("due_today", False)

        message_text = build_notification_text(
            task,
            target_date,
            overdue=overdue,
            due_today=due_today,
        )

        try:
            send_message(chat_id, message_text)
            mark_reminder_notified(chat_id, notification["reminder_id"])
            notified_count += 1
            logger.info("Recordatorio enviado a chat %s: %s (%s)", chat_id, task, target_date)
        except Exception as exc:
            errors.append({"chat_id": chat_id, "error": str(exc)})
            logger.warning("No se pudo notificar al chat %s: %s", chat_id, exc)

    result = {
        "ok": len(errors) == 0,
        "notified_count": notified_count,
        "total_found": len(notifications),
        "errors": errors,
    }

    if errors:
        logger.warning("%s notificacion(es) fallaron.", len(errors))

    return result


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_daily_check()
    print(f"Comprobacion de recordatorios finalizada: {result}")
    sys.exit(0 if result.get("ok") else 1)
