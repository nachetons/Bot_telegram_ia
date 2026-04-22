import json
import threading
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import (
    APP_TIMEZONE,
    WALLAPOP_ALERT_INTERVAL_HOURS,
    WALLAPOP_ALERT_INTERVAL_MINUTES,
    WALLAPOP_ALERT_JITTER_MINUTES,
)

_alerts_lock = threading.Lock()
_alerts_path = Path("data") / "wallapop_alerts.json"
_alert_timezone = ZoneInfo(APP_TIMEZONE)


def _ensure_store():
    _alerts_path.parent.mkdir(parents=True, exist_ok=True)
    if not _alerts_path.exists():
        _alerts_path.write_text("[]", encoding="utf-8")


def _load_alerts():
    _ensure_store()
    try:
        return json.loads(_alerts_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_alerts(alerts):
    _ensure_store()
    _alerts_path.write_text(
        json.dumps(alerts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _now():
    return datetime.now(_alert_timezone)


def _serialize_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _next_check_time(reference=None):
    base = reference or _now()
    extra_minutes = random.randint(0, max(0, WALLAPOP_ALERT_JITTER_MINUTES))
    interval_minutes = WALLAPOP_ALERT_INTERVAL_MINUTES or (WALLAPOP_ALERT_INTERVAL_HOURS * 60)
    return base + timedelta(minutes=interval_minutes + extra_minutes)


def _infer_timezone_from_coordinates(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    # Best-effort inference without external services. Telegram does not expose
    # the device timezone directly, so we infer from shared coordinates when possible.
    if 27.0 <= latitude <= 29.8 and -18.5 <= longitude <= -13.0:
        return "Atlantic/Canary"

    if 35.0 <= latitude <= 44.5 and -10.5 <= longitude <= 4.5:
        return "Europe/Madrid"

    return None


def infer_alert_timezone(filters=None):
    filters = filters or {}

    inferred = _infer_timezone_from_coordinates(
        filters.get("latitude"),
        filters.get("longitude"),
    )
    if inferred:
        return inferred

    location_label = str(filters.get("location_label") or "").lower()
    if location_label:
        if any(token in location_label for token in {"canarias", "tenerife", "gran canaria", "lanzarote", "fuerteventura", "la palma", "la gomera", "el hierro"}):
            return "Atlantic/Canary"
        if any(token in location_label for token in {"españa", "espana", "madrid", "barcelona", "sevilla", "valencia", "bilbao", "zaragoza", "murcia", "andalucía", "andalucia", "galicia", "asturias", "castilla", "baleares"}):
            return "Europe/Madrid"

    return APP_TIMEZONE


def _build_alert_filters(base_filters, reuse_filters, max_price):
    base_filters = dict(base_filters or {})
    filters = {
        "query": base_filters.get("query", ""),
        "condition": base_filters.get("condition", "any") if reuse_filters else "any",
        "min_price": base_filters.get("min_price") if reuse_filters else None,
        "max_price": max_price,
        "location_label": base_filters.get("location_label", "") if reuse_filters else "",
        "distance_km": base_filters.get("distance_km") if reuse_filters else None,
        "latitude": base_filters.get("latitude") if reuse_filters else None,
        "longitude": base_filters.get("longitude") if reuse_filters else None,
        "category_id": base_filters.get("category_id"),
        "order": "newest",
    }
    return filters


def get_alert_for_chat(chat_id):
    with _alerts_lock:
        alerts = _load_alerts()
        for alert in alerts:
            if str(alert.get("chat_id")) == str(chat_id):
                return alert
    return None


def create_or_replace_alert(chat_id, base_filters, reuse_filters, max_price, seen_items=None):
    max_price_value = float(max_price)
    filters = _build_alert_filters(base_filters, reuse_filters, max_price_value)
    query = (filters.get("query") or "").strip()
    if not query:
        return {"error": "No tengo una búsqueda válida para crear la alerta."}

    seen_ids = []
    for item in seen_items or []:
        item_id = item.get("id")
        if item_id:
            seen_ids.append(str(item_id))

    created_at = _now().isoformat(timespec="seconds")
    alert_payload = {
        "id": f"wallapop-{chat_id}",
        "chat_id": str(chat_id),
        "query": query,
        "reuse_filters": bool(reuse_filters),
        "max_price": max_price_value,
        "filters": filters,
        "timezone": infer_alert_timezone(filters),
        "last_seen_ids": seen_ids[:200],
        "status": "active",
        "created_at": created_at,
        "last_check_at": None,
        "next_check_at": _serialize_dt(_next_check_time()),
    }

    with _alerts_lock:
        alerts = _load_alerts()
        alerts = [alert for alert in alerts if str(alert.get("chat_id")) != str(chat_id)]
        alerts.append(alert_payload)
        _save_alerts(alerts)

    return alert_payload


def delete_alert(chat_id):
    removed = False
    with _alerts_lock:
        alerts = _load_alerts()
        updated = []
        for alert in alerts:
            if str(alert.get("chat_id")) == str(chat_id):
                removed = True
                continue
            updated.append(alert)
        if removed:
            _save_alerts(updated)
    return removed


def list_alerts():
    with _alerts_lock:
        return _load_alerts()


def update_alert_runtime(chat_id, *, last_seen_ids=None, last_check_at=None, next_check_at=None, status=None):
    updated_alert = None
    with _alerts_lock:
        alerts = _load_alerts()
        for alert in alerts:
            if str(alert.get("chat_id")) != str(chat_id):
                continue
            if last_seen_ids is not None:
                alert["last_seen_ids"] = [str(item_id) for item_id in last_seen_ids][:200]
            if last_check_at is not None:
                alert["last_check_at"] = _serialize_dt(last_check_at)
            if next_check_at is not None:
                alert["next_check_at"] = _serialize_dt(next_check_at)
            if status is not None:
                alert["status"] = status
            updated_alert = dict(alert)
            break
        if updated_alert is not None:
            _save_alerts(alerts)
    return updated_alert


def get_due_alerts(limit=None, now=None):
    now = now or _now()
    due_alerts = []
    with _alerts_lock:
        alerts = _load_alerts()
        for alert in alerts:
            if alert.get("status") != "active":
                continue
            next_check_at = _parse_dt(alert.get("next_check_at"))
            if next_check_at is None or next_check_at <= now:
                due_alerts.append(dict(alert))
    due_alerts.sort(key=lambda alert: _parse_dt(alert.get("next_check_at")) or datetime.min)
    if limit is not None:
        return due_alerts[:limit]
    return due_alerts
