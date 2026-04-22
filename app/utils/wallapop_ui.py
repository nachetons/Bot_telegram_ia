from datetime import datetime
from difflib import SequenceMatcher
import re
import unicodedata
from zoneinfo import ZoneInfo

from app.config import APP_TIMEZONE
from app.tools.wallapop_alerts import infer_alert_timezone


WALLAPOP_UI_PAGE_SIZE = 8
WALLAPOP_INSIGHT_MIN_SIMILARITY = 0.62
WALLAPOP_INSIGHT_MIN_COMPARABLES = 2
_wallapop_ui_timezone = ZoneInfo(APP_TIMEZONE)


def wallapop_condition_buttons():
    return [
        [
            {"text": "🆕 Nuevo", "callback_data": "wallapop_condition:new"},
            {"text": "✨ Como nuevo", "callback_data": "wallapop_condition:as_good_as_new"},
        ],
        [
            {"text": "📦 En su caja", "callback_data": "wallapop_condition:in_box"},
            {"text": "♻️ Buen estado", "callback_data": "wallapop_condition:good"},
        ],
        [
            {"text": "⏭ Sin filtrar", "callback_data": "wallapop_condition:any"},
        ],
    ]


def wallapop_radius_buttons():
    return [
        [
            {"text": "5 km", "callback_data": "wallapop_radius:5"},
            {"text": "10 km", "callback_data": "wallapop_radius:10"},
            {"text": "25 km", "callback_data": "wallapop_radius:25"},
        ],
        [
            {"text": "50 km", "callback_data": "wallapop_radius:50"},
            {"text": "100 km", "callback_data": "wallapop_radius:100"},
        ],
        [
            {"text": "⏭ Sin radio", "callback_data": "wallapop_radius:skip"},
        ],
    ]


def wallapop_order_buttons():
    return [
        [
            {"text": "⭐ Relevancia", "callback_data": "wallapop_order:most_relevance"},
            {"text": "🕒 Recientes", "callback_data": "wallapop_order:newest"},
        ],
        [
            {"text": "💸 Precio asc", "callback_data": "wallapop_order:price_low_to_high"},
            {"text": "💰 Precio desc", "callback_data": "wallapop_order:price_high_to_low"},
        ],
        [
            {"text": "📍 Cercanos", "callback_data": "wallapop_order:closest"},
            {"text": "🔥 Gangas", "callback_data": "wallapop_order:deal_score"},
        ],
    ]


def wallapop_price_skip_buttons():
    return [
        [
            {"text": "⏭ Sin precio", "callback_data": "wallapop_price:skip"},
        ],
    ]


def wallapop_location_skip_buttons():
    return [
        [
            {"text": "⏭ Sin ubicación", "callback_data": "wallapop_location:skip"},
        ],
    ]


def wallapop_alert_reuse_buttons():
    return [
        [
            {"text": "✅ Sí, reutilizarlos", "callback_data": "wallapop_alert_reuse:yes"},
        ],
        [
            {"text": "🔎 No, solo el producto", "callback_data": "wallapop_alert_reuse:no"},
        ],
    ]


def wallapop_total_loaded_pages(result_session):
    loaded_items = len(result_session.get("loaded_items", []))
    if loaded_items <= 0:
        return 1
    return (loaded_items + WALLAPOP_UI_PAGE_SIZE - 1) // WALLAPOP_UI_PAGE_SIZE


def _wallapop_results_slice(result_session):
    page_index = result_session.get("current_page", 0)
    loaded_items = result_session.get("loaded_items", [])
    start = page_index * WALLAPOP_UI_PAGE_SIZE
    end = start + WALLAPOP_UI_PAGE_SIZE
    return start, end, loaded_items[start:end]


def _wallapop_format_price(item):
    price = item.get("price")
    currency = (item.get("currency") or "EUR").upper()
    if price is None:
        return "Precio no disponible"
    symbol = "€" if currency == "EUR" else currency
    return f"{price:.0f}{symbol}"


def _wallapop_normalize_text(value):
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _wallapop_tokenize(value):
    normalized = _wallapop_normalize_text(value)
    return normalized.split() if normalized else []


def _wallapop_significant_tokens(tokens):
    return {
        token for token in tokens
        if len(token) >= 3 or any(ch.isdigit() for ch in token)
    }


