import logging
import threading
import time

from app.config import WALLAPOP_ALERT_BATCH_SIZE
from app.services.telegram_client import send_message, send_message_with_buttons
from app.tools.wallapop import search_wallapop
from app.tools.wallapop_alerts import (
    _now,
    get_alert_for_chat,
    get_due_alerts,
    update_alert_runtime,
    _next_check_time,
)


logger = logging.getLogger("wallapop_alert_worker")

_worker_thread = None
_worker_lock = threading.Lock()
_stop_event = threading.Event()


def _build_alert_notification(alert, new_items):
    query = alert.get("query", "")
    lines = [f"🔔 Nuevos resultados para tu alerta: {query}"]

    buttons = []
    for index, item in enumerate(new_items[:3], start=1):
        price = item.get("price")
        price_text = f"{int(price)}€" if price is not None else "Sin precio"
        location = item.get("location") or "Sin ubicación"
        lines.append(f"{index}. {item.get('title', 'Producto')} - {price_text} - {location}")
        if item.get("url"):
            buttons.append([{"text": f"🔗 {index}. Abrir anuncio", "url": item["url"]}])

    return "\n".join(lines), buttons


def _check_alert_once(alert, *, notify=True):
    chat_id = alert.get("chat_id")
    filters = dict(alert.get("filters") or {})
    if not chat_id or not filters.get("query"):
        return {
            "ok": False,
            "error": "missing_query",
            "new_items": [],
            "current_count": 0,
        }

    now = _now()
    result = search_wallapop(filters)

    if not isinstance(result, dict) or result.get("type") != "wallapop":
        update_alert_runtime(
            chat_id,
            last_check_at=now,
            next_check_at=_next_check_time(now),
        )
        return {
            "ok": False,
            "error": "invalid_result",
            "new_items": [],
            "current_count": 0,
        }

    items = result.get("items") or []
    seen_ids = {str(item_id) for item_id in (alert.get("last_seen_ids") or [])}
    current_ids = []
    new_items = []

    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        item_id = str(item_id)
        current_ids.append(item_id)
        if item_id not in seen_ids:
            new_items.append(item)

    if new_items and notify:
        message_text, buttons = _build_alert_notification(alert, new_items)
        if buttons:
            send_message_with_buttons(chat_id, message_text, buttons)
        else:
            send_message(chat_id, message_text)

    merged_seen_ids = list(dict.fromkeys(current_ids + list(alert.get("last_seen_ids") or [])))
    update_alert_runtime(
        chat_id,
        last_seen_ids=merged_seen_ids,
        last_check_at=now,
        next_check_at=_next_check_time(now),
    )
    return {
        "ok": True,
        "new_items": new_items,
        "new_count": len(new_items),
        "current_count": len(items),
    }


def _process_alert(alert):
    _check_alert_once(alert, notify=True)


def run_wallapop_alert_test(chat_id):
    alert = get_alert_for_chat(chat_id)
    if not alert:
        return {
            "ok": False,
            "error": "missing_alert",
            "message": "No tienes ninguna alerta activa.",
            "new_items": [],
            "current_count": 0,
        }
    return _check_alert_once(alert, notify=True)


def _worker_loop():
    logger.info("Wallapop alert worker started")
    while not _stop_event.is_set():
        try:
            due_alerts = get_due_alerts(limit=WALLAPOP_ALERT_BATCH_SIZE)
            if not due_alerts:
                _stop_event.wait(60)
                continue

            for alert in due_alerts:
                if _stop_event.is_set():
                    break
                try:
                    _process_alert(alert)
                except Exception as exc:
                    logger.warning("Wallapop alert processing failed for %s: %s", alert.get("chat_id"), exc)
                    update_alert_runtime(
                        alert.get("chat_id"),
                        last_check_at=_now(),
                        next_check_at=_next_check_time(_now()),
                    )
                time.sleep(5)
        except Exception as exc:
            logger.warning("Wallapop alert worker loop error: %s", exc)
            _stop_event.wait(120)


def start_wallapop_alert_worker():
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _stop_event.clear()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="wallapop-alert-worker",
            daemon=True,
        )
        _worker_thread.start()


def stop_wallapop_alert_worker():
    _stop_event.set()
