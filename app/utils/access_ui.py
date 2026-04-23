from datetime import datetime


CONTROL_PAGE_SIZE = 8


def _status_icon(status):
    return {
        "approved": "🟢",
        "pending": "🟡",
        "blocked": "🔴",
        "unknown": "⚪",
    }.get(status or "unknown", "⚪")


def _status_label(status):
    return {
        "approved": "Aprobado",
        "pending": "Pendiente",
        "blocked": "Bloqueado",
        "unknown": "Desconocido",
    }.get(status or "unknown", "Desconocido")


def _trim(text, limit=42):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _display_name(user):
    first_name = (user.get("first_name") or "").strip()
    username = (user.get("username") or "").strip()
    if first_name and username:
        return f"{first_name} (@{username})"
    if first_name:
        return first_name
    if username:
        return f"@{username}"
    return str(user.get("user_id"))


def _format_dt(value):
    if not value:
        return "N/D"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)


def build_control_menu(users, current_filter="all", page=0, all_users=None):
    all_users = all_users or users
    counts = {
        "all": len(all_users),
        "pending": len([item for item in all_users if item.get("status") == "pending"]),
        "approved": len([item for item in all_users if item.get("status") == "approved"]),
        "blocked": len([item for item in all_users if item.get("status") == "blocked"]),
    }

    start = page * CONTROL_PAGE_SIZE
    end = start + CONTROL_PAGE_SIZE
    current_page_items = users[start:end]
    total_pages = max(1, (len(users) + CONTROL_PAGE_SIZE - 1) // CONTROL_PAGE_SIZE)

    lines = [
        "🛠 Centro de control",
        "",
        f"Filtro: {current_filter}",
        f"Usuarios mostrados: {len(users)}",
        f"Página {page + 1} de {total_pages}",
    ]

    buttons = [
        [
            {"text": f"Todos ({counts['all']})", "callback_data": "control_list:all:0"},
            {"text": f"Pendientes ({counts['pending']})", "callback_data": "control_list:pending:0"},
        ],
        [
            {"text": f"Aprobados ({counts['approved']})", "callback_data": "control_list:approved:0"},
            {"text": f"Bloqueados ({counts['blocked']})", "callback_data": "control_list:blocked:0"},
        ],
    ]

    for user in current_page_items:
        buttons.append([
            {
                "text": _trim(f"{_status_icon(user.get('status'))} {_display_name(user)}"),
                "callback_data": f"control_user:{user.get('user_id')}:{current_filter}:{page}",
            }
        ])

    nav = []
    if page > 0:
        nav.append({"text": "⬅️ Anterior", "callback_data": f"control_list:{current_filter}:{page - 1}"})
    if end < len(users):
        nav.append({"text": "Siguiente ➡️", "callback_data": f"control_list:{current_filter}:{page + 1}"})
    if nav:
        buttons.append(nav)

    if not current_page_items:
        lines.append("No hay usuarios en este filtro.")

    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
    }


def build_user_actions_menu(user, current_filter="all", page=0):
    status = user.get("status", "unknown")
    lines = [
        f"{_status_icon(status)} {_display_name(user)}",
        f"Estado: {_status_label(status)}",
        f"user_id: {user.get('user_id')}",
        f"chat_id: {user.get('chat_id', 'N/D')}",
        f"Alta detectada: {_format_dt(user.get('first_seen_at'))}",
        f"Último uso: {_format_dt(user.get('last_used_at'))}",
    ]

    buttons = [[
        {"text": "📄 Ver detalles", "callback_data": f"control_detail:{user.get('user_id')}:{current_filter}:{page}"}
    ]]

    if status == "pending":
        buttons.append([
            {"text": "✅ Aprobar", "callback_data": f"control_approve:{user.get('user_id')}:{current_filter}:{page}"},
            {"text": "❌ Bloquear", "callback_data": f"control_block:{user.get('user_id')}:{current_filter}:{page}"},
        ])
    elif status == "approved":
        buttons.append([
            {"text": "❌ Bloquear", "callback_data": f"control_block:{user.get('user_id')}:{current_filter}:{page}"},
        ])
    elif status == "blocked":
        buttons.append([
            {"text": "✅ Aprobar", "callback_data": f"control_approve:{user.get('user_id')}:{current_filter}:{page}"},
        ])

    buttons.append([
        {"text": "⬅️ Volver", "callback_data": f"control_list:{current_filter}:{page}"},
    ])

    return {
        "type": "menu",
        "text": "\n".join(lines),
        "buttons": buttons,
    }


def build_user_details_menu(user, current_filter="all", page=0):
    status = user.get("status", "unknown")
    lines = [
        f"📄 Detalles de {_display_name(user)}",
        f"Estado: {_status_icon(status)} {_status_label(status)}",
        f"user_id: {user.get('user_id')}",
        f"chat_id: {user.get('chat_id', 'N/D')}",
        f"Username: @{user.get('username')}" if user.get("username") else "Username: N/D",
        f"Nombre: {user.get('first_name') or 'N/D'}",
        f"Primera vez visto: {_format_dt(user.get('first_seen_at'))}",
        f"Solicitud de acceso: {_format_dt(user.get('requested_at'))}",
        f"Aprobado: {_format_dt(user.get('approved_at'))}",
        f"Bloqueado: {_format_dt(user.get('blocked_at'))}",
        f"Último uso: {_format_dt(user.get('last_used_at'))}",
        f"Eventos registrados: {user.get('usage_count', 0)}",
    ]

    history = user.get("recent_inputs") or []
    if history:
        lines.append("")
        lines.append("Histórico reciente:")
        for item in history[:8]:
            text = item.get("text") or ""
            lines.append(f"- {_format_dt(item.get('at'))} | {text}")

    buttons = [[
        {"text": "⬅️ Volver al usuario", "callback_data": f"control_user:{user.get('user_id')}:{current_filter}:{page}"}
    ]]

    return {
        "type": "menu",
        "text": "\n".join(lines)[:4000],
        "buttons": buttons,
    }