def _wallapop_comparable_title_tokens(title, query_tokens):
    title_tokens = _wallapop_tokenize(title)
    significant_tokens = _wallapop_significant_tokens(title_tokens)
    generic_tokens = set(query_tokens)
    noisy_tokens = {
        "nuevo", "nueva", "nuevos", "nuevas",
        "usado", "usada", "usados", "usadas",
        "caja", "precintado", "precintada",
        "garantia", "envio",
    }
    specific_tokens = significant_tokens - generic_tokens - noisy_tokens
    numeric_tokens = {token for token in title_tokens if any(ch.isdigit() for ch in token)}
    return {
        "all": significant_tokens,
        "specific": specific_tokens,
        "numeric": numeric_tokens,
        "normalized": _wallapop_normalize_text(title),
    }


def _wallapop_price_insight(item, result_session):
    price = item.get("price")
    if price is None:
        return None

    loaded_items = result_session.get("loaded_items", [])
    query_tokens = _wallapop_tokenize(result_session.get("filters", {}).get("query", ""))
    item_title_profile = _wallapop_comparable_title_tokens(item.get("title", ""), query_tokens)

    comparable_prices = []
    for candidate in loaded_items:
        candidate_price = candidate.get("price")
        if candidate_price is None:
            continue
        if candidate.get("id") == item.get("id"):
            continue
        if candidate.get("similarity_score", 0) < WALLAPOP_INSIGHT_MIN_SIMILARITY:
            continue

        candidate_title_profile = _wallapop_comparable_title_tokens(candidate.get("title", ""), query_tokens)
        if not candidate_title_profile["all"]:
            continue

        if item_title_profile["numeric"] and not (
            item_title_profile["numeric"] & candidate_title_profile["numeric"]
        ):
            continue

        if item_title_profile["specific"]:
            if not (item_title_profile["specific"] & candidate_title_profile["specific"]):
                continue
        else:
            title_similarity = SequenceMatcher(
                None,
                item_title_profile["normalized"],
                candidate_title_profile["normalized"],
            ).ratio()
            if title_similarity < 0.58:
                continue

        comparable_prices.append(float(candidate_price))

    if len(comparable_prices) < WALLAPOP_INSIGHT_MIN_COMPARABLES:
        return None

    comparable_prices.sort()
    middle = len(comparable_prices) // 2
    if len(comparable_prices) % 2 == 0:
        median_price = (comparable_prices[middle - 1] + comparable_prices[middle]) / 2
    else:
        median_price = comparable_prices[middle]

    if median_price <= 0:
        return None

    ratio = float(price) / median_price
    if ratio <= 0.88:
        label = "🟢 Ganga"
    elif ratio >= 1.12:
        label = "🔴 Caro"
    else:
        label = "🟡 Precio razonable"

    return {
        "label": label,
        "median_price": round(median_price, 2),
        "comparable_count": len(comparable_prices),
        "ratio": round(ratio, 3),
    }


def _wallapop_deal_sort_key(item, result_session):
    insight = _wallapop_price_insight(item, result_session)
    if not insight:
        return (3, 1.0, -(item.get("similarity_score") or 0), item.get("price") or 0)

    ratio = insight.get("ratio", 1.0)
    if ratio <= 0.88:
        bucket = 0
    elif ratio <= 1.12:
        bucket = 1
    else:
        bucket = 2

    return (
        bucket,
        ratio,
        -(item.get("similarity_score") or 0),
        item.get("price") or 0,
    )


def wallapop_apply_order(result_session):
    order = result_session.get("filters", {}).get("order")
    if order != "deal_score":
        return

    items = list(result_session.get("loaded_items", []))
    if not items:
        return

    items.sort(key=lambda item: _wallapop_deal_sort_key(item, result_session))
    result_session["loaded_items"] = items


def _wallapop_format_datetime(label):
    if not label:
        return ""
    return label


