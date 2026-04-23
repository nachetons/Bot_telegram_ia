import threading


pending_followups = {}
pending_followups_lock = threading.Lock()
playlist_sessions = {}
playlist_sessions_lock = threading.Lock()
translate_sessions = {}
translate_sessions_lock = threading.Lock()
translate_results = {}
translate_results_lock = threading.Lock()
wallapop_sessions = {}
wallapop_sessions_lock = threading.Lock()
wallapop_result_sessions = {}
wallapop_result_sessions_lock = threading.Lock()
wallapop_item_messages = {}
wallapop_item_messages_lock = threading.Lock()
jellyfin_item_messages = {}
jellyfin_item_messages_lock = threading.Lock()
wallapop_alert_sessions = {}
wallapop_alert_sessions_lock = threading.Lock()


def set_pending_followup(chat_id, intent):
    with pending_followups_lock:
        pending_followups[chat_id] = intent


def pop_pending_followup(chat_id):
    with pending_followups_lock:
        return pending_followups.pop(chat_id, None)


def clear_pending_followup(chat_id):
    with pending_followups_lock:
        pending_followups.pop(chat_id, None)


def set_playlist_session(chat_id, action, playlist_name):
    with playlist_sessions_lock:
        playlist_sessions[chat_id] = {
            "action": action,
            "playlist": playlist_name,
        }


def get_playlist_session(chat_id):
    with playlist_sessions_lock:
        return playlist_sessions.get(chat_id)


def clear_playlist_session(chat_id):
    with playlist_sessions_lock:
        playlist_sessions.pop(chat_id, None)


def set_translate_session(chat_id, step, text_value=None):
    with translate_sessions_lock:
        translate_sessions[chat_id] = {
            "step": step,
            "text": text_value or "",
        }


def get_translate_session(chat_id):
    with translate_sessions_lock:
        return translate_sessions.get(chat_id)


def clear_translate_session(chat_id):
    with translate_sessions_lock:
        translate_sessions.pop(chat_id, None)


def set_wallapop_session(chat_id, payload):
    with wallapop_sessions_lock:
        wallapop_sessions[chat_id] = payload


def get_wallapop_session(chat_id):
    with wallapop_sessions_lock:
        return wallapop_sessions.get(chat_id)


def clear_wallapop_session(chat_id):
    with wallapop_sessions_lock:
        wallapop_sessions.pop(chat_id, None)


def set_wallapop_result_session(chat_id, payload):
    with wallapop_result_sessions_lock:
        wallapop_result_sessions[chat_id] = payload


def get_wallapop_result_session(chat_id):
    with wallapop_result_sessions_lock:
        return wallapop_result_sessions.get(chat_id)


def clear_wallapop_result_session(chat_id):
    with wallapop_result_sessions_lock:
        wallapop_result_sessions.pop(chat_id, None)


def set_wallapop_item_message(chat_id, payload):
    with wallapop_item_messages_lock:
        wallapop_item_messages[chat_id] = payload


def get_wallapop_item_message(chat_id):
    with wallapop_item_messages_lock:
        return wallapop_item_messages.get(chat_id)


def clear_wallapop_item_message(chat_id):
    with wallapop_item_messages_lock:
        wallapop_item_messages.pop(chat_id, None)


def set_jellyfin_item_message(chat_id, payload):
    with jellyfin_item_messages_lock:
        jellyfin_item_messages[chat_id] = payload


def get_jellyfin_item_message(chat_id):
    with jellyfin_item_messages_lock:
        return jellyfin_item_messages.get(chat_id)


def clear_jellyfin_item_message(chat_id):
    with jellyfin_item_messages_lock:
        jellyfin_item_messages.pop(chat_id, None)


def set_wallapop_alert_session(chat_id, payload):
    with wallapop_alert_sessions_lock:
        wallapop_alert_sessions[chat_id] = payload


def get_wallapop_alert_session(chat_id):
    with wallapop_alert_sessions_lock:
        return wallapop_alert_sessions.get(chat_id)


def clear_wallapop_alert_session(chat_id):
    with wallapop_alert_sessions_lock:
        wallapop_alert_sessions.pop(chat_id, None)


def set_translate_result(chat_id, payload):
    with translate_results_lock:
        translate_results[chat_id] = payload


def get_translate_result(chat_id):
    with translate_results_lock:
        return translate_results.get(chat_id)


def clear_translate_result(chat_id):
    with translate_results_lock:
        translate_results.pop(chat_id, None)


def clear_base_chat_state(chat_id):
    clear_pending_followup(chat_id)
    clear_playlist_session(chat_id)
    clear_translate_session(chat_id)


def clear_all_chat_state(chat_id):
    clear_pending_followup(chat_id)
    clear_playlist_session(chat_id)
    clear_translate_session(chat_id)
    clear_translate_result(chat_id)
    clear_wallapop_session(chat_id)
    clear_wallapop_result_session(chat_id)
    clear_wallapop_item_message(chat_id)
    clear_wallapop_alert_session(chat_id)
    clear_jellyfin_item_message(chat_id)
