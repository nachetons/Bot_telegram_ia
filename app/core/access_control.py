import json
import threading
from datetime import datetime
from pathlib import Path

from app.config import TELEGRAM_ADMIN_CHAT_IDS


_access_lock = threading.Lock()
_access_path = Path("data") / "access" / "users.json"


def _default_store():
    seeded_admins = [int(user_id) for user_id in TELEGRAM_ADMIN_CHAT_IDS]
    return {
        "admins": seeded_admins,
        "approved_users": seeded_admins.copy(),
        "blocked_users": [],
        "pending_users": [],
        "profiles": {},
    }


def _ensure_store():
    _access_path.parent.mkdir(parents=True, exist_ok=True)
    if not _access_path.exists():
        _access_path.write_text(
            json.dumps(_default_store(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _load_store():
    _ensure_store()
    try:
        data = json.loads(_access_path.read_text(encoding="utf-8") or "{}")
    except Exception:
        data = _default_store()

    default = _default_store()
    for key, value in default.items():
        data.setdefault(key, value)

    existing_admins = {int(user_id) for user_id in data.get("admins", []) if str(user_id).isdigit()}
    for admin_id in TELEGRAM_ADMIN_CHAT_IDS:
        existing_admins.add(int(admin_id))

    data["admins"] = sorted(existing_admins)

    approved = {int(user_id) for user_id in data.get("approved_users", []) if str(user_id).isdigit()}
    approved.update(existing_admins)
    data["approved_users"] = sorted(approved)

    blocked = {int(user_id) for user_id in data.get("blocked_users", []) if str(user_id).isdigit()}
    data["blocked_users"] = sorted(blocked)

    pending = []
    seen_pending = set()
    for item in data.get("pending_users", []):
        try:
            user_id = int(item.get("user_id"))
        except Exception:
            continue
        if user_id in seen_pending:
            continue
        seen_pending.add(user_id)
        item["user_id"] = user_id
        pending.append(item)
    data["pending_users"] = pending

    return data


def _save_store(data):
    _ensure_store()
    _access_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _ensure_profile(data, user_id, chat_id=None, username=None, first_name=None):
    profiles = data.setdefault("profiles", {})
    key = str(int(user_id))
    now = datetime.now().isoformat(timespec="seconds")
    profile = profiles.get(key)
    if not isinstance(profile, dict):
        profile = {
            "user_id": int(user_id),
            "chat_id": int(chat_id) if chat_id is not None else int(user_id),
            "username": username or "",
            "first_name": first_name or "",
            "first_seen_at": now,
            "requested_at": None,
            "approved_at": None,
            "blocked_at": None,
            "last_used_at": None,
            "usage_count": 0,
            "recent_inputs": [],
        }
        profiles[key] = profile

    if chat_id is not None:
        profile["chat_id"] = int(chat_id)
    if username:
        profile["username"] = username
    if first_name:
        profile["first_name"] = first_name
    profile.setdefault("recent_inputs", [])
    profile.setdefault("usage_count", 0)
    return profile


def _status_for_user(data, user_id):
    user_id = int(user_id)
    if user_id in {int(value) for value in data.get("blocked_users", [])}:
        return "blocked"
    if user_id in {int(value) for value in data.get("approved_users", [])}:
        return "approved"
    if any(int(item.get("user_id")) == user_id for item in data.get("pending_users", [])):
        return "pending"
    return "unknown"


def is_admin(user_id):
    if user_id is None:
        return False
    with _access_lock:
        data = _load_store()
        return int(user_id) in {int(value) for value in data.get("admins", [])}


def is_approved(user_id):
    if user_id is None:
        return False
    with _access_lock:
        data = _load_store()
        approved = {int(value) for value in data.get("approved_users", [])}
        return int(user_id) in approved


def is_blocked(user_id):
    if user_id is None:
        return False
    with _access_lock:
        data = _load_store()
        blocked = {int(value) for value in data.get("blocked_users", [])}
        return int(user_id) in blocked


def get_pending_request(user_id):
    if user_id is None:
        return None
    with _access_lock:
        data = _load_store()
        for item in data.get("pending_users", []):
            if int(item.get("user_id")) == int(user_id):
                return dict(item)
    return None


def register_access_request(user_id, chat_id=None, username=None, first_name=None):
    user_id = int(user_id)
    chat_id = int(chat_id) if chat_id is not None else user_id
    with _access_lock:
        data = _load_store()
        profile = _ensure_profile(data, user_id, chat_id, username, first_name)

        if user_id in {int(value) for value in data.get("blocked_users", [])}:
            return {"status": "blocked", "created": False}

        if user_id in {int(value) for value in data.get("approved_users", [])}:
            return {"status": "approved", "created": False}

        for item in data.get("pending_users", []):
            if int(item.get("user_id")) == user_id:
                return {"status": "pending", "created": False, "request": dict(item)}

        request_payload = {
            "user_id": user_id,
            "chat_id": chat_id,
            "username": username or "",
            "first_name": first_name or "",
            "requested_at": datetime.now().isoformat(timespec="seconds"),
        }
        profile["requested_at"] = request_payload["requested_at"]
        data.setdefault("pending_users", []).append(request_payload)
        _save_store(data)
        return {"status": "pending", "created": True, "request": request_payload}


def approve_user(user_id):
    user_id = int(user_id)
    with _access_lock:
        data = _load_store()
        profile = _ensure_profile(data, user_id)
        approved = {int(value) for value in data.get("approved_users", [])}
        approved.add(user_id)
        data["approved_users"] = sorted(approved)
        data["blocked_users"] = [int(value) for value in data.get("blocked_users", []) if int(value) != user_id]
        profile["approved_at"] = datetime.now().isoformat(timespec="seconds")
        profile["blocked_at"] = None

        approved_request = None
        remaining_pending = []
        for item in data.get("pending_users", []):
            if int(item.get("user_id")) == user_id and approved_request is None:
                approved_request = dict(item)
                continue
            remaining_pending.append(item)
        data["pending_users"] = remaining_pending
        _save_store(data)
        return approved_request


def block_user(user_id):
    user_id = int(user_id)
    with _access_lock:
        data = _load_store()
        profile = _ensure_profile(data, user_id)
        blocked = {int(value) for value in data.get("blocked_users", [])}
        blocked.add(user_id)
        data["blocked_users"] = sorted(blocked)
        data["approved_users"] = [int(value) for value in data.get("approved_users", []) if int(value) != user_id]
        profile["blocked_at"] = datetime.now().isoformat(timespec="seconds")

        blocked_request = None
        remaining_pending = []
        for item in data.get("pending_users", []):
            if int(item.get("user_id")) == user_id and blocked_request is None:
                blocked_request = dict(item)
                continue
            remaining_pending.append(item)
        data["pending_users"] = remaining_pending
        _save_store(data)
        return blocked_request


def list_admins():
    with _access_lock:
        data = _load_store()
        return [int(value) for value in data.get("admins", [])]


def record_user_activity(user_id, chat_id=None, username=None, first_name=None, text=None):
    if user_id is None:
        return None
    with _access_lock:
        data = _load_store()
        profile = _ensure_profile(data, int(user_id), chat_id, username, first_name)
        profile["last_used_at"] = datetime.now().isoformat(timespec="seconds")
        profile["usage_count"] = int(profile.get("usage_count", 0) or 0) + 1
        if text:
            history = list(profile.get("recent_inputs", []))
            history.insert(
                0,
                {
                    "text": str(text)[:300],
                    "at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            profile["recent_inputs"] = history[:20]
        _save_store(data)
        return dict(profile)


def list_users(status="all"):
    with _access_lock:
        data = _load_store()
        profiles = data.get("profiles", {})
        all_ids = set()
        all_ids.update(int(value) for value in data.get("approved_users", []))
        all_ids.update(int(value) for value in data.get("blocked_users", []))
        all_ids.update(int(item.get("user_id")) for item in data.get("pending_users", []) if str(item.get("user_id")).isdigit())
        all_ids.update(int(key) for key in profiles.keys() if str(key).isdigit())

        users = []
        for user_id in all_ids:
            current_status = _status_for_user(data, user_id)
            if status != "all" and current_status != status:
                continue
            profile = dict(profiles.get(str(user_id), {}))
            profile["user_id"] = user_id
            profile["status"] = current_status
            users.append(profile)

        status_rank = {"pending": 0, "approved": 1, "blocked": 2, "unknown": 3}
        def _timestamp(value):
            try:
                return datetime.fromisoformat(str(value)).timestamp()
            except Exception:
                return 0.0

        users.sort(
            key=lambda item: (
                status_rank.get(item.get("status"), 99),
                -_timestamp(item.get("last_used_at") or item.get("requested_at") or item.get("first_seen_at")),
            ),
        )
        return users


def get_user_details(user_id):
    user_id = int(user_id)
    with _access_lock:
        data = _load_store()
        profiles = data.get("profiles", {})
        profile = dict(profiles.get(str(user_id), {}))
        if not profile and _status_for_user(data, user_id) == "unknown":
            return None
        profile["user_id"] = user_id
        profile["status"] = _status_for_user(data, user_id)
        return profile