def _wallapop_format_alert_datetime(value, timezone_name=None):
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return str(value)

    try:
        target_timezone = ZoneInfo(timezone_name or APP_TIMEZONE)
    except Exception:
        target_timezone = _wallapop_ui_timezone

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=target_timezone)
    else:
        parsed = parsed.astimezone(target_timezone)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _wallapop_format_age(timestamp_ms):
    try:
        published_at = datetime.fromtimestamp(float(timestamp_ms) / 1000)
    except (TypeError, ValueError, OSError):
        return ""

    delta = datetime.now() - published_at
    if delta.days > 0:
        return f"hace {delta.days} día{'s' if delta.days != 1 else ''}"

    hours = delta.seconds // 3600
    if hours > 0:
        return f"hace {hours} hora{'s' if hours != 1 else ''}"

    minutes = max(1, delta.seconds // 60)
    return f"hace {minutes} min"


def _wallapop_trim_button(text, limit=52):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _wallapop_condition_badge(condition):
    return {
        "new": "🆕",
        "as_good_as_new": "✨",
        "in_box": "📦",
        "good": "♻️",
        "used": "♻️",
    }.get(condition or "")


def _wallapop_listing_badges(item, result_session):
    badges = []
    filters = result_session.get("filters", {})

    if item.get("reserved"):
        badges.append("⛔")

    price_insight = _wallapop_price_insight(item, result_session)
    if price_insight:
        label = price_insight.get("label", "")
        if label.startswith("🟢"):
            badges.append("🟢")
        elif label.startswith("🟡"):
            badges.append("🟡")
        elif label.startswith("🔴"):
            badges.append("🔴")

    if filters.get("condition") == "any":
        condition_badge = _wallapop_condition_badge(item.get("condition"))
        if condition_badge:
            badges.append(condition_badge)
    else:
        badges.append("🚚" if item.get("shipping") else "🚫")

    return "".join(badges)


def _wallapop_listing_button_text(index, item, result_session):
    title = (item.get("title") or "Producto").strip()
    location = (item.get("location") or "").strip()
    shipping = item.get("shipping")
    badges = _wallapop_listing_badges(item, result_session)
    price = _wallapop_format_price(item)

    head_parts = [f"{index}.", price]
    if badges:
        head_parts.append(badges)

    tail_parts = [title]
    if location and not shipping:
        tail_parts.append(location)

    body = " ".join(head_parts)
    tail = " · ".join(tail_parts)
    return _wallapop_trim_button(f"{body} · {tail}", limit=58)


def wallapop_results_menu(result_session):
    filters = result_session.get("filters", {})
    search_url = result_session.get("search_url")
    current_page = result_session.get("current_page", 0)
    loaded_pages = wallapop_total_loaded_pages(result_session)
    start, _, items = _wallapop_results_slice(result_session)

    text_lines = [f"🛒 Wallapop: {filters.get('query', '')}"]
    if result_session.get("summary"):
        text_lines.append(f"Filtros: {result_session['summary']}")
    text_lines.append("")
    text_lines.append("Selecciona un artículo para ver la ficha completa.")
    text_lines.append("")
    total_label = f"{loaded_pages}+" if result_session.get("next_page_token") else str(loaded_pages)
    text_lines.append(f"Página {current_page + 1} de {total_label}")

    buttons = []
    for index, item in enumerate(items, start=start + 1):
        buttons.append([
            {
                "text": _wallapop_listing_button_text(index, item, result_session),
                "callback_data": f"wallapop_item:{index - 1}",
            }
        ])

    nav_buttons = []
    if current_page > 0:
        nav_buttons.append({"text": "⬅️ Anterior", "callback_data": "wallapop_page:prev"})

    loaded_items = result_session.get("loaded_items", [])
    if (current_page + 1) * WALLAPOP_UI_PAGE_SIZE < len(loaded_items) or result_session.get("next_page_token"):
        nav_buttons.append({"text": "Siguiente ➡️", "callback_data": "wallapop_page:next"})

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([{"text": "🔔 Crear alerta", "callback_data": "wallapop_alert_create"}])
    buttons.append([{"text": "🔎 Buscar otro producto", "callback_data": "wallapop_new_search"}])

    if search_url:
        buttons.append([{"text": "🔗 Abrir búsqueda en Wallapop", "url": search_url}])

    return {
        "type": "menu",
        "text": "\n".join(text_lines),
        "buttons": buttons,
    }


def wallapop_alerts_menu(alert, status_message=None):
    if not alert:
        return {
            "type": "text",
            "text": "No tienes alertas activas de Wallapop.",
        }

    filters = alert.get("filters", {})
    lines = [
        "🔔 Tu alerta de Wallapop",
        f"Producto: {alert.get('query', '')}",
        f"Precio máximo: {int(alert.get('max_price', 0))}€",
        "Modo: Reutilizando filtros" if alert.get("reuse_filters") else "Modo: Solo producto",
    ]
    timezone_name = alert.get("timezone") or infer_alert_timezone(filters)
    lines.append(f"Zona horaria: {timezone_name}")

    if alert.get("reuse_filters"):
        if filters.get("condition") and filters.get("condition") != "any":
            labels = {
                "new": "🆕 Nuevo",
                "as_good_as_new": "✨ Como nuevo",
                "in_box": "📦 En su caja",
                "good": "♻️ Buen estado",
                "used": "♻️ Usado",
            }
            lines.append(f"Estado: {labels.get(filters['condition'], filters['condition'])}")
        if filters.get("location_label"):
            radius = filters.get("distance_km")
            location_text = filters["location_label"]
            if radius:
                location_text += f" ({radius} km)"
            lines.append(f"Zona: {location_text}")

    next_check_at = alert.get("next_check_at")
    if next_check_at:
        lines.append(f"Próxima revisión: {_wallapop_format_alert_datetime(next_check_at, timezone_name)}")

    last_check_at = alert.get("last_check_at")
    if last_check_at:
        lines.append(f"Última revisión: {_wallapop_format_alert_datetime(last_check_at, timezone_name)}")

    if status_message:
        lines.append("")
        lines.append(status_message)

    buttons = [
        #[{"text": "🧪 Probar ahora", "callback_data": "wallapop_alert_test"}],
        [{"text": "🗑 Borrar alerta", "callback_data": "wallapop_alert_delete"}],
    ]

    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
    }


def wallapop_item_caption(item, result_session=None):
    lines = [
        f"🛒 {item.get('title', 'Artículo')}",
        f"💸 {_wallapop_format_price(item)}",
    ]

    if item.get("reserved"):
        lines.append("⛔ RESERVADO")

    location_parts = [part for part in [item.get("location"), item.get("region")] if part]
    if location_parts:
        lines.append(f"📍 {', '.join(location_parts)}")

    if item.get("condition"):
        condition_labels = {
            "new": "🆕 Nuevo",
            "as_good_as_new": "✨ Como nuevo",
            "in_box": "📦 En su caja",
            "good": "♻️ Buen estado",
            "used": "♻️ Usado",
        }
        lines.append(condition_labels.get(item["condition"], str(item["condition"])))

    created_label = _wallapop_format_datetime(item.get("created_label"))
    age_label = _wallapop_format_age(item.get("created_at"))
    if created_label:
        suffix = f" ({age_label})" if age_label else ""
        lines.append(f"🕒 Publicado: {created_label}{suffix}")

    modified_label = _wallapop_format_datetime(item.get("modified_label"))
    if modified_label:
        lines.append(f"✏️ Última edición: {modified_label}")

    if result_session:
        price_insight = _wallapop_price_insight(item, result_session)
        if price_insight:
            lines.append(
                f"📊 {price_insight['label']} frente a {price_insight['comparable_count']} comparables"
            )
            lines.append(f"Referencia media: {price_insight['median_price']:.0f}€")

    extra_flags = []
    if item.get("shipping"):
        extra_flags.append("Envío")
    if item.get("has_warranty"):
        extra_flags.append("Garantía")
    if item.get("is_refurbished"):
        extra_flags.append("Reacondicionado")
    if item.get("is_top_profile"):
        extra_flags.append("Top profile")
    if item.get("views") is not None:
        extra_flags.append(f"{item['views']} visualizaciones")

    if extra_flags:
        lines.append("• " + " | ".join(extra_flags))

    description = (item.get("description") or "").strip()
    if description:
        shortened = description[:500].rstrip()
        if len(description) > 500:
            shortened += "…"
        lines.append("")
        lines.append(shortened)

    return "\n".join(lines)[:1024]


def wallapop_build_result_session(filters, search_result):
    result_session = {
        "filters": dict(filters),
        "loaded_items": list(search_result.get("items", [])),
        "next_page_token": search_result.get("next_page"),
        "current_page": 0,
        "summary": search_result.get("summary", ""),
        "search_url": search_result.get("search_url"),
    }
    wallapop_apply_order(result_session)
    return result_session
